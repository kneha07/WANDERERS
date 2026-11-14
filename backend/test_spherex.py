"""Pure-logic tests for the SPHEREx blink pipeline. No network."""
import pytest

from backend.spherex import group_epochs, parse_coords


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


def test_epochs_split_where_gap_is_more_than_20_days():
    # input is unsorted; time-sorted gaps are 19.5 d (same epoch), 20.5 d (new epoch), 1 d
    assert group_epochs([60040.0, 60000.0, 60019.5, 60041.0]) == [[1, 2], [0, 3]]


def test_epoch_longer_than_45_days_is_cut_into_30_day_bins():
    # one 70-day epoch with no 20-day gap -> bins [0, 30), [30, 60), [60, 90)
    mjds = [0.0, 10.0, 29.0, 31.0, 45.0, 59.0, 61.0, 70.0]
    assert group_epochs(mjds) == [[0, 1, 2], [3, 4, 5], [6, 7]]


def test_epoch_of_exactly_45_days_stays_whole():
    assert group_epochs([0.0, 15.0, 30.0, 45.0]) == [[0, 1, 2, 3]]


def test_more_than_12_epochs_keeps_12_evenly_spaced_with_first_and_last():
    mjds = [100.0 * k for k in range(23)]  # 23 epochs, 100 days apart
    kept = [g[0] for g in group_epochs(mjds)]
    assert kept == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
