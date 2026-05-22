# si4703 — FM Radio Receiver for Raspberry Pi

Python 3 driver for the **Silicon Labs Si4702/Si4703** FM radio receiver chip.
Clean, modern API.  pip-installable.  Context-manager friendly.  Full RDS/RBDS decoding.  Built-in band scanner.  Comes with a curses interactive UI.

```
$ si4703 --reset-pin 17 tune 98.7 --volume 10 --rds
Tuned:  98.7 MHz   RSSI: 47 dBµV   Stereo   Vol: 10
Listening for RDS...  (timeout 20s, Ctrl+C to stop early)
  RDS: [KEXP-FM]  Alternative  "The Wipers - Romeo"

Final RDS snapshot:
  [KEXP-FM]  Alternative  "The Wipers - Romeo"  Clock: 14:32+00:00
```

---

## Installation

```bash
pip install si4703
```

> **Note:** `RPi.GPIO` is required on Raspberry Pi.  If it is not already installed:
> ```bash
> sudo apt install python3-rpi.gpio    # from apt
> # or
> pip install RPi.GPIO                 # from pip
> ```

### Hardware wiring (SparkFun Si4703 breakout)

| Si4703 pin | Raspberry Pi       |
|------------|--------------------|
| SDA        | GPIO 2 (I2C SDA)   |
| SCL        | GPIO 3 (I2C SCL)   |
| RST        | any free GPIO, e.g. **GPIO 17** |
| GPIO2      | any free GPIO, e.g. **GPIO 27** (optional IRQ) |
| 3.3V       | 3.3 V              |
| GND        | GND                |

Confirm the I2C address (should be `0x10`):
```bash
sudo i2cdetect -y 1
```

---

## Quick start

```python
from si4703 import Si4703Radio, BAND_US

with Si4703Radio(reset_pin=17) as radio:
    radio.frequency = 98.7   # tune to 98.7 MHz
    radio.volume    = 10     # 0 - 15

    print(f"{radio.frequency:.1f} MHz")
    print(f"RSSI  : {radio.rssi} dBuV")
    print(f"Stereo: {radio.is_stereo}")
```

---

## API reference

### `Si4703Radio(reset_pin, *, i2c_address=0x10, i2c_bus=1, irq_pin=None, band=BAND_US)`

| Parameter     | Description |
|---------------|-------------|
| `reset_pin`   | BCM GPIO pin connected to `/RST` on the Si4703 |
| `i2c_address` | I2C address (default `0x10`) |
| `i2c_bus`     | I2C bus number (default `1`) |
| `irq_pin`     | Optional BCM GPIO pin for the `STC` interrupt -- enables faster seek/tune vs. polling |
| `band`        | Regional FM band -- `BAND_US`, `BAND_EU`, `BAND_JP_WIDE`, `BAND_JP` |

#### Context manager

```python
with Si4703Radio(reset_pin=17) as radio:
    ...  # radio is powered on; automatically powered off on exit
```

#### Properties

| Property     | Type    | R/W | Description |
|--------------|---------|-----|-------------|
| `frequency`  | `float` | R/W | Tuned frequency in MHz.  Set to tune: `radio.frequency = 98.7` |
| `volume`     | `int`   | R/W | Audio volume `0`-`15` |
| `muted`      | `bool`  | R/W | Mute state |
| `mono`       | `bool`  | R/W | Force mono output (reduces stereo blend noise on weak signals) |
| `is_stereo`  | `bool`  | R   | `True` if the chip detected a stereo pilot tone |
| `rssi`       | `int`   | R   | Received signal strength in dBuV (0-75) |
| `rds`        | `RDSData` | R | Current accumulated RDS data (see below) |

#### Methods

```python
# Tuning
radio.frequency = 98.7          # set property to tune
radio.seek_up()                 # returns float (new frequency)
radio.seek_down()               # returns float
radio.seek(up=True, wrap=True)  # returns float

# Full band scan
stations = radio.scan()         # returns [(freq_mhz, rssi_dbuv), ...]
stations = radio.scan(min_rssi=30)

# Volume helpers
radio.volume_up()               # returns int (new volume)
radio.volume_down()

# Mute helpers
radio.mute()
radio.unmute()

# Power control (not needed when using context manager)
radio.power_on()
radio.power_off()

# RDS background thread
radio.start_rds(callback=lambda rds: print(rds))
radio.stop_rds()
```

---

### `RDSData`

Filled in progressively as RDS groups arrive.  Fields start as `None` and
populate over roughly 5-30 seconds depending on the station.

| Field                  | Type             | Description |
|------------------------|------------------|-------------|
| `station_name`         | `str or None`    | PS -- 8-character station name |
| `radio_text`           | `str or None`    | RT -- scrolling text (up to 64 chars) |
| `program_type`         | `ProgramType or None` | PTY code (e.g. `ProgramType.ROCK`) |
| `program_id`           | `int or None`    | PI -- unique 16-bit station ID |
| `traffic_program`      | `bool`           | Station can broadcast traffic info |
| `traffic_announcement` | `bool`           | Station is currently broadcasting traffic |
| `music`                | `bool or None`   | `True` = music, `False` = speech |
| `clock_time`           | `str or None`    | CT -- `"HH:MM+/-HH:MM"` |

```python
radio.start_rds()
import time; time.sleep(30)
print(radio.rds.station_name)            # e.g. 'KEXP-FM '
print(radio.rds.radio_text)             # e.g. 'The Wipers - Romeo'
print(radio.rds.program_type.describe()) # e.g. 'Alternative'
```

---

### `ProgramType`

`IntEnum` with all 32 RBDS program type codes:
`NONE`, `NEWS`, `INFORMATION`, `SPORTS`, `TALK`, `ROCK`, `CLASSIC_ROCK`,
`ADULT_HITS`, `SOFT_ROCK`, `TOP_40`, `COUNTRY`, `OLDIES`, `SOFT`, `NOSTALGIA`,
`JAZZ`, `CLASSICAL`, `RNB`, `SOFT_RNB`, `LANGUAGE`, `RELIGIOUS_MUS`,
`RELIGIOUS_TALK`, `PERSONALITY`, `PUBLIC`, `COLLEGE`, `WEATHER`,
`EMERGENCY_TEST`, `EMERGENCY`.

---

### Band constants

| Constant       | Region          | Range           | Spacing | De-emphasis |
|----------------|-----------------|-----------------|---------|-------------|
| `BAND_US`      | USA/Australia   | 87.5 - 108 MHz  | 200 kHz | 75 us       |
| `BAND_EU`      | Europe          | 87.5 - 108 MHz  | 100 kHz | 50 us       |
| `BAND_JP_WIDE` | Japan (wide)    | 76 - 108 MHz    | 100 kHz | 50 us       |
| `BAND_JP`      | Japan           | 76 - 90 MHz     | 100 kHz | 50 us       |

---

### Exceptions

| Exception             | When raised |
|-----------------------|-------------|
| `Si4703Error`         | Base class for all library errors |
| `TuneTimeoutError`    | Seek/tune did not complete within timeout |
| `SeekFailedError`     | Seek reached band limit without finding a station |
| `NotInitializedError` | Method called before `power_on()` |

---

## Command-line interface

The `si4703` command is installed automatically with the package.

```bash
# Tune to a station
si4703 --reset-pin 17 tune 98.7 --volume 10

# Tune and collect RDS
si4703 --reset-pin 17 tune 98.7 --rds --rds-timeout 30

# Seek up / down
si4703 --reset-pin 17 seek up
si4703 --reset-pin 17 seek down --no-wrap

# Scan the whole band
si4703 --reset-pin 17 scan
si4703 --reset-pin 17 scan --min-rssi 30

# RDS monitor
si4703 --reset-pin 17 rds 98.7 --timeout 60

# European band
si4703 --reset-pin 17 --band eu tune 97.3

# With IRQ pin for faster seek/tune
si4703 --reset-pin 17 --irq-pin 27 tune 98.7

# Debug logging
si4703 --reset-pin 17 --verbose tune 98.7
```

---

## Examples

| File | Description |
|------|-------------|
| [examples/basic_usage.py](examples/basic_usage.py) | Tune, seek, scan, RDS, volume |
| [examples/interactive.py](examples/interactive.py) | Curses-based interactive UI |

---

## Development

```bash
git clone https://github.com/ryane/si4703RaspberryPi
cd si4703RaspberryPi
pip install -e ".[dev]"
pytest
```

---

## Changelog

### 2.0.0 (2026)

Complete rewrite in modern Python 3.

- **Property-based API** -- `radio.frequency = 98.7` instead of `si4703SetChannel(987)`
- **Context manager** -- `with Si4703Radio(...) as radio:`
- **Type hints** throughout -- full IDE autocomplete
- **Full RDS/RBDS decoder** -- PS, RT, PTY, PI, TP, TA, M/S, CT (group 4A)
- **Background RDS thread** with optional callback
- **Band scanner** -- `radio.scan()` returns all receivable stations
- **Multi-region** -- US, EU, Japan Wide, Japan band configurations
- **IRQ support** -- faster seek/tune completion via GPIO interrupt
- **`si4703` CLI tool** -- tune, seek, scan, rds subcommands
- **Interactive curses UI** -- example in `examples/interactive.py`
- **`smbus2`** instead of the old `smbus` system package
- **Proper exceptions** -- `TuneTimeoutError`, `SeekFailedError`, `NotInitializedError`
- **`pip install si4703`** -- proper `pyproject.toml` package

### 1.0.0 (2016)

Initial release.

---

## License

MIT -- see [LICENSE](LICENSE).

---

*Originally ported from an Arduino library by Aaron Weiss @ SparkFun.*
