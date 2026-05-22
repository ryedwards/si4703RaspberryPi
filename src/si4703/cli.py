"""Command-line interface for the si4703 library.

Usage examples
--------------

Tune to a station::

    si4703 --reset-pin 17 tune 98.7 --volume 10

Seek up from the current frequency::

    si4703 --reset-pin 17 seek up

Scan the full band::

    si4703 --reset-pin 17 scan

Collect and display RDS data::

    si4703 --reset-pin 17 rds 98.7 --timeout 60

Use European band settings::

    si4703 --reset-pin 17 --band eu tune 97.3
"""

from __future__ import annotations

import argparse
import logging
import sys
import time


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="si4703",
        description="Control a Silicon Labs Si4703 FM radio receiver from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--reset-pin", "-r",
        type=int,
        required=True,
        metavar="BCM_PIN",
        help="BCM GPIO pin number connected to the Si4703 /RST pin.",
    )
    parser.add_argument(
        "--irq-pin", "-i",
        type=int,
        default=None,
        metavar="BCM_PIN",
        help="Optional BCM GPIO interrupt pin (GPIO2 on the Si4703).  "
             "Enables faster seek/tune completion vs. polling.",
    )
    parser.add_argument(
        "--i2c-address", "-a",
        type=lambda x: int(x, 0),
        default=0x10,
        metavar="ADDR",
        help="I²C address of the Si4703 (default: 0x10).  "
             "Confirm with: sudo i2cdetect -y 1",
    )
    parser.add_argument(
        "--i2c-bus",
        type=int,
        default=1,
        metavar="BUS",
        help="I²C bus number (default: 1).",
    )
    parser.add_argument(
        "--band", "-b",
        choices=["us", "eu", "jp", "jp_wide"],
        default="us",
        help=(
            "Regional FM band: us=87.5–108 MHz/200 kHz (default), "
            "eu=87.5–108 MHz/100 kHz, jp=76–90 MHz, jp_wide=76–108 MHz."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── tune ──────────────────────────────────────────────────────────────────
    p_tune = sub.add_parser("tune", help="Tune to a specific frequency.")
    p_tune.add_argument(
        "frequency",
        type=float,
        metavar="FREQ_MHZ",
        help="Frequency in MHz, e.g. 98.7",
    )
    p_tune.add_argument("--volume", type=int, default=8, metavar="0-15")
    p_tune.add_argument(
        "--rds",
        action="store_true",
        help="Also wait for and display RDS data.",
    )
    p_tune.add_argument(
        "--rds-timeout",
        type=float,
        default=20.0,
        metavar="SECONDS",
        help="How long to gather RDS data (default: 20 s).",
    )

    # ── seek ──────────────────────────────────────────────────────────────────
    p_seek = sub.add_parser("seek", help="Seek to the next valid station.")
    p_seek.add_argument(
        "direction",
        choices=["up", "down"],
        nargs="?",
        default="up",
        help="Seek direction (default: up).",
    )
    p_seek.add_argument("--volume", type=int, default=8, metavar="0-15")
    p_seek.add_argument(
        "--no-wrap",
        action="store_true",
        help="Stop at band limit instead of wrapping around.",
    )

    # ── scan ──────────────────────────────────────────────────────────────────
    p_scan = sub.add_parser("scan", help="Scan the entire band for receivable stations.")
    p_scan.add_argument(
        "--min-rssi",
        type=int,
        default=20,
        metavar="DBUV",
        help="Minimum signal strength to include (default: 20 dBµV).",
    )

    # ── rds ───────────────────────────────────────────────────────────────────
    p_rds = sub.add_parser("rds", help="Tune to a station and stream RDS data.")
    p_rds.add_argument(
        "frequency",
        type=float,
        metavar="FREQ_MHZ",
        help="Frequency in MHz.",
    )
    p_rds.add_argument("--volume", type=int, default=8, metavar="0-15")
    p_rds.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="How long to listen (default: 30 s, 0 = forever).",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Import lazily so that missing RPi.GPIO gives a clean error message
    from .radio import BAND_EU, BAND_JP, BAND_JP_WIDE, BAND_US, Si4703Radio
    from .exceptions import SeekFailedError

    band_map = {"us": BAND_US, "eu": BAND_EU, "jp": BAND_JP, "jp_wide": BAND_JP_WIDE}

    try:
        with Si4703Radio(
            reset_pin=args.reset_pin,
            i2c_address=args.i2c_address,
            i2c_bus=args.i2c_bus,
            irq_pin=args.irq_pin,
            band=band_map[args.band],
        ) as radio:
            _dispatch(args, radio)

    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        if args.verbose:
            raise
        sys.exit(1)


def _dispatch(args: argparse.Namespace, radio: object) -> None:
    from .radio import Si4703Radio
    from .exceptions import SeekFailedError
    assert isinstance(radio, Si4703Radio)

    if args.command == "tune":
        radio.volume = args.volume
        radio.frequency = args.frequency
        _print_status(radio)

        if args.rds:
            _collect_rds(radio, args.rds_timeout)

    elif args.command == "seek":
        radio.volume = args.volume
        try:
            freq = radio.seek(up=(args.direction == "up"), wrap=not args.no_wrap)
            print(f"Landed on {freq:.1f} MHz")
            _print_status(radio)
        except SeekFailedError as exc:
            print(f"Seek failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "scan":
        print(f"Scanning {radio._band.name} band…  (this takes ~30–60 seconds)")
        stations = radio.scan(min_rssi=args.min_rssi)
        if not stations:
            print("No stations found.")
            return
        print(f"\n  {'Freq (MHz)':>10}   {'RSSI (dBµV)':>11}")
        print("  " + "-" * 26)
        for freq, rssi in stations:
            bar = "█" * (rssi // 5)
            print(f"  {freq:>10.1f}   {rssi:>7}  {bar}")
        print(f"\n  {len(stations)} station(s) found.")

    elif args.command == "rds":
        radio.volume = args.volume
        radio.frequency = args.frequency
        _print_status(radio)
        _collect_rds(radio, args.timeout)


def _print_status(radio: object) -> None:
    from .radio import Si4703Radio
    assert isinstance(radio, Si4703Radio)
    stereo = "Stereo" if radio.is_stereo else "Mono"
    print(
        f"Tuned:  {radio.frequency:.1f} MHz   "
        f"RSSI: {radio.rssi} dBµV   "
        f"{stereo}   "
        f"Vol: {radio.volume}"
    )


def _collect_rds(radio: object, timeout: float) -> None:
    from .radio import Si4703Radio
    assert isinstance(radio, Si4703Radio)

    last_str = ""

    def on_update(rds_data: object) -> None:
        nonlocal last_str
        s = str(rds_data)
        if s != last_str:
            last_str = s
            print(f"\rRDS: {s:<78}", end="", flush=True)

    radio.start_rds(callback=on_update)

    print(f"Listening for RDS…  ", end="", flush=True)
    if timeout > 0:
        print(f"(timeout {timeout:.0f}s, Ctrl+C to stop early)")
    else:
        print("(Ctrl+C to stop)")

    try:
        if timeout > 0:
            time.sleep(timeout)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        radio.stop_rds()
        print(f"\n\nFinal RDS snapshot:\n  {radio.rds}\n")
