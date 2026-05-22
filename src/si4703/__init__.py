"""si4703 — Silicon Labs Si4702/Si4703 FM Radio Receiver driver for Raspberry Pi.

Quick start::

    from si4703 import Si4703Radio, BAND_US

    with Si4703Radio(reset_pin=17) as radio:
        radio.frequency = 98.7   # tune to 98.7 MHz
        radio.volume    = 10     # 0 – 15

        print(f"{radio.frequency:.1f} MHz")
        print(f"RSSI  : {radio.rssi} dBµV")
        print(f"Stereo: {radio.is_stereo}")

        # Background RDS collection
        radio.start_rds(callback=lambda d: print(d))
        import time; time.sleep(30)
        radio.stop_rds()
        print(radio.rds)
"""

from .radio import (
    BAND_EU,
    BAND_JP,
    BAND_JP_WIDE,
    BAND_US,
    Band,
    Si4703Radio,
)
from .rds import ProgramType, RDSData
from .exceptions import NotInitializedError, SeekFailedError, Si4703Error, TuneTimeoutError

__version__ = "2.0.0"
__author__  = "Ryan Edwards <ryan.edwards@gmail.com>"

__all__ = [
    # Main class
    "Si4703Radio",
    # Band configurations
    "Band",
    "BAND_US",
    "BAND_EU",
    "BAND_JP",
    "BAND_JP_WIDE",
    # RDS
    "RDSData",
    "ProgramType",
    # Exceptions
    "Si4703Error",
    "TuneTimeoutError",
    "SeekFailedError",
    "NotInitializedError",
]
