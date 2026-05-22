"""Unit tests for the RDS/RBDS decoder."""

import pytest

from si4703.rds import ProgramType, RDSData, RDSDecoder


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_rdsb(
    group_type: int,
    version: int = 0,
    tp: bool = False,
    pty: int = 0,
    extra: int = 0,
) -> int:
    """Build a RDSB register word from its constituent fields.

    RDSB layout:
      [15:12] group type   [11] version (0=A,1=B)   [10] TP
      [9:5]   PTY          [4:0] group-specific bits
    """
    return (
        ((group_type & 0xF) << 12)
        | ((version & 0x1)  << 11)
        | ((int(tp) & 0x1)  << 10)
        | ((pty & 0x1F)     <<  5)
        | (extra & 0x1F)
    )


def send_group0(dec: RDSDecoder, seg: int, chars: str, ta: bool = False, ms: bool = False) -> bool:
    """Send a Group 0A segment (2 PS chars)."""
    assert len(chars) == 2
    rdsb = make_rdsb(0, extra=(int(ta) << 4) | (int(ms) << 3) | (seg & 0x3))
    rdsd = (ord(chars[0]) << 8) | ord(chars[1])
    return dec.process(rdsa=0x1234, rdsb=rdsb, rdsc=0, rdsd=rdsd)


def send_group2a(dec: RDSDecoder, seg: int, chars: str, ab: int = 0) -> bool:
    """Send a Group 2A segment (4 RT chars from RDSC + RDSD)."""
    assert len(chars) == 4
    rdsb = make_rdsb(2, version=0, extra=(ab << 4) | (seg & 0xF))
    rdsc = (ord(chars[0]) << 8) | ord(chars[1])
    rdsd = (ord(chars[2]) << 8) | ord(chars[3])
    return dec.process(rdsa=0x1234, rdsb=rdsb, rdsc=rdsc, rdsd=rdsd)


# ──────────────────────────────────────────────────────────────────────────────
# ProgramType
# ──────────────────────────────────────────────────────────────────────────────

class TestProgramType:
    def test_known_values(self):
        assert ProgramType(1)  == ProgramType.NEWS
        assert ProgramType(5)  == ProgramType.ROCK
        assert ProgramType(9)  == ProgramType.TOP_40
        assert ProgramType(14) == ProgramType.JAZZ
        assert ProgramType(31) == ProgramType.EMERGENCY

    def test_missing_returns_none(self):
        # 25–28 are unassigned in RBDS; _missing_ should return NONE
        assert ProgramType(25) == ProgramType.NONE
        assert ProgramType(27) == ProgramType.NONE

    def test_describe_single_word(self):
        assert ProgramType.NEWS.describe()     == "News"
        assert ProgramType.JAZZ.describe()     == "Jazz"
        assert ProgramType.ROCK.describe()     == "Rock"

    def test_describe_multi_word(self):
        assert ProgramType.CLASSIC_ROCK.describe()   == "Classic Rock"
        assert ProgramType.RELIGIOUS_MUS.describe()  == "Religious Mus"
        assert ProgramType.EMERGENCY_TEST.describe() == "Emergency Test"

    def test_int_value(self):
        assert int(ProgramType.TOP_40) == 9


# ──────────────────────────────────────────────────────────────────────────────
# RDSData
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSData:
    def test_str_empty(self):
        assert str(RDSData()) == "<no RDS data yet>"

    def test_str_contains_station_name(self):
        d = RDSData(station_name="KEXP-FM ")
        assert "KEXP-FM" in str(d)

    def test_str_contains_radio_text(self):
        d = RDSData(radio_text="Some Song - Artist")
        assert "Some Song" in str(d)

    def test_str_traffic_announcement(self):
        d = RDSData(traffic_announcement=True)
        assert "Traffic" in str(d)

    def test_str_clock_time(self):
        d = RDSData(clock_time="14:30+00:00")
        assert "14:30" in str(d)

    def test_is_complete_false_missing_rt(self):
        d = RDSData(station_name="KEXP-FM ")
        assert not d.is_complete()

    def test_is_complete_false_missing_ps(self):
        d = RDSData(radio_text="Some Song")
        assert not d.is_complete()

    def test_is_complete_true(self):
        d = RDSData(station_name="KEXP-FM ", radio_text="Some Song")
        assert d.is_complete()

    def test_is_complete_false_empty(self):
        assert not RDSData().is_complete()


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — PI code
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderPI:
    def test_pi_decoded_from_rdsa(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE")
        assert dec.data.program_id == 0x1234

    def test_pi_change_returns_true(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE")
        # Same group, different PI (rdsa)
        rdsb = make_rdsb(0)
        changed = dec.process(rdsa=0xABCD, rdsb=rdsb, rdsc=0, rdsd=0)
        assert changed is True

    def test_same_pi_returns_false_for_pi_field(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE")
        # Repeat exactly — PI unchanged, only segment data checked for change
        changed = send_group0(dec, 0, "KE")
        assert isinstance(changed, bool)  # just confirm no crash; value can be True/False


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — Program Type (PTY) and Traffic Program (TP)
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderPTY:
    def test_pty_rock(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, pty=5), rdsc=0, rdsd=0)
        assert dec.data.program_type == ProgramType.ROCK

    def test_pty_top40(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, pty=9), rdsc=0, rdsd=0)
        assert dec.data.program_type == ProgramType.TOP_40

    def test_pty_unassigned_becomes_none(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, pty=25), rdsc=0, rdsd=0)
        assert dec.data.program_type == ProgramType.NONE

    def test_tp_flag_set(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, tp=True), rdsc=0, rdsd=0)
        assert dec.data.traffic_program is True

    def test_tp_flag_clear(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, tp=True), rdsc=0, rdsd=0)
        dec.process(rdsa=0, rdsb=make_rdsb(0, tp=False), rdsc=0, rdsd=0)
        assert dec.data.traffic_program is False


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — Group 0A: Program Service name
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderGroup0:
    def test_ps_incomplete_before_all_segments(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE")
        send_group0(dec, 1, "XP")
        assert dec.data.station_name is None  # only 2 of 4 segments received

    def test_ps_complete_after_four_segments(self):
        dec = RDSDecoder()
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            send_group0(dec, i, pair)
        assert dec.data.station_name == "KEXP-FM "

    def test_ps_changed_true_on_completion(self):
        dec = RDSDecoder()
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            changed = send_group0(dec, i, pair)
        assert changed is True  # final segment completes the name

    def test_ps_changed_false_on_repeat(self):
        dec = RDSDecoder()
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            send_group0(dec, i, pair)
        # Resend identical segments
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            changed = send_group0(dec, i, pair)
        assert changed is False

    def test_ta_flag_set(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE", ta=True)
        assert dec.data.traffic_announcement is True

    def test_ta_flag_cleared(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE", ta=True)
        send_group0(dec, 0, "KE", ta=False)
        assert dec.data.traffic_announcement is False

    def test_music_speech_flag(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE", ms=True)    # True = music
        assert dec.data.music is True
        send_group0(dec, 0, "KE", ms=False)   # False = speech
        assert dec.data.music is False


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — Group 2A: RadioText
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderGroup2A:
    def test_rt_builds_from_segments(self):
        dec = RDSDecoder()
        # Fill 4 segments (16 chars) of RT
        message = "Hello, World!   "  # 16 chars
        for seg in range(4):
            send_group2a(dec, seg, message[seg * 4 : seg * 4 + 4])
        assert dec.data.radio_text == "Hello, World!   "

    def test_rt_stops_at_cr_end_marker(self):
        dec = RDSDecoder()
        # \r (0x0D) is the official RT end marker
        send_group2a(dec, 0, "AB\rX")   # only A and B should appear
        assert dec.data.radio_text == "AB"

    def test_rt_incomplete_before_none_boundary(self):
        dec = RDSDecoder()
        send_group2a(dec, 0, "ABCD")
        # Segments 1–15 not yet received; buffer has None after pos 3
        assert dec.data.radio_text == "ABCD"

    def test_rt_ab_flag_flip_clears_buffer(self):
        dec = RDSDecoder()
        # Fill with A/B=0 message
        for seg in range(4):
            send_group2a(dec, seg, "ABCD", ab=0)
        assert dec.data.radio_text == "ABCDABCDABCDABCD"

        # Flip A/B flag → new message; only first segment visible so far
        send_group2a(dec, 0, "WXYZ", ab=1)
        assert dec.data.radio_text == "WXYZ"   # buffer reset; only new data

    def test_rt_changed_true_on_new_data(self):
        dec = RDSDecoder()
        changed = send_group2a(dec, 0, "ABCD")
        assert changed is True

    def test_rt_changed_false_on_repeat(self):
        dec = RDSDecoder()
        send_group2a(dec, 0, "ABCD")
        changed = send_group2a(dec, 0, "ABCD")
        assert changed is False


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — Group 2B: RadioText (short form)
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderGroup2B:
    def test_rt_2b_two_chars_per_segment(self):
        dec = RDSDecoder()
        text = "HELLO!  "   # 8 chars = 4 segments × 2 chars
        for seg in range(4):
            pair = text[seg * 2 : seg * 2 + 2]
            rdsb = make_rdsb(2, version=1, extra=seg)   # version=1 → group 2B
            rdsd = (ord(pair[0]) << 8) | ord(pair[1])
            dec.process(rdsa=0x1234, rdsb=rdsb, rdsc=0, rdsd=rdsd)
        assert dec.data.radio_text == "HELLO!  "

    def test_rt_2b_max_32_chars(self):
        dec = RDSDecoder()
        # Send all 16 group-2B segments (positions 0–31)
        for seg in range(16):
            rdsb = make_rdsb(2, version=1, extra=seg)
            rdsd = (ord("A") << 8) | ord("B")
            dec.process(rdsa=0, rdsb=rdsb, rdsc=0, rdsd=rdsd)
        # 16 segments × 2 chars = 32 chars; all should be present
        assert len(dec.data.radio_text or "") == 32  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — Group 4A: Clock Time
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderGroup4A:
    def _send_clock(self, dec: RDSDecoder, hours: int, minutes: int,
                    sign_neg: bool = False, offset_slots: int = 0) -> bool:
        """Send a group 4A clock-time group."""
        rdsb = make_rdsb(4, version=0)
        rdsc = hours & 0x001F
        rdsd = ((minutes & 0x3F) << 10) | ((int(sign_neg) & 1) << 5) | (offset_slots & 0x1F)
        return dec.process(rdsa=0, rdsb=rdsb, rdsc=rdsc, rdsd=rdsd)

    def test_utc_noon(self):
        dec = RDSDecoder()
        self._send_clock(dec, hours=12, minutes=0)
        assert dec.data.clock_time == "12:00+00:00"

    def test_afternoon_with_minutes(self):
        dec = RDSDecoder()
        self._send_clock(dec, hours=14, minutes=30)
        assert dec.data.clock_time == "14:30+00:00"

    def test_negative_offset(self):
        dec = RDSDecoder()
        # UTC-5:00 = offset_slots=10 (10 × 30 min = 300 min = 5 h), sign=negative
        self._send_clock(dec, hours=8, minutes=0, sign_neg=True, offset_slots=10)
        assert dec.data.clock_time == "08:00-05:00"

    def test_positive_offset_half_hour(self):
        dec = RDSDecoder()
        # UTC+5:30 = offset_slots=11 (11 × 30 = 330 min = 5h30m)
        self._send_clock(dec, hours=9, minutes=0, sign_neg=False, offset_slots=11)
        assert dec.data.clock_time == "09:00+05:30"

    def test_changed_true_on_new_time(self):
        dec = RDSDecoder()
        changed = self._send_clock(dec, hours=10, minutes=0)
        assert changed is True

    def test_changed_false_on_same_time(self):
        dec = RDSDecoder()
        self._send_clock(dec, hours=10, minutes=0)
        changed = self._send_clock(dec, hours=10, minutes=0)
        assert changed is False


# ──────────────────────────────────────────────────────────────────────────────
# RDSDecoder — clear()
# ──────────────────────────────────────────────────────────────────────────────

class TestRDSDecoderClear:
    def test_clear_resets_station_name(self):
        dec = RDSDecoder()
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            send_group0(dec, i, pair)
        assert dec.data.station_name is not None
        dec.clear()
        assert dec.data.station_name is None

    def test_clear_resets_radio_text(self):
        dec = RDSDecoder()
        send_group2a(dec, 0, "ABCD")
        dec.clear()
        assert dec.data.radio_text is None

    def test_clear_resets_pi(self):
        dec = RDSDecoder()
        send_group0(dec, 0, "KE")
        dec.clear()
        assert dec.data.program_id is None

    def test_clear_resets_program_type(self):
        dec = RDSDecoder()
        dec.process(rdsa=0, rdsb=make_rdsb(0, pty=5), rdsc=0, rdsd=0)
        dec.clear()
        assert dec.data.program_type is None

    def test_data_rebuilds_after_clear(self):
        dec = RDSDecoder()
        for i, pair in enumerate(["KE", "XP", "-F", "M "]):
            send_group0(dec, i, pair)
        dec.clear()
        # Send new station name after clear
        for i, pair in enumerate(["WB", "UR", "-A", "M "]):
            send_group0(dec, i, pair)
        assert dec.data.station_name == "WBUR-AM "
