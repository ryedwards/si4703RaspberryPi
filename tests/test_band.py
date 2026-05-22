"""Unit tests for Band dataclass and the four pre-defined band constants."""

import pytest

from si4703 import BAND_EU, BAND_JP, BAND_JP_WIDE, BAND_US


class TestBandUS:
    """87.5–108 MHz, 200 kHz spacing, 75 µs de-emphasis."""

    def test_bottom_freq(self):
        assert BAND_US.freq_to_channel(87.5) == 0

    def test_known_channel(self):
        # 98.7 MHz: (98.7 - 87.5) / 0.2 = 56.0
        assert BAND_US.freq_to_channel(98.7) == 56

    def test_another_known_channel(self):
        # 91.5 MHz: (91.5 - 87.5) / 0.2 = 20.0
        assert BAND_US.freq_to_channel(91.5) == 20

    def test_channel_to_freq_roundtrip(self):
        for freq in (87.5, 91.5, 98.7, 101.1, 107.5):
            chan = BAND_US.freq_to_channel(freq)
            assert BAND_US.channel_to_freq(chan) == pytest.approx(freq, abs=1e-9)

    def test_channel_to_freq_zero(self):
        assert BAND_US.channel_to_freq(0) == 87.5

    def test_channel_to_freq_56(self):
        # 87.5 + 56 * 0.2 = 87.5 + 11.2 = 98.7
        assert BAND_US.channel_to_freq(56) == pytest.approx(98.7)

    def test_spacing_mhz(self):
        assert BAND_US.spacing_mhz == pytest.approx(0.2)

    def test_de_emphasis_75us(self):
        assert BAND_US.de_emphasis_us == 75

    def test_band_bits(self):
        assert BAND_US.band_bits == 0b00

    def test_space_bits_200khz(self):
        assert BAND_US.space_bits == 0b00

    def test_out_of_range_below(self):
        with pytest.raises(ValueError, match="outside"):
            BAND_US.freq_to_channel(87.4)

    def test_out_of_range_above(self):
        with pytest.raises(ValueError, match="outside"):
            BAND_US.freq_to_channel(108.1)

    def test_error_message_contains_band_name(self):
        with pytest.raises(ValueError, match="US/Australia"):
            BAND_US.freq_to_channel(50.0)


class TestBandEU:
    """87.5–108 MHz, 100 kHz spacing, 50 µs de-emphasis."""

    def test_known_channel(self):
        # 97.3 MHz: (97.3 - 87.5) / 0.1 = 98.0
        assert BAND_EU.freq_to_channel(97.3) == 98

    def test_channel_to_freq(self):
        assert BAND_EU.channel_to_freq(98) == pytest.approx(97.3)

    def test_spacing_mhz(self):
        assert BAND_EU.spacing_mhz == pytest.approx(0.1)

    def test_de_emphasis_50us(self):
        assert BAND_EU.de_emphasis_us == 50

    def test_space_bits_100khz(self):
        assert BAND_EU.space_bits == 0b01

    def test_same_bottom_as_us(self):
        assert BAND_EU.bottom_mhz == BAND_US.bottom_mhz

    def test_finer_resolution_than_us(self):
        # EU has 100 kHz spacing — can tune to frequencies US can't
        chan = BAND_EU.freq_to_channel(98.6)
        assert BAND_EU.channel_to_freq(chan) == pytest.approx(98.6)


class TestBandJP:
    """Japan: 76–90 MHz."""

    def test_bottom(self):
        assert BAND_JP.bottom_mhz == 76.0

    def test_top(self):
        assert BAND_JP.top_mhz == 90.0

    def test_within_range(self):
        assert BAND_JP.freq_to_channel(82.0) == round((82.0 - 76.0) / 0.1)

    def test_out_of_range_above(self):
        with pytest.raises(ValueError):
            BAND_JP.freq_to_channel(91.0)

    def test_out_of_range_below(self):
        with pytest.raises(ValueError):
            BAND_JP.freq_to_channel(75.9)

    def test_band_bits(self):
        assert BAND_JP.band_bits == 0b10


class TestBandJPWide:
    """Japan Wide: 76–108 MHz."""

    def test_bottom(self):
        assert BAND_JP_WIDE.bottom_mhz == 76.0

    def test_top(self):
        assert BAND_JP_WIDE.top_mhz == 108.0

    def test_band_bits(self):
        assert BAND_JP_WIDE.band_bits == 0b01

    def test_covers_both_japan_and_eu_range(self):
        # Should be tunable to frequencies in both JP and EU ranges
        BAND_JP_WIDE.freq_to_channel(80.0)   # JP range — no error
        BAND_JP_WIDE.freq_to_channel(100.0)  # EU/US range — no error


class TestBandImmutability:
    def test_band_is_frozen(self):
        with pytest.raises((AttributeError, TypeError)):
            BAND_US.bottom_mhz = 88.0  # type: ignore[misc]
