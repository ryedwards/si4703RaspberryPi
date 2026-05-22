"""Si4703 FM Radio Receiver — main driver.

Register layout reference: Silicon Labs Si4702/03-C19 datasheet (rev C19-1).
Application note reference: AN230 "Si4700/01/02/03 Programming Guide".
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import smbus2 as smbus  # preferred: pure-Python, pip-installable
except ImportError:
    import smbus  # type: ignore[no-redef]  # fallback: system python3-smbus

try:
    import RPi.GPIO as GPIO  # type: ignore[import]
    _GPIO_AVAILABLE = True
except ImportError:  # allow import on non-Pi (e.g. for doc builds / type checking)
    GPIO = None  # type: ignore[assignment]
    _GPIO_AVAILABLE = False

from .exceptions import NotInitializedError, SeekFailedError, TuneTimeoutError
from .rds import RDSData, RDSDecoder

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Register addresses
# ──────────────────────────────────────────────────────────────────────────────
_REG_DEVICEID   = 0x00
_REG_CHIPID     = 0x01
_REG_POWERCFG   = 0x02
_REG_CHANNEL    = 0x03
_REG_SYSCONFIG1 = 0x04
_REG_SYSCONFIG2 = 0x05
_REG_SYSCONFIG3 = 0x06
_REG_TEST1      = 0x07
_REG_TEST2      = 0x08  # reserved — do not modify without reading first
_REG_BOOTCONFIG = 0x09  # reserved — do not modify without reading first
_REG_STATUSRSSI = 0x0A
_REG_READCHAN   = 0x0B
_REG_RDSA       = 0x0C
_REG_RDSB       = 0x0D
_REG_RDSC       = 0x0E
_REG_RDSD       = 0x0F

# ──────────────────────────────────────────────────────────────────────────────
# Bit-field positions
# ──────────────────────────────────────────────────────────────────────────────
# POWERCFG (0x02)
_DSMUTE  = 15   # Softmute disable
_DMUTE   = 14   # Mute disable  (1 = unmuted / audio on)
_MONO    = 13   # Mono select   (1 = force mono)
_RDSM    = 11   # RDS mode
_SKMODE  = 10   # Seek mode     (1 = stop at band limit, 0 = wrap)
_SEEKUP  = 9    # Seek direction (1 = up)
_SEEK    = 8    # Seek/start    (set 1 to begin, clears when done)
_DISABLE = 6    # Powerdown
_ENABLE  = 0    # Powerup

# CHANNEL (0x03)
_TUNE    = 15   # Start tuning when written 1

# SYSCONFIG1 (0x04)
_RDSIEN  = 15   # RDS interrupt enable
_STCIEN  = 14   # Seek/Tune Complete interrupt enable
_RDS     = 12   # RDS enable
_DE      = 11   # De-emphasis: 0=75µs (US), 1=50µs (Europe/Japan)
_AGCD    = 10   # AGC disable
_BLNDADJ = 6    # Stereo/Mono blend adjust [7:6]
_GPIO3   = 4    # GPIO3 [5:4]
_GPIO2   = 2    # GPIO2 [3:2]
_GPIO1   = 0    # GPIO1 [1:0]

# SYSCONFIG2 (0x05)
_SEEKTH  = 8    # Seek SNR threshold [15:8]
_BAND    = 6    # Band select [7:6]
_SPACE   = 4    # Channel spacing [5:4]
_VOLUME  = 0    # Volume [3:0]

# SYSCONFIG3 (0x06)
_SMUTER  = 14   # Softmute attack/recover rate [15:14]
_SMUTEA  = 12   # Softmute attenuation [13:12]
_VOLEXT  = 8    # Extended volume range (−28 dBfs)
_SKSNR   = 4    # Seek SNR threshold [7:4]
_SKCNT   = 0    # Seek FM impulse threshold [3:0]

# TEST1 (0x07)
_XOSCEN  = 15   # Crystal oscillator enable
_AHIZEN  = 14   # Audio high-Z enable

# STATUSRSSI (0x0A)   — read-only
_RDSR    = 15   # RDS ready (new group received)
_STC     = 14   # Seek/Tune Complete
_SFBL    = 13   # Seek Fail / Band Limit
_AFCRL   = 12   # AFC rail indicator
_RDSS    = 11   # RDS Synchronized
_BLERA   = 9    # Block A error level [10:9]
_ST      = 8    # Stereo indicator
_RSSI    = 0    # Signal strength [7:0]

# READCHAN (0x0B)     — read-only
_READCHAN_MASK = 0x03FF


# ──────────────────────────────────────────────────────────────────────────────
# Band / region configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Band:
    """Describes a regional FM broadcast band configuration.

    Choose one of the pre-defined constants:
    :data:`BAND_US`, :data:`BAND_EU`, :data:`BAND_JP_WIDE`, :data:`BAND_JP`.
    """

    name:            str    #: Human-readable name
    bottom_mhz:      float  #: Lowest tunable frequency (MHz)
    top_mhz:         float  #: Highest tunable frequency (MHz)
    spacing_khz:     int    #: Channel spacing (kHz) — determines tuning resolution
    band_bits:       int    #: SYSCONFIG2 BAND[1:0] register value
    space_bits:      int    #: SYSCONFIG2 SPACE[1:0] register value
    de_emphasis_us:  int    #: De-emphasis time constant µs (75 = US, 50 = EU/JP)

    @property
    def spacing_mhz(self) -> float:
        """Channel spacing in MHz."""
        return self.spacing_khz / 1000.0

    def freq_to_channel(self, freq_mhz: float) -> int:
        """Convert a frequency in MHz to a chip channel register value."""
        if not (self.bottom_mhz <= freq_mhz <= self.top_mhz):
            raise ValueError(
                f"{freq_mhz:.1f} MHz is outside the {self.name} band "
                f"({self.bottom_mhz}–{self.top_mhz} MHz)"
            )
        return round((freq_mhz - self.bottom_mhz) / self.spacing_mhz)

    def channel_to_freq(self, channel: int) -> float:
        """Convert a chip channel register value to a frequency in MHz."""
        return round(self.bottom_mhz + channel * self.spacing_mhz, 3)


#: USA / Australia — 87.5–108 MHz, 200 kHz spacing, 75 µs de-emphasis
BAND_US = Band(
    name="US/Australia",
    bottom_mhz=87.5, top_mhz=108.0,
    spacing_khz=200, band_bits=0b00, space_bits=0b00, de_emphasis_us=75,
)

#: Europe — 87.5–108 MHz, 100 kHz spacing, 50 µs de-emphasis
BAND_EU = Band(
    name="Europe",
    bottom_mhz=87.5, top_mhz=108.0,
    spacing_khz=100, band_bits=0b00, space_bits=0b01, de_emphasis_us=50,
)

#: Japan Wide — 76–108 MHz, 100 kHz spacing, 50 µs de-emphasis
BAND_JP_WIDE = Band(
    name="Japan Wide",
    bottom_mhz=76.0, top_mhz=108.0,
    spacing_khz=100, band_bits=0b01, space_bits=0b01, de_emphasis_us=50,
)

#: Japan — 76–90 MHz, 100 kHz spacing, 50 µs de-emphasis
BAND_JP = Band(
    name="Japan",
    bottom_mhz=76.0, top_mhz=90.0,
    spacing_khz=100, band_bits=0b10, space_bits=0b01, de_emphasis_us=50,
)


# ──────────────────────────────────────────────────────────────────────────────
# Main driver class
# ──────────────────────────────────────────────────────────────────────────────

class Si4703Radio:
    """Python driver for the Silicon Labs Si4702/Si4703 FM radio receiver.

    Communicates via I²C (SMBus) and controls reset/IRQ via RPi.GPIO.

    **Quick start** (context manager — handles power on/off automatically)::

        from si4703 import Si4703Radio, BAND_US

        with Si4703Radio(reset_pin=17) as radio:
            radio.frequency = 98.7   # tune to 98.7 MHz
            radio.volume    = 10     # 0 – 15
            print(f"{radio.frequency:.1f} MHz  RSSI={radio.rssi} dBµV  "
                  f"{'Stereo' if radio.is_stereo else 'Mono'}")

    **Manual power control**::

        radio = Si4703Radio(reset_pin=17)
        radio.power_on()
        ...
        radio.power_off()

    Args:
        reset_pin:   BCM GPIO pin number connected to the Si4703 ``/RST`` pin.
        i2c_address: I²C device address (default ``0x10``).
        i2c_bus:     I²C bus number (default ``1`` for all modern Raspberry Pis).
        irq_pin:     Optional BCM GPIO pin for the ``GPIO2``/``STC`` interrupt.
                     Enables faster seek/tune completion detection instead of polling.
        band:        Regional FM band configuration.  Defaults to :data:`BAND_US`.
    """

    def __init__(
        self,
        reset_pin:   int,
        i2c_address: int  = 0x10,
        i2c_bus:     int  = 1,
        irq_pin:     Optional[int] = None,
        band:        Band = BAND_US,
    ) -> None:
        if not _GPIO_AVAILABLE:
            raise ImportError(
                "RPi.GPIO is required.  Install it with: pip install RPi.GPIO  "
                "(or: sudo apt install python3-rpi.gpio)"
            )

        self._reset_pin  = reset_pin
        self._i2c_addr   = i2c_address
        self._irq_pin    = irq_pin
        self._band       = band
        self._regs: list[int] = [0] * 16
        self._initialized    = False

        # RDS
        self._rds_decoder  = RDSDecoder()
        self._rds_thread:   Optional[threading.Thread] = None
        self._rds_running   = threading.Event()
        self._rds_callback: Optional[Callable[[RDSData], None]] = None

        # Hardware setup
        self._i2c = smbus.SMBus(i2c_bus)
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(reset_pin, GPIO.OUT)
        GPIO.setup(0, GPIO.OUT)  # GPIO0 = SDA; must be driven LOW before reset
                                  # to put the chip into 2-wire (I²C) mode

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "Si4703Radio":
        self.power_on()
        return self

    def __exit__(self, *_: object) -> None:
        self.power_off()

    def __repr__(self) -> str:
        state = "on" if self._initialized else "off"
        return (
            f"<Si4703Radio band={self._band.name!r} "
            f"addr=0x{self._i2c_addr:02X} state={state}>"
        )

    # ── Power ─────────────────────────────────────────────────────────────────

    def power_on(self) -> None:
        """Power on and initialise the Si4703.

        Safe to call multiple times — a no-op if already initialised.
        """
        if self._initialized:
            return
        log.info("Powering on Si4703 (band=%s)…", self._band.name)

        # Put Si4703 into 2-wire mode:
        #   drive SDA (GPIO0) low, then toggle RST low → high.
        GPIO.output(0, GPIO.LOW)
        time.sleep(0.1)
        GPIO.output(self._reset_pin, GPIO.LOW)
        time.sleep(0.1)
        GPIO.output(self._reset_pin, GPIO.HIGH)
        time.sleep(0.1)

        # Step 1 — enable crystal oscillator (AN230 §2.1.1)
        self._read_regs()
        self._regs[_REG_TEST1] = 0x8100
        self._write_regs()
        time.sleep(0.5)  # clock must stabilise before proceeding

        # Step 2 — enable IC
        self._read_regs()
        self._regs[_REG_POWERCFG] = 0x4001  # DMUTE | ENABLE

        # SYSCONFIG1 — RDS on, de-emphasis, STC interrupt
        self._regs[_REG_SYSCONFIG1] |= (1 << _RDS)    # enable RDS
        if self._band.de_emphasis_us == 50:
            self._regs[_REG_SYSCONFIG1] |=  (1 << _DE)   # 50 µs — Europe/Japan
        else:
            self._regs[_REG_SYSCONFIG1] &= ~(1 << _DE)   # 75 µs — US/Australia
        self._regs[_REG_SYSCONFIG1] |= (1 << _GPIO2)  # GPIO2 = interrupt output

        if self._irq_pin is not None:
            GPIO.setup(self._irq_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._regs[_REG_SYSCONFIG1] |= (1 << _STCIEN)  # enable STC interrupt

        # SYSCONFIG2 — band, channel spacing, seek threshold, initial volume
        self._regs[_REG_SYSCONFIG2] |= (self._band.band_bits  << _BAND)
        self._regs[_REG_SYSCONFIG2] |= (self._band.space_bits << _SPACE)
        self._regs[_REG_SYSCONFIG2] |= (0x19 << _SEEKTH)  # recommended: AN230 p.40
        self._regs[_REG_SYSCONFIG2] &= 0xFFF0             # volume = 0 (start muted)

        # SYSCONFIG3 — seek SNR / impulse noise thresholds (AN230 p.40)
        self._regs[_REG_SYSCONFIG3] |= (0x04 << _SKSNR)
        self._regs[_REG_SYSCONFIG3] |= (0x08 << _SKCNT)

        self._write_regs()
        time.sleep(0.11)  # max powerup time per datasheet §2.2

        self._initialized = True
        log.info("Si4703 ready.")

    def power_off(self) -> None:
        """Power down the Si4703 and stop any background RDS thread."""
        self.stop_rds()
        if not self._initialized:
            return
        log.info("Powering off Si4703…")
        self._read_regs()
        # Powerdown sequence per AN230 §2.1.4
        self._regs[_REG_TEST1]      = 0x7C04
        self._regs[_REG_POWERCFG]   = 0x002A
        self._regs[_REG_SYSCONFIG1] = 0x0041
        self._write_regs()
        self._initialized = False

    # ── Frequency / tuning ────────────────────────────────────────────────────

    @property
    def frequency(self) -> float:
        """Current tuned frequency in MHz (e.g. ``98.7``).

        Read from the chip's ``READCHAN`` register so it always reflects what
        the AFC has actually locked onto.
        """
        self._check_initialized()
        self._read_regs()
        chan = self._regs[_REG_READCHAN] & _READCHAN_MASK
        return self._band.channel_to_freq(chan)

    @frequency.setter
    def frequency(self, freq_mhz: float) -> None:
        """Tune to *freq_mhz* MHz.

        Example::

            radio.frequency = 98.7
        """
        self._check_initialized()
        chan = self._band.freq_to_channel(freq_mhz)
        log.debug("Tuning %.1f MHz → channel %d", freq_mhz, chan)

        self._read_regs()
        self._regs[_REG_CHANNEL] &= 0xFE00      # clear channel bits
        self._regs[_REG_CHANNEL] |= chan          # set new channel
        self._regs[_REG_CHANNEL] |= (1 << _TUNE) # start tuning
        self._write_regs()

        self._wait_for_stc()

        self._read_regs()
        self._regs[_REG_CHANNEL] &= ~(1 << _TUNE)  # clear TUNE bit
        self._write_regs()

        self._rds_decoder.clear()
        log.info("Tuned to %.1f MHz", self.frequency)

    # ── Seek ──────────────────────────────────────────────────────────────────

    def seek(self, up: bool = True, wrap: bool = True) -> float:
        """Seek to the next valid FM station.

        Args:
            up:   ``True`` to seek towards higher frequencies (default),
                  ``False`` to seek towards lower.
            wrap: ``True`` to wrap around at the band edges (default).

        Returns:
            The frequency in MHz that the chip locked onto.

        Raises:
            :class:`~si4703.SeekFailedError`: If no valid station was found
                (chip reached band limit).
        """
        self._check_initialized()
        log.debug("Seeking %s…", "up" if up else "down")

        self._read_regs()
        # SKMODE: 0 = wrap at band limit, 1 = stop at band limit
        if wrap:
            self._regs[_REG_POWERCFG] &= ~(1 << _SKMODE)
        else:
            self._regs[_REG_POWERCFG] |=  (1 << _SKMODE)

        if up:
            self._regs[_REG_POWERCFG] |=  (1 << _SEEKUP)
        else:
            self._regs[_REG_POWERCFG] &= ~(1 << _SEEKUP)

        self._regs[_REG_POWERCFG] |= (1 << _SEEK)  # start seek
        self._write_regs()

        self._wait_for_stc()

        self._read_regs()
        failed = bool(self._regs[_REG_STATUSRSSI] & (1 << _SFBL))
        self._regs[_REG_POWERCFG] &= ~(1 << _SEEK)  # clear SEEK bit
        self._write_regs()

        freq = self.frequency
        if failed:
            raise SeekFailedError(
                f"Seek hit band limit at {freq:.1f} MHz — no station found"
            )

        self._rds_decoder.clear()
        log.info("Seek landed on %.1f MHz", freq)
        return freq

    def seek_up(self) -> float:
        """Seek to the next station above the current frequency."""
        return self.seek(up=True)

    def seek_down(self) -> float:
        """Seek to the next station below the current frequency."""
        return self.seek(up=False)

    def scan(self, min_rssi: int = 20) -> list[tuple[float, int]]:
        """Scan the full band and return every receivable station.

        Starts at the band bottom, seeks up repeatedly until the band limit
        is reached, and collects ``(frequency_mhz, rssi_dbuv)`` pairs.

        This is a slow operation — expect ~30–60 seconds for a full US band.

        Args:
            min_rssi: Minimum RSSI in dBµV to include in results.  Default 20.

        Returns:
            List of ``(freq_mhz, rssi)`` tuples, sorted by frequency.
        """
        self._check_initialized()
        log.info("Starting full band scan on %s band…", self._band.name)

        start_freq = self.frequency
        self.frequency = self._band.bottom_mhz

        found: list[tuple[float, int]] = []
        seen: set[float] = set()

        while True:
            try:
                freq = self.seek(up=True, wrap=False)
            except SeekFailedError:
                break

            if freq in seen:  # guard against a chip quirk that wraps anyway
                break
            seen.add(freq)

            rssi = self.rssi
            log.debug("  %.1f MHz  RSSI=%d dBµV", freq, rssi)
            if rssi >= min_rssi:
                found.append((freq, rssi))

        # Restore the original frequency (best-effort)
        try:
            self.frequency = start_freq
        except (ValueError, TuneTimeoutError):
            pass

        found.sort()
        log.info("Scan complete — %d stations found.", len(found))
        return found

    # ── Volume ────────────────────────────────────────────────────────────────

    @property
    def volume(self) -> int:
        """Audio volume, ``0`` (muted) – ``15`` (max)."""
        self._check_initialized()
        self._read_regs()
        return self._regs[_REG_SYSCONFIG2] & 0x000F

    @volume.setter
    def volume(self, value: int) -> None:
        """Set volume.  Clamped to the range ``0``–``15``."""
        self._check_initialized()
        value = max(0, min(15, value))
        self._read_regs()
        self._regs[_REG_SYSCONFIG2] &= 0xFFF0
        self._regs[_REG_SYSCONFIG2] |= value
        self._write_regs()

    def volume_up(self, step: int = 1) -> int:
        """Increase volume by *step* (default 1).  Returns new volume."""
        self.volume = self.volume + step
        return self.volume

    def volume_down(self, step: int = 1) -> int:
        """Decrease volume by *step* (default 1).  Returns new volume."""
        self.volume = self.volume - step
        return self.volume

    # ── Mute ──────────────────────────────────────────────────────────────────

    @property
    def muted(self) -> bool:
        """``True`` when audio output is muted."""
        self._check_initialized()
        self._read_regs()
        # DMUTE=1 → mute disabled (audio on); DMUTE=0 → muted
        return not bool(self._regs[_REG_POWERCFG] & (1 << _DMUTE))

    @muted.setter
    def muted(self, value: bool) -> None:
        self._check_initialized()
        self._read_regs()
        if value:
            self._regs[_REG_POWERCFG] &= ~(1 << _DMUTE)  # DMUTE=0 → muted
        else:
            self._regs[_REG_POWERCFG] |=  (1 << _DMUTE)  # DMUTE=1 → unmuted
        self._write_regs()

    def mute(self) -> None:
        """Mute audio output."""
        self.muted = True

    def unmute(self) -> None:
        """Unmute audio output."""
        self.muted = False

    # ── Mono / Stereo ─────────────────────────────────────────────────────────

    @property
    def mono(self) -> bool:
        """``True`` when the output is forced to mono.

        Forcing mono suppresses stereo blend noise on weak stations.
        """
        self._check_initialized()
        self._read_regs()
        return bool(self._regs[_REG_POWERCFG] & (1 << _MONO))

    @mono.setter
    def mono(self, value: bool) -> None:
        self._check_initialized()
        self._read_regs()
        if value:
            self._regs[_REG_POWERCFG] |=  (1 << _MONO)
        else:
            self._regs[_REG_POWERCFG] &= ~(1 << _MONO)
        self._write_regs()

    @property
    def is_stereo(self) -> bool:
        """``True`` if the chip has decoded a stereo pilot tone on the current station."""
        self._check_initialized()
        self._read_regs()
        return bool(self._regs[_REG_STATUSRSSI] & (1 << _ST))

    # ── Signal strength ───────────────────────────────────────────────────────

    @property
    def rssi(self) -> int:
        """Received Signal Strength Indicator in dBµV.

        Typical range 0–75; the chip's seek threshold defaults to ~25 dBµV.
        """
        self._check_initialized()
        self._read_regs()
        return self._regs[_REG_STATUSRSSI] & 0x00FF

    # ── RDS ───────────────────────────────────────────────────────────────────

    @property
    def rds(self) -> RDSData:
        """Current accumulated :class:`~si4703.RDSData` for the tuned station.

        Data fills in over time as RDS groups arrive — check the individual
        fields rather than assuming the whole object is populated immediately.
        Call :meth:`start_rds` to start the background collection thread.
        """
        return self._rds_decoder.data

    def start_rds(
        self,
        callback:      Optional[Callable[[RDSData], None]] = None,
        poll_interval: float = 0.04,
    ) -> None:
        """Start a background thread that continuously decodes RDS groups.

        Args:
            callback:      Optional function called with the :class:`~si4703.RDSData`
                           object every time a field is updated.  Called from the
                           background thread — keep it short or offload work.
            poll_interval: How often to read RDS registers (seconds).  Default
                           40 ms matches the chip's ~25 Hz RDS group rate.
        """
        if self._rds_thread and self._rds_thread.is_alive():
            return
        self._rds_callback = callback
        self._rds_running.set()
        self._rds_thread = threading.Thread(
            target=self._rds_loop,
            args=(poll_interval,),
            daemon=True,
            name="si4703-rds",
        )
        self._rds_thread.start()
        log.info("RDS background thread started.")

    def stop_rds(self) -> None:
        """Stop the background RDS thread (blocks until it exits)."""
        self._rds_running.clear()
        if self._rds_thread and self._rds_thread.is_alive():
            self._rds_thread.join(timeout=2.0)
            self._rds_thread = None
            log.info("RDS background thread stopped.")

    def _rds_loop(self, poll_interval: float) -> None:
        """Main loop for the RDS background thread."""
        while self._rds_running.is_set():
            try:
                self._read_regs()
                if self._regs[_REG_STATUSRSSI] & (1 << _RDSR):
                    changed = self._rds_decoder.process(
                        self._regs[_REG_RDSA],
                        self._regs[_REG_RDSB],
                        self._regs[_REG_RDSC],
                        self._regs[_REG_RDSD],
                    )
                    if changed and self._rds_callback:
                        try:
                            self._rds_callback(self._rds_decoder.data)
                        except Exception:
                            log.exception("Exception in RDS callback")
            except Exception:
                log.exception("Exception in RDS loop")
            time.sleep(poll_interval)

    # ── Chip information ──────────────────────────────────────────────────────

    @property
    def device_id(self) -> int:
        """Raw ``DEVICEID`` register value (upper word, 16-bit)."""
        self._read_regs()
        return self._regs[_REG_DEVICEID]

    @property
    def chip_id(self) -> int:
        """Raw ``CHIPID`` register value."""
        self._read_regs()
        return self._regs[_REG_CHIPID]

    # ── Low-level I²C register access ─────────────────────────────────────────

    def _write_regs(self) -> None:
        """Write registers 0x02–0x07 to the Si4703.

        The Si4703 I²C protocol does not use register addressing for writes —
        every write always begins at register 0x02.  SMBus ``write_i2c_block_data``
        sends ``[device_addr, "register" byte, data…]``; we use the high byte of
        POWERCFG (reg 0x02) as the command byte so the 12-byte payload covers
        all six registers correctly.
        """
        buf = bytearray(12)
        for i in range(6):
            buf[i * 2], buf[i * 2 + 1] = divmod(self._regs[i + 2], 0x100)
        # buf[0] is the "command" byte (high byte of reg 0x02); buf[1:] is the data
        self._i2c.write_i2c_block_data(self._i2c_addr, buf[0], list(buf[1:]))

    def _read_regs(self) -> None:
        """Read all 16 registers from the Si4703.

        The chip always starts its read burst at register 0x0A (STATUSRSSI)
        and wraps through 0x0F → 0x00 → … → 0x09.  We un-shuffle the result
        back into ``self._regs[0x00]``…``self._regs[0x0F]``.
        """
        cmd = self._regs[_REG_POWERCFG] >> 8  # any byte works; chip ignores it
        raw = self._i2c.read_i2c_block_data(self._i2c_addr, cmd, 32)
        idx = _REG_STATUSRSSI  # 0x0A — where the chip starts
        for i in range(16):
            self._regs[idx] = (raw[i * 2] << 8) | raw[i * 2 + 1]
            idx = (idx + 1) & 0x0F  # wrap 0x0F → 0x00

    def _wait_for_stc(self, timeout: float = 5.0) -> None:
        """Block until the Seek/Tune Complete (STC) bit is asserted.

        Uses GPIO interrupt if *irq_pin* was provided; otherwise polls.

        Raises:
            :class:`~si4703.TuneTimeoutError`: If STC does not set within *timeout*.
        """
        if self._irq_pin is not None:
            result = GPIO.wait_for_edge(
                self._irq_pin, GPIO.FALLING, timeout=int(timeout * 1000)
            )
            if result is None:
                raise TuneTimeoutError(
                    f"STC interrupt did not fire within {timeout:.1f}s"
                )
        else:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self._read_regs()
                if self._regs[_REG_STATUSRSSI] & (1 << _STC):
                    return
                time.sleep(0.01)
            raise TuneTimeoutError(
                f"STC bit did not set within {timeout:.1f}s (polling)"
            )

    def _check_initialized(self) -> None:
        if not self._initialized:
            raise NotInitializedError(
                "Radio is not powered on.  Call power_on() or use as a context manager."
            )
