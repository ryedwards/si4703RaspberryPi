#!/usr/bin/env python3
"""Basic Si4703 usage example.

Hardware setup (SparkFun Si4703 Breakout, Raspberry Pi):
  Si4703 SDA  → RPi GPIO 2  (I²C SDA)
  Si4703 SCL  → RPi GPIO 3  (I²C SCL)
  Si4703 RST  → RPi GPIO 17 (configurable via reset_pin)
  Si4703 GPIO2→ RPi GPIO 27 (optional IRQ; faster seek/tune)
  Si4703 3.3V → RPi 3.3 V
  Si4703 GND  → RPi GND

Confirm the I²C address with:
  sudo i2cdetect -y 1
(should show 0x10)
"""

import time
from si4703 import Si4703Radio, BAND_US, SeekFailedError

RESET_PIN = 17   # change to your wiring
IRQ_PIN   = 27   # set to None if not wired
VOLUME    = 10


def main() -> None:
    with Si4703Radio(reset_pin=RESET_PIN, irq_pin=IRQ_PIN, band=BAND_US) as radio:
        # ── Tune ──────────────────────────────────────────────────────────────
        radio.volume    = VOLUME
        radio.frequency = 98.7
        print(f"Tuned to {radio.frequency:.1f} MHz")
        print(f"Signal : {radio.rssi} dBµV  ({'Stereo' if radio.is_stereo else 'Mono'})")

        # ── RDS ───────────────────────────────────────────────────────────────
        print("\nCollecting RDS data for 20 seconds…")

        def on_rds(rds):
            print(f"  RDS: {rds}")

        radio.start_rds(callback=on_rds)
        time.sleep(20)
        radio.stop_rds()

        print(f"\nFinal RDS snapshot: {radio.rds}")

        # ── Seek ──────────────────────────────────────────────────────────────
        print("\nSeeking up…")
        try:
            freq = radio.seek_up()
            print(f"Landed on {freq:.1f} MHz  (RSSI={radio.rssi} dBµV)")
        except SeekFailedError as exc:
            print(f"Seek failed: {exc}")

        # ── Scan ──────────────────────────────────────────────────────────────
        print("\nScanning full band…  (takes ~30–60 s)")
        stations = radio.scan()
        print(f"\n  {'Freq':>8}   RSSI")
        print("  " + "-" * 20)
        for freq, rssi in stations:
            print(f"  {freq:>6.1f} MHz   {rssi:>3} dBµV")
        print(f"\n{len(stations)} station(s) found.")

        # ── Volume demo ───────────────────────────────────────────────────────
        radio.frequency = 98.7
        print("\nVolume sweep:")
        for vol in range(0, 16, 5):
            radio.volume = vol
            print(f"  Volume = {radio.volume}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
