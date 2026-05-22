"""Global test configuration.

Mocks RPi.GPIO and smbus2 before any si4703 module is imported so tests
can run on any platform (not just Raspberry Pi).
"""

import sys
from unittest.mock import MagicMock

# ── RPi.GPIO mock ──────────────────────────────────────────────────────────────
_GPIO = MagicMock(name="RPi.GPIO")
_GPIO.BCM    = 11
_GPIO.BOARD  = 10
_GPIO.OUT    = 0
_GPIO.IN     = 1
_GPIO.LOW    = 0
_GPIO.HIGH   = 1
_GPIO.PUD_UP = 22
_GPIO.FALLING = 32
_GPIO.wait_for_edge.return_value = 1   # non-None → edge was detected

sys.modules.setdefault("RPi", MagicMock())
sys.modules["RPi.GPIO"] = _GPIO

# ── smbus2 mock ────────────────────────────────────────────────────────────────
_smbus2 = MagicMock(name="smbus2")
# SMBus(n) returns the same mock instance every time (consistent across tests)
_smbus2.SMBus.return_value = MagicMock(name="SMBus_instance")
_smbus2.SMBus.return_value.read_i2c_block_data.return_value = [0] * 32
sys.modules["smbus2"] = _smbus2
