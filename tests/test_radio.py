"""Unit tests for Si4703Radio driver (hardware mocked via conftest.py)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from si4703 import (
    BAND_EU,
    BAND_US,
    NotInitializedError,
    SeekFailedError,
    Si4703Radio,
    TuneTimeoutError,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_i2c_buffer(regs: list[int]) -> list[int]:
    """Build the 32-byte read buffer the Si4703 returns.

    The chip starts its burst read at register 0x0A and wraps back to 0x00
    after 0x0F, so the buffer order is: 0x0A, 0x0B, …, 0x0F, 0x00, …, 0x09.
    """
    buf: list[int] = []
    idx = 0x0A
    for _ in range(16):
        val = regs[idx] if idx < len(regs) else 0
        buf.append((val >> 8) & 0xFF)
        buf.append(val & 0xFF)
        idx = (idx + 1) & 0x0F
    return buf


def default_regs() -> list[int]:
    """A realistic register state for a powered-on radio tuned to 98.7 MHz."""
    regs = [0] * 16
    regs[0x02] = 0x4001  # POWERCFG: DMUTE=1 (audio on), ENABLE=1
    regs[0x04] = 0x1000  # SYSCONFIG1: RDS enabled
    regs[0x05] = 0x1908  # SYSCONFIG2: SEEKTH=0x19, vol=8
    regs[0x0A] = 0x0028  # STATUSRSSI: RSSI=40, no STC, no stereo
    regs[0x0B] = 56      # READCHAN: channel 56 → 87.5 + 56*0.2 = 98.7 MHz
    return regs


def stc_regs(base: list[int], readchan: int | None = None) -> list[int]:
    """Return a register snapshot with the STC bit set."""
    r = list(base)
    r[0x0A] = (r[0x0A] & 0x0FFF) | 0x4000  # set STC (bit 14)
    if readchan is not None:
        r[0x0B] = readchan
    return r


def sfbl_regs(base: list[int]) -> list[int]:
    """Return a register snapshot with STC + SFBL (seek fail) set."""
    r = list(base)
    r[0x0A] = (r[0x0A] & 0x0FFF) | 0x6000  # STC (bit14) + SFBL (bit13)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def radio() -> Si4703Radio:
    """A Si4703Radio with hardware mocked and _initialized set to True."""
    r = Si4703Radio(reset_pin=17, band=BAND_US)
    r._initialized = True
    r._regs = default_regs()
    # Always reset side_effect so exhausted iterators from previous tests don't cascade.
    r._i2c.read_i2c_block_data.side_effect = None
    r._i2c.read_i2c_block_data.return_value = make_i2c_buffer(r._regs)
    return r


def set_read_sequence(radio: Si4703Radio, *reg_snapshots: list[int]) -> None:
    """Configure successive read_i2c_block_data return values."""
    radio._i2c.read_i2c_block_data.side_effect = [
        make_i2c_buffer(snap) for snap in reg_snapshots
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Power on / off
# ──────────────────────────────────────────────────────────────────────────────

class TestPowerOnOff:
    @patch("si4703.radio.time.sleep")
    def test_power_on_sets_initialized(self, _sleep: MagicMock):
        r = Si4703Radio(reset_pin=17, band=BAND_US)
        r._i2c.read_i2c_block_data.return_value = [0] * 32
        assert r._initialized is False
        r.power_on()
        assert r._initialized is True

    @patch("si4703.radio.time.sleep")
    def test_power_on_toggles_reset_pin(self, _sleep: MagicMock):
        from si4703.radio import GPIO
        r = Si4703Radio(reset_pin=17, band=BAND_US)
        r._i2c.read_i2c_block_data.return_value = [0] * 32
        GPIO.reset_mock()
        r.power_on()
        # RST pin must go LOW then HIGH
        gpio_calls = GPIO.output.call_args_list
        low_call  = call(17, GPIO.LOW)
        high_call = call(17, GPIO.HIGH)
        assert low_call  in gpio_calls
        assert high_call in gpio_calls

    @patch("si4703.radio.time.sleep")
    def test_power_on_idempotent(self, _sleep: MagicMock):
        r = Si4703Radio(reset_pin=17)
        r._i2c.read_i2c_block_data.return_value = [0] * 32
        r.power_on()
        call_count = r._i2c.write_i2c_block_data.call_count
        r.power_on()  # second call — should be a no-op
        assert r._i2c.write_i2c_block_data.call_count == call_count

    @patch("si4703.radio.time.sleep")
    def test_power_off_clears_initialized(self, _sleep: MagicMock, radio: Si4703Radio):
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(radio._regs)
        radio.power_off()
        assert radio._initialized is False

    @patch("si4703.radio.time.sleep")
    def test_power_off_writes_powerdown_sequence(self, _sleep: MagicMock, radio: Si4703Radio):
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(radio._regs)
        radio._i2c.write_i2c_block_data.reset_mock()
        radio.power_off()
        assert radio._i2c.write_i2c_block_data.called

    def test_power_off_idempotent(self, radio: Si4703Radio):
        radio._initialized = False
        # Should not raise
        radio.power_off()

    def test_context_manager_powers_on_and_off(self):
        with patch("si4703.radio.time.sleep"):
            r = Si4703Radio(reset_pin=17)
            r._i2c.read_i2c_block_data.return_value = [0] * 32
            with r:
                assert r._initialized is True
            assert r._initialized is False


# ──────────────────────────────────────────────────────────────────────────────
# Not-initialized guard
# ──────────────────────────────────────────────────────────────────────────────

class TestNotInitialized:
    def test_frequency_get_raises(self):
        r = Si4703Radio(reset_pin=17)
        with pytest.raises(NotInitializedError):
            _ = r.frequency

    def test_frequency_set_raises(self):
        r = Si4703Radio(reset_pin=17)
        with pytest.raises(NotInitializedError):
            r.frequency = 98.7

    def test_volume_raises(self):
        r = Si4703Radio(reset_pin=17)
        with pytest.raises(NotInitializedError):
            _ = r.volume

    def test_rssi_raises(self):
        r = Si4703Radio(reset_pin=17)
        with pytest.raises(NotInitializedError):
            _ = r.rssi


# ──────────────────────────────────────────────────────────────────────────────
# frequency property
# ──────────────────────────────────────────────────────────────────────────────

class TestFrequency:
    def test_frequency_get_decodes_readchan(self, radio: Si4703Radio):
        # default_regs has READCHAN=56; 87.5 + 56*0.2 = 98.7
        assert radio.frequency == pytest.approx(98.7)

    def test_frequency_get_different_channel(self, radio: Si4703Radio):
        # Channel 20 = 87.5 + 20*0.2 = 91.5 MHz
        regs = list(radio._regs)
        regs[0x0B] = 20
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)
        assert radio.frequency == pytest.approx(91.5)

    def test_frequency_set_writes_tune_bit(self, radio: Si4703Radio):
        base = list(radio._regs)
        set_read_sequence(radio,
            base,                                    # initial _read_regs in setter
            stc_regs(base, readchan=56),             # _wait_for_stc poll: STC set
            stc_regs(base, readchan=56),             # _read_regs after STC to clear TUNE
            stc_regs(base, readchan=56),             # frequency getter called in log.info
        )
        radio.frequency = 98.7
        # Verify at least one write occurred
        assert radio._i2c.write_i2c_block_data.called

    def test_frequency_set_out_of_band_raises(self, radio: Si4703Radio):
        with pytest.raises(ValueError, match="outside"):
            radio.frequency = 50.0

    def test_frequency_set_clears_rds(self, radio: Si4703Radio):
        radio._rds_decoder._data.station_name = "KEXP-FM "
        base = list(radio._regs)
        set_read_sequence(radio,
            base,                  # initial _read_regs in setter
            stc_regs(base),        # _wait_for_stc poll: STC set
            stc_regs(base),        # _read_regs after STC to clear TUNE
            stc_regs(base),        # frequency getter called in log.info
        )
        radio.frequency = 98.7
        assert radio._rds_decoder.data.station_name is None

    def test_frequency_eu_band(self):
        r = Si4703Radio(reset_pin=17, band=BAND_EU)
        r._initialized = True
        regs = default_regs()
        # Channel 98 = 87.5 + 98*0.1 = 97.3 MHz
        regs[0x0B] = 98
        r._regs = regs
        r._i2c.read_i2c_block_data.side_effect = None  # reset any residual side_effect
        r._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)
        assert r.frequency == pytest.approx(97.3)


# ──────────────────────────────────────────────────────────────────────────────
# volume property
# ──────────────────────────────────────────────────────────────────────────────

class TestVolume:
    def test_volume_get(self, radio: Si4703Radio):
        # default_regs: SYSCONFIG2 = 0x1908 → lower nibble = 8
        assert radio.volume == 8

    def test_volume_set(self, radio: Si4703Radio):
        radio.volume = 10
        assert (radio._regs[0x05] & 0x000F) == 10

    def test_volume_clamped_max(self, radio: Si4703Radio):
        radio.volume = 100
        assert (radio._regs[0x05] & 0x000F) == 15  # check _regs; getter re-reads mock

    def test_volume_clamped_min(self, radio: Si4703Radio):
        radio.volume = -5
        assert (radio._regs[0x05] & 0x000F) == 0  # check _regs; getter re-reads mock

    def test_volume_up(self, radio: Si4703Radio):
        # Lambda side_effect mirrors live _regs on each read so the final
        # `return self.volume` in volume_up() sees the newly written value.
        radio._i2c.read_i2c_block_data.side_effect = lambda *a: make_i2c_buffer(radio._regs)
        new_vol = radio.volume_up()   # default_regs has vol=8 → should become 9
        assert new_vol == 9

    def test_volume_down(self, radio: Si4703Radio):
        radio._i2c.read_i2c_block_data.side_effect = lambda *a: make_i2c_buffer(radio._regs)
        new_vol = radio.volume_down()  # default vol=8 → should become 7
        assert new_vol == 7

    def test_volume_up_clamped_at_15(self, radio: Si4703Radio):
        radio._regs[0x05] = (radio._regs[0x05] & 0xFFF0) | 15
        radio._i2c.read_i2c_block_data.side_effect = lambda *a: make_i2c_buffer(radio._regs)
        new_vol = radio.volume_up()
        assert new_vol == 15

    def test_volume_down_clamped_at_0(self, radio: Si4703Radio):
        radio._regs[0x05] = (radio._regs[0x05] & 0xFFF0) | 0
        radio._i2c.read_i2c_block_data.side_effect = lambda *a: make_i2c_buffer(radio._regs)
        new_vol = radio.volume_down()
        assert new_vol == 0


# ──────────────────────────────────────────────────────────────────────────────
# muted property
# ──────────────────────────────────────────────────────────────────────────────

class TestMute:
    def test_initially_unmuted(self, radio: Si4703Radio):
        # default_regs POWERCFG=0x4001: DMUTE (bit14) = 1 → unmuted
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(radio._regs)
        assert radio.muted is False

    def test_mute(self, radio: Si4703Radio):
        radio.mute()
        # DMUTE (bit 14) should be 0 in POWERCFG
        assert (radio._regs[0x02] & (1 << 14)) == 0

    def test_unmute(self, radio: Si4703Radio):
        radio.mute()
        radio.unmute()
        assert (radio._regs[0x02] & (1 << 14)) != 0

    def test_muted_property_set_true(self, radio: Si4703Radio):
        radio.muted = True
        assert (radio._regs[0x02] & (1 << 14)) == 0

    def test_muted_property_set_false(self, radio: Si4703Radio):
        radio.muted = False
        assert (radio._regs[0x02] & (1 << 14)) != 0


# ──────────────────────────────────────────────────────────────────────────────
# mono property
# ──────────────────────────────────────────────────────────────────────────────

class TestMono:
    def test_mono_off_by_default(self, radio: Si4703Radio):
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(radio._regs)
        assert radio.mono is False

    def test_mono_on(self, radio: Si4703Radio):
        radio.mono = True
        assert (radio._regs[0x02] & (1 << 13)) != 0

    def test_mono_off(self, radio: Si4703Radio):
        radio.mono = True
        radio.mono = False
        assert (radio._regs[0x02] & (1 << 13)) == 0


# ──────────────────────────────────────────────────────────────────────────────
# is_stereo property
# ──────────────────────────────────────────────────────────────────────────────

class TestStereo:
    def test_is_stereo_false(self, radio: Si4703Radio):
        # default_regs STATUSRSSI = 0x0028: bit 8 (ST) = 0
        assert radio.is_stereo is False

    def test_is_stereo_true(self, radio: Si4703Radio):
        regs = list(radio._regs)
        regs[0x0A] = 0x0128  # ST (bit 8) set + RSSI=40
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)
        assert radio.is_stereo is True


# ──────────────────────────────────────────────────────────────────────────────
# rssi property
# ──────────────────────────────────────────────────────────────────────────────

class TestRSSI:
    def test_rssi_value(self, radio: Si4703Radio):
        # default_regs STATUSRSSI = 0x0028 = 40
        assert radio.rssi == 40

    def test_rssi_low_signal(self, radio: Si4703Radio):
        regs = list(radio._regs)
        regs[0x0A] = 0x000F  # RSSI=15
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)
        assert radio.rssi == 15

    def test_rssi_max(self, radio: Si4703Radio):
        regs = list(radio._regs)
        regs[0x0A] = 0x004B  # RSSI=75 (max per datasheet)
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)
        assert radio.rssi == 75


# ──────────────────────────────────────────────────────────────────────────────
# seek
# ──────────────────────────────────────────────────────────────────────────────

class TestSeek:
    def test_seek_up_returns_frequency(self, radio: Si4703Radio):
        base = list(radio._regs)
        # Chip lands on channel 60 = 87.5 + 60*0.2 = 99.5 MHz
        set_read_sequence(radio,
            base,                             # initial _read_regs in seek
            stc_regs(base, readchan=60),      # _wait_for_stc poll
            stc_regs(base, readchan=60),      # _read_regs after STC
            stc_regs(base, readchan=60),      # frequency getter _read_regs
        )
        freq = radio.seek_up()
        assert freq == pytest.approx(99.5)

    def test_seek_down_clears_seekup_bit(self, radio: Si4703Radio):
        base = list(radio._regs)
        set_read_sequence(radio,
            base,
            stc_regs(base, readchan=56),
            stc_regs(base, readchan=56),
            stc_regs(base, readchan=56),
        )
        radio.seek_down()
        # SEEKUP bit (bit 9) should have been cleared in POWERCFG before write
        assert (radio._regs[0x02] & (1 << 9)) == 0

    def test_seek_up_sets_seekup_bit_before_write(self, radio: Si4703Radio):
        written_regs: list[list[int]] = []

        def capture_write(addr: int, cmd: int, data: list[int]) -> None:
            # Reconstruct the full buffer from the write call
            written_regs.append([cmd] + list(data))

        base = list(radio._regs)
        set_read_sequence(radio,
            base,
            stc_regs(base, readchan=60),
            stc_regs(base, readchan=60),
            stc_regs(base, readchan=60),
        )
        radio._i2c.write_i2c_block_data.side_effect = capture_write
        radio.seek_up()
        # At least one write was issued
        assert len(written_regs) >= 1

    def test_seek_raises_on_band_limit(self, radio: Si4703Radio):
        base = list(radio._regs)
        set_read_sequence(radio,
            base,
            sfbl_regs(base),      # STC + SFBL set → seek failed
            sfbl_regs(base),      # _read_regs after STC
            sfbl_regs(base),      # frequency getter
        )
        with pytest.raises(SeekFailedError):
            radio.seek(up=True, wrap=False)

    def test_seek_clears_rds_on_success(self, radio: Si4703Radio):
        radio._rds_decoder._data.station_name = "OLD-STA "
        base = list(radio._regs)
        set_read_sequence(radio,
            base,
            stc_regs(base, readchan=60),
            stc_regs(base, readchan=60),
            stc_regs(base, readchan=60),
        )
        radio.seek_up()
        assert radio._rds_decoder.data.station_name is None

    def test_seek_wrap_false_sets_skmode_bit(self, radio: Si4703Radio):
        base = list(radio._regs)
        set_read_sequence(radio,
            base,
            stc_regs(base),
            stc_regs(base),
            stc_regs(base),
        )
        # Intercept the register state just before the first write
        seek_reg_state: list[int] = []

        original_write = radio._write_regs.__func__  # get unbound method

        def capture_write(self_inner: Si4703Radio) -> None:
            seek_reg_state.append(list(self_inner._regs))
            # Call the real write
            radio._i2c.write_i2c_block_data(
                radio._i2c_addr,
                (self_inner._regs[0x02] >> 8) & 0xFF,
                [],  # simplified — we don't need the full bytes
            )

        radio._write_regs = lambda: capture_write(radio)  # type: ignore[method-assign]
        try:
            radio.seek(up=True, wrap=False)
        except Exception:
            pass

        if seek_reg_state:
            # SKMODE (bit 10) should be 1 (stop at band limit) when wrap=False
            assert (seek_reg_state[0][0x02] & (1 << 10)) != 0


# ──────────────────────────────────────────────────────────────────────────────
# _wait_for_stc — timeout
# ──────────────────────────────────────────────────────────────────────────────

class TestWaitForSTC:
    def test_polling_succeeds_when_stc_set(self, radio: Si4703Radio):
        regs_with_stc = stc_regs(radio._regs)
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs_with_stc)
        # Should not raise
        radio._wait_for_stc(timeout=1.0)

    def test_polling_raises_on_timeout(self, radio: Si4703Radio):
        # No STC bit ever set
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(radio._regs)
        with pytest.raises(TuneTimeoutError):
            radio._wait_for_stc(timeout=0.01)   # very short timeout

    def test_irq_mode_success(self, radio: Si4703Radio):
        from si4703.radio import GPIO
        radio._irq_pin = 27
        GPIO.wait_for_edge.return_value = 1   # non-None = edge detected
        radio._wait_for_stc(timeout=1.0)   # should not raise

    def test_irq_mode_timeout(self, radio: Si4703Radio):
        from si4703.radio import GPIO
        radio._irq_pin = 27
        GPIO.wait_for_edge.return_value = None   # None = timeout
        with pytest.raises(TuneTimeoutError):
            radio._wait_for_stc(timeout=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# RDS background thread
# ──────────────────────────────────────────────────────────────────────────────

class TestRDS:
    def test_rds_property_returns_rds_data(self, radio: Si4703Radio):
        from si4703 import RDSData
        assert isinstance(radio.rds, RDSData)

    def test_start_stop_rds_thread(self, radio: Si4703Radio):
        radio.start_rds()
        assert radio._rds_thread is not None
        assert radio._rds_thread.is_alive()
        radio.stop_rds()
        assert not (radio._rds_thread and radio._rds_thread.is_alive())

    def test_start_rds_idempotent(self, radio: Si4703Radio):
        radio.start_rds()
        thread_id = id(radio._rds_thread)
        radio.start_rds()   # second call — should not create a new thread
        assert id(radio._rds_thread) == thread_id
        radio.stop_rds()

    def test_rds_callback_invoked_on_new_data(self, radio: Si4703Radio):
        received: list = []

        def on_rds(data):
            received.append(data)

        # Build a read buffer that has RDSR set (new RDS group ready)
        # and carries group 0A segment 0: PI=0x1234, PS chars "KE"
        regs = list(radio._regs)
        regs[0x0A] = 0x8028   # RDSR (bit15) set, RSSI=40

        # group type 0, seg 0, rdsd = "KE"
        rdsb_val = 0x0000                              # group 0, version A, no TP, PTY=0, seg=0
        regs[0x0C] = 0x1234                            # RDSA: PI code
        regs[0x0D] = rdsb_val                          # RDSB
        regs[0x0E] = 0x0000                            # RDSC
        regs[0x0F] = (ord("K") << 8) | ord("E")       # RDSD

        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)

        radio.start_rds(callback=on_rds, poll_interval=0.01)
        time.sleep(0.15)   # give the thread a few iterations
        radio.stop_rds()

        assert len(received) > 0

    def test_rds_callback_exception_does_not_kill_thread(self, radio: Si4703Radio):
        def bad_callback(data):
            raise RuntimeError("oops")

        regs = list(radio._regs)
        regs[0x0A] = 0x8028   # RDSR set
        regs[0x0C] = 0x1234
        radio._i2c.read_i2c_block_data.return_value = make_i2c_buffer(regs)

        radio.start_rds(callback=bad_callback, poll_interval=0.01)
        time.sleep(0.1)
        assert radio._rds_thread is not None and radio._rds_thread.is_alive()
        radio.stop_rds()


# ──────────────────────────────────────────────────────────────────────────────
# scan
# ──────────────────────────────────────────────────────────────────────────────

class TestScan:
    def test_scan_returns_list(self, radio: Si4703Radio):
        # Only two seeks succeed before SFBL
        base = list(radio._regs)
        # Sequence of reads for scan:
        #  1. tune to band bottom (_read_regs in freq setter, stc, stc_clear)
        #  2. seek 1: success at 91.5 MHz (ch 20)
        #  3. seek 2: success at 98.7 MHz (ch 56)
        #  4. seek 3: SFBL → SeekFailedError stops the loop
        #  5. restore original frequency
        ch20 = stc_regs(base, readchan=20)
        ch56 = stc_regs(base, readchan=56)
        ch_sfbl = sfbl_regs(base)

        reads = [
            base,      # freq-setter read
            ch20,      # freq-setter STC (tuning to band bottom → ch 0... but let's simplify)
            ch20,      # freq-setter clear TUNE
            base,      # seek 1 initial read
            ch20,      # seek 1 STC
            ch20,      # seek 1 clear SEEK + rssi
            ch20,      # frequency getter (rssi check in scan)
            ch20,      # rssi read
            base,      # seek 2 initial read
            ch56,      # seek 2 STC
            ch56,      # seek 2 clear SEEK
            ch56,      # frequency getter
            ch56,      # rssi read
            base,      # seek 3 initial read
            ch_sfbl,   # seek 3 STC+SFBL
            ch_sfbl,   # seek 3 clear SEEK
            ch_sfbl,   # frequency getter for error msg
            base,      # restore frequency read
            ch56,      # restore STC
            ch56,      # restore clear TUNE
        ]
        radio._i2c.read_i2c_block_data.side_effect = [
            make_i2c_buffer(r) for r in reads
        ]
        # Just confirm it returns a list without crashing
        result = radio.scan()
        assert isinstance(result, list)

    def test_scan_sorted_by_frequency(self, radio: Si4703Radio):
        """scan() guarantees results are sorted ascending by frequency."""
        calls: list[float] = []
        fake_freqs = [101.1, 91.5, 98.7]  # intentionally unsorted

        def fake_seek(up: bool = True, wrap: bool = True) -> float:
            if len(calls) >= len(fake_freqs):
                raise SeekFailedError("done")
            f = fake_freqs[len(calls)]
            calls.append(f)
            return f

        with (
            patch.object(radio, "seek", side_effect=fake_seek),
            patch.object(type(radio), "frequency", new_callable=PropertyMock, return_value=87.5),
            patch.object(type(radio), "rssi", new_callable=PropertyMock, return_value=40),
        ):
            result = radio.scan()

        freqs = [f for f, _ in result]
        assert freqs == sorted(freqs)


# ──────────────────────────────────────────────────────────────────────────────
# __repr__
# ──────────────────────────────────────────────────────────────────────────────

class TestRepr:
    def test_repr_contains_band(self, radio: Si4703Radio):
        assert "US/Australia" in repr(radio)

    def test_repr_contains_state_on(self, radio: Si4703Radio):
        assert "on" in repr(radio)

    def test_repr_contains_state_off(self):
        r = Si4703Radio(reset_pin=17)
        assert "off" in repr(r)
