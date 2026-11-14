"""Pure-logic tests for the SPHEREx blink pipeline. No network."""
import pytest

from backend.spherex import parse_coords


def test_sexagesimal_with_hms_letters():
    c = parse_coords("08h55m10.831s -07d14m42.53s")
    assert c.ra.deg == pytest.approx(133.795129, abs=1e-6)
    assert c.dec.deg == pytest.approx(-7.245147, abs=1e-6)


def test_sexagesimal_with_colons():
    c = parse_coords("17:57:48.5 +04:41:36")
    assert c.ra.deg == pytest.approx(269.452083, abs=1e-6)
    assert c.dec.deg == pytest.approx(4.693333, abs=1e-6)


@pytest.mark.parametrize("q", ["269.45 4.69", "269.45, 4.69", " 269.45,4.69 "])
def test_two_decimals_are_degrees(q):
    c = parse_coords(q)
    assert (c.ra.deg, c.dec.deg) == pytest.approx((269.45, 4.69))


@pytest.mark.parametrize("q", ["10 95", "10, -90.5", "400 10", "12h00m00s +95d00m00s", "42"])
def test_bad_coordinates_raise_value_error_with_a_hint(q):
    with pytest.raises(ValueError, match="RA/Dec"):
        parse_coords(q)


@pytest.mark.parametrize("q", ["Barnard's Star", "R Dra", "WISE J085510.83-071442.5", "hd 123"])
def test_names_are_not_coordinates(q):
    assert parse_coords(q) is None
