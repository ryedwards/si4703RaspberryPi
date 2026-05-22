#!/usr/bin/env python3
"""Interactive radio controller — a mini curses-based FM tuner.

Controls:
  ← / →       Seek down / up
  + / -       Volume up / down
  m           Toggle mute
  s           Toggle forced mono
  0-9         Type a frequency (MHz) then Enter to tune directly
  q           Quit

Run with:
  python3 examples/interactive.py --reset-pin 17
"""

import argparse
import curses
import sys
import time
from typing import Optional

from si4703 import Si4703Radio, BAND_US, BAND_EU, BAND_JP, BAND_JP_WIDE, RDSData, SeekFailedError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--reset-pin", "-r", type=int, required=True)
    p.add_argument("--irq-pin",   "-i", type=int, default=None)
    p.add_argument("--band",      "-b", choices=["us","eu","jp","jp_wide"], default="us")
    return p.parse_args()


def run_ui(stdscr: "curses._CursesWindow", radio: Si4703Radio) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.use_default_colors()

    # Colors
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN,  -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_CYAN,   -1)
    curses.init_pair(4, curses.COLOR_RED,    -1)

    freq_input: list[str] = []
    status_msg  = ""
    last_rds    = RDSData()

    def on_rds(rds: RDSData) -> None:
        nonlocal last_rds
        last_rds = rds

    radio.start_rds(callback=on_rds)

    while True:
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        # ── Header ────────────────────────────────────────────────────────────
        header = " Si4703 FM Radio "
        stdscr.addstr(0, (width - len(header)) // 2, header, curses.A_REVERSE)

        # ── Frequency ─────────────────────────────────────────────────────────
        try:
            freq = radio.frequency
            rssi = radio.rssi
            stereo = radio.is_stereo
        except Exception:
            freq = rssi = 0.0; stereo = False  # type: ignore[assignment]

        bar_len = max(0, min(rssi, 75)) * (width // 2 - 4) // 75
        rssi_bar = "█" * bar_len + "░" * ((width // 2 - 4) - bar_len)

        stdscr.addstr(2, 2, "Frequency:", curses.A_BOLD)
        stdscr.addstr(2, 13, f"{freq:.1f} MHz",
                      curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(3, 2, "Signal:  ", curses.A_BOLD)
        stdscr.addstr(3, 13, f"{rssi_bar}  {rssi} dBµV",
                      curses.color_pair(2))
        stdscr.addstr(4, 2, "Mode:    ", curses.A_BOLD)
        mode_str = "Stereo" if stereo else "Mono"
        if radio.mono:
            mode_str += " (forced mono)"
        stdscr.addstr(4, 13, mode_str, curses.color_pair(3))

        vol = radio.volume
        vol_bar = "▮" * vol + "▯" * (15 - vol)
        stdscr.addstr(5, 2, "Volume:  ", curses.A_BOLD)
        stdscr.addstr(5, 13, f"{vol_bar}  {vol}/15")

        # ── RDS ───────────────────────────────────────────────────────────────
        stdscr.addstr(7, 2, "─" * (width - 4), curses.color_pair(3))
        if last_rds.station_name:
            stdscr.addstr(8, 2, f"Station : {last_rds.station_name.strip()!r}",
                          curses.color_pair(1))
        if last_rds.program_type:
            stdscr.addstr(9, 2, f"Type    : {last_rds.program_type.describe()}")
        if last_rds.radio_text:
            rt = last_rds.radio_text[:width - 14]
            stdscr.addstr(10, 2, f"RT      : {rt!r}")
        if last_rds.traffic_announcement:
            stdscr.addstr(11, 2, "⚠  TRAFFIC ANNOUNCEMENT", curses.color_pair(4) | curses.A_BOLD)
        if last_rds.clock_time:
            stdscr.addstr(12, 2, f"Clock   : {last_rds.clock_time}")

        # ── Status / freq input ───────────────────────────────────────────────
        stdscr.addstr(height - 3, 2, "─" * (width - 4), curses.color_pair(3))
        if freq_input:
            stdscr.addstr(height - 2, 2, f"Tune to: {''.join(freq_input)} MHz_")
        elif status_msg:
            stdscr.addstr(height - 2, 2, status_msg)

        # ── Help bar ──────────────────────────────────────────────────────────
        help_str = " ←/→ seek   +/- vol   m mute   s mono   digits+Enter tune   q quit "
        try:
            stdscr.addstr(height - 1, 0, help_str[:width].ljust(width), curses.A_REVERSE)
        except curses.error:
            # Writing to the last cell can raise an error; it's safe to ignore
            pass

        stdscr.refresh()

        # ── Input handling ────────────────────────────────────────────────────
        try:
            key = stdscr.getch()
        except Exception:
            key = -1

        if key == ord("q"):
            break

        elif key == curses.KEY_RIGHT:
            status_msg = "Seeking up…"
            stdscr.refresh()
            try:
                radio.seek_up()
                last_rds = RDSData()
                status_msg = ""
            except SeekFailedError:
                status_msg = "Seek failed — band limit reached"

        elif key == curses.KEY_LEFT:
            status_msg = "Seeking down…"
            stdscr.refresh()
            try:
                radio.seek_down()
                last_rds = RDSData()
                status_msg = ""
            except SeekFailedError:
                status_msg = "Seek failed — band limit reached"

        elif key == ord("+"):
            radio.volume_up()

        elif key == ord("-"):
            radio.volume_down()

        elif key == ord("m"):
            radio.muted = not radio.muted
            status_msg = "Muted" if radio.muted else "Unmuted"

        elif key == ord("s"):
            radio.mono = not radio.mono
            status_msg = "Mono forced" if radio.mono else "Stereo enabled"

        elif chr(key) in "0123456789." if 0 <= key < 256 else False:
            freq_input.append(chr(key))

        elif key in (10, 13, curses.KEY_ENTER) and freq_input:
            try:
                target = float("".join(freq_input))
                radio.frequency = target
                last_rds = RDSData()
                status_msg = ""
            except (ValueError, Exception) as exc:
                status_msg = f"Error: {exc}"
            freq_input.clear()

        elif key == 27:  # Escape
            freq_input.clear()
            status_msg = ""

        time.sleep(0.05)

    radio.stop_rds()


def main() -> None:
    args = parse_args()
    band_map = {"us": BAND_US, "eu": BAND_EU, "jp": BAND_JP, "jp_wide": BAND_JP_WIDE}

    with Si4703Radio(
        reset_pin=args.reset_pin,
        irq_pin=args.irq_pin,
        band=band_map[args.band],
    ) as radio:
        radio.volume = 8
        curses.wrapper(run_ui, radio)


if __name__ == "__main__":
    main()
