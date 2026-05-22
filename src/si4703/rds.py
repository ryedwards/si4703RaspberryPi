"""RDS/RBDS decoder for the Si4703.

Decodes the following RDS groups:
- 0A/0B  Program Service name (PS)  — 8-char station name
- 2A/2B  RadioText (RT)             — up to 64-char scrolling text
- 4A     Clock Time (CT)            — date + time with UTC offset
- 0A/0B  Traffic Program / Traffic Announcement flags
- All    Program Type (PTY)         — news, rock, jazz, …
- All    Program Identification (PI)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Program Type codes (RBDS — North America)
# ──────────────────────────────────────────────────────────────────────────────

class ProgramType(IntEnum):
    """RBDS Program Type codes (North America).  European RDS uses different names."""
    NONE           = 0
    NEWS           = 1
    INFORMATION    = 2
    SPORTS         = 3
    TALK           = 4
    ROCK           = 5
    CLASSIC_ROCK   = 6
    ADULT_HITS     = 7
    SOFT_ROCK      = 8
    TOP_40         = 9
    COUNTRY        = 10
    OLDIES         = 11
    SOFT           = 12
    NOSTALGIA      = 13
    JAZZ           = 14
    CLASSICAL      = 15
    RNB            = 16
    SOFT_RNB       = 17
    LANGUAGE       = 18
    RELIGIOUS_MUS  = 19
    RELIGIOUS_TALK = 20
    PERSONALITY    = 21
    PUBLIC         = 22
    COLLEGE        = 23
    # 24–28 unassigned
    WEATHER        = 29
    EMERGENCY_TEST = 30
    EMERGENCY      = 31

    @classmethod
    def _missing_(cls, value: object) -> "ProgramType":
        return cls.NONE

    def describe(self) -> str:
        """Human-readable description."""
        return self.name.replace("_", " ").title()


# ──────────────────────────────────────────────────────────────────────────────
# Public data container
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RDSData:
    """Snapshot of all decoded RDS data for the currently tuned station."""

    #: 16-bit Program Identification code (unique station ID).
    program_id: Optional[int] = None

    #: Program Type — what kind of content is playing.
    program_type: Optional[ProgramType] = None

    #: Program Service name — the 8-character station name shown on receivers.
    station_name: Optional[str] = None

    #: RadioText — the longer scrolling text broadcast by the station.
    radio_text: Optional[str] = None

    #: Traffic Program flag — station can broadcast traffic info.
    traffic_program: bool = False

    #: Traffic Announcement flag — station is currently broadcasting traffic.
    traffic_announcement: bool = False

    #: Music/Speech flag. ``True`` = music, ``False`` = speech, ``None`` = unknown.
    music: Optional[bool] = None

    #: Clock Time decoded from RDS group 4A, formatted as ``"HH:MM±HH:MM"``.
    clock_time: Optional[str] = None

    def __str__(self) -> str:
        parts: list[str] = []
        if self.station_name:
            parts.append(f"[{self.station_name.strip()}]")
        if self.program_type is not None and self.program_type != ProgramType.NONE:
            parts.append(self.program_type.describe())
        if self.radio_text:
            parts.append(f'"{self.radio_text.strip()}"')
        if self.traffic_announcement:
            parts.append("⚠ Traffic")
        if self.clock_time:
            parts.append(f"🕒 {self.clock_time}")
        return "  ".join(parts) if parts else "<no RDS data yet>"

    def is_complete(self) -> bool:
        """Return ``True`` once both station name and radio text have been received."""
        return self.station_name is not None and self.radio_text is not None


# ──────────────────────────────────────────────────────────────────────────────
# Stateful decoder
# ──────────────────────────────────────────────────────────────────────────────

class RDSDecoder:
    """Stateful decoder that accumulates RDS groups into an :class:`RDSData` object.

    Call :meth:`process` once per RDS group.  The returned bool indicates whether
    any field changed so callers can decide whether to fire a callback.
    """

    def __init__(self) -> None:
        self._data = RDSData()
        self._ps_buf: list[Optional[str]] = [None] * 8   # 8 char PS name
        self._rt_buf: list[Optional[str]] = [None] * 64  # 64 char RT
        self._rt_ab: Optional[int] = None                # RT A/B toggle flag

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def data(self) -> RDSData:
        """Current accumulated :class:`RDSData` snapshot (not a copy — read-only)."""
        return self._data

    def clear(self) -> None:
        """Reset all buffers and data — call this after tuning to a new station."""
        self._data = RDSData()
        self._ps_buf = [None] * 8
        self._rt_buf = [None] * 64
        self._rt_ab = None

    def process(self, rdsa: int, rdsb: int, rdsc: int, rdsd: int) -> bool:
        """Decode one four-word RDS group.

        Args:
            rdsa: Register 0x0C — PI code.
            rdsb: Register 0x0D — group type, version, TP, PTY, segment info.
            rdsc: Register 0x0E — group-specific payload.
            rdsd: Register 0x0F — group-specific payload.

        Returns:
            ``True`` if any :class:`RDSData` field changed.
        """
        changed = False

        # ── PI code (always in RDSA) ──────────────────────────────────────────
        if self._data.program_id != rdsa:
            self._data.program_id = rdsa
            changed = True

        # ── Decode RDSB header ────────────────────────────────────────────────
        group_type: int = (rdsb >> 12) & 0x0F   # bits [15:12]
        version_b:  bool = bool((rdsb >> 11) & 1)  # 0=A, 1=B
        tp:         bool = bool((rdsb >> 10) & 1)  # Traffic Program
        pty_raw:    int  = (rdsb >> 5) & 0x1F      # Program Type

        if self._data.traffic_program != tp:
            self._data.traffic_program = tp
            changed = True

        pty = ProgramType(pty_raw)
        if self._data.program_type != pty:
            self._data.program_type = pty
            changed = True

        # ── Dispatch to group handler ─────────────────────────────────────────
        if group_type == 0:
            changed |= self._group_0(rdsb, rdsc, rdsd, version_b)
        elif group_type == 2:
            changed |= self._group_2(rdsb, rdsc, rdsd, version_b)
        elif group_type == 4 and not version_b:
            changed |= self._group_4a(rdsc, rdsd)
        # groups 1, 3, 5–15 silently ignored for now

        return changed

    # ── Group handlers ────────────────────────────────────────────────────────

    def _group_0(self, rdsb: int, rdsc: int, rdsd: int, version_b: bool) -> bool:
        """Group 0A/0B — Program Service name + TA/MS flags."""
        changed = False
        ta   = bool((rdsb >> 4) & 1)   # Traffic Announcement
        ms   = bool((rdsb >> 3) & 1)   # Music/Speech (True = music)
        seg  = rdsb & 0x03             # segment address 0–3

        if self._data.traffic_announcement != ta:
            self._data.traffic_announcement = ta
            changed = True
        if self._data.music != ms:
            self._data.music = ms
            changed = True

        # RDSD carries the two characters for this segment of the 8-char PS name
        hi = chr((rdsd >> 8) & 0xFF)
        lo = chr(rdsd & 0xFF)
        for i, ch in enumerate((hi, lo)):
            slot = seg * 2 + i
            if self._ps_buf[slot] != ch:
                self._ps_buf[slot] = ch
                changed = True

        # Assemble full name once all 4 segments have been received
        if None not in self._ps_buf:
            name = "".join(c for c in self._ps_buf if c)  # type: ignore[arg-type]
            if self._data.station_name != name:
                self._data.station_name = name
                changed = True

        return changed

    def _group_2(self, rdsb: int, rdsc: int, rdsd: int, version_b: bool) -> bool:
        """Group 2A/2B — RadioText."""
        changed = False
        ab  = (rdsb >> 4) & 1   # A/B flag — flip means new message
        seg = rdsb & 0x0F        # segment 0–15

        # A/B flag flip → new RT message inbound, reset buffer
        if self._rt_ab is not None and self._rt_ab != ab:
            self._rt_buf = [None] * 64
            changed = True
        self._rt_ab = ab

        if not version_b:
            # Group 2A: 4 chars per segment from RDSC + RDSD
            chars = (
                chr((rdsc >> 8) & 0xFF),
                chr(rdsc & 0xFF),
                chr((rdsd >> 8) & 0xFF),
                chr(rdsd & 0xFF),
            )
            for i, ch in enumerate(chars):
                pos = seg * 4 + i
                if pos < 64 and self._rt_buf[pos] != ch:
                    self._rt_buf[pos] = ch
                    changed = True
        else:
            # Group 2B: 2 chars per segment from RDSD only
            chars_2b = (
                chr((rdsd >> 8) & 0xFF),
                chr(rdsd & 0xFF),
            )
            for i, ch in enumerate(chars_2b):
                pos = seg * 2 + i
                if pos < 32 and self._rt_buf[pos] != ch:
                    self._rt_buf[pos] = ch
                    changed = True

        # Build RT string; 0x0D (carriage return) is the official end-of-text marker
        rt_chars: list[str] = []
        for ch in self._rt_buf:
            if ch is None:
                break
            if ch == "\r":
                break
            rt_chars.append(ch)
        rt = "".join(rt_chars)

        if self._data.radio_text != rt:
            self._data.radio_text = rt
            changed = True

        return changed

    def _group_4a(self, rdsc: int, rdsd: int) -> bool:
        """Group 4A — Clock Time and Date.

        Encodes Modified Julian Day (MJD), local time, and UTC offset.
        We decode the time portion only for simplicity.
        """
        hours   = rdsc & 0x001F
        minutes = (rdsd >> 10) & 0x3F
        sign    = "-" if (rdsd >> 5) & 1 else "+"
        offset  = (rdsd & 0x001F) * 30  # offset in minutes
        off_h, off_m = divmod(offset, 60)

        ct = f"{hours:02d}:{minutes:02d}{sign}{off_h:02d}:{off_m:02d}"
        if self._data.clock_time != ct:
            self._data.clock_time = ct
            return True
        return False
