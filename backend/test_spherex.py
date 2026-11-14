"""Pure-logic tests for the SPHEREx blink pipeline. No network."""
import base64
import io
from collections import Counter

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from PIL import Image

from backend.spherex import (choose_images, display_xy, epoch_label, group_epochs, output_wcs, parse_coords, plan_epochs,
                             bad_pixels, saturated_holes, subtract_background, to_png)


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


def rows(times_by_detector):
    return [{"detector": d, "mjd": t} for d, ts in times_by_detector.items() for t in ts]


def test_choice_takes_detectors_round_robin():
    images = rows({f"D{k}": [k + 10.0 * i for i in range(5)] for k in range(1, 7)})  # 6 x 5 images
    assert Counter(r["detector"] for r in choose_images(images, 12)) == {f"D{k}": 2 for k in range(1, 7)}


def test_choice_spreads_picks_in_time_within_a_detector():
    chosen = choose_images(rows({"D5": [float(t) for t in range(9)]}), 3)
    assert [r["mjd"] for r in chosen] == [0.0, 4.0, 8.0]


def test_choice_gives_spare_slots_to_detectors_with_more_images():
    chosen = choose_images(rows({"D1": [1.0, 2.0, 3.0, 4.0, 5.0], "D2": [6.0]}), 4)
    assert [r["mjd"] for r in chosen] == [1.0, 3.0, 5.0, 6.0]


def test_choice_returns_all_images_when_fewer_than_asked():
    assert [r["mjd"] for r in choose_images(rows({"D3": [2.0], "D1": [1.0]}), 12)] == [1.0, 2.0]


def test_ring_at_grid_center_is_in_the_middle_of_the_png():
    center = SkyCoord(133.76, -7.24, unit="deg")
    assert display_xy(output_wcs(center, 49), 49, center) == pytest.approx((24.5, 24.5))


def test_ring_is_north_up_east_left_with_top_left_origin():
    center = SkyCoord(269.45, 60.0, unit="deg")
    star = center.spherical_offsets_by(5 * 6.15 * u.arcsec, 10 * 6.15 * u.arcsec)  # 5 px east, 10 px north
    assert display_xy(output_wcs(center, 49), 49, star) == pytest.approx((24.5 - 5, 24.5 - 10), abs=0.01)


def test_png_pixels_and_ring_agree_on_where_a_star_is():
    center, n = SkyCoord(10.0, 20.0, unit="deg"), 21
    grid = output_wcs(center, n)
    star = center.spherical_offsets_by(-6 * 6.15 * u.arcsec, 4 * 6.15 * u.arcsec)  # 6 px west, 4 px north
    x, y = grid.wcs_world2pix(star.ra.deg, star.dec.deg, 0)
    frame = np.zeros((n, n))
    frame[round(float(y)), round(float(x))] = 1.0  # frames are indexed [grid y, grid x]
    png = np.asarray(Image.open(io.BytesIO(base64.b64decode(to_png(frame).split(",")[1]))))
    row, col = np.unravel_index(np.argmax(png), png.shape)
    ring_x, ring_y = display_xy(grid, n, star)
    assert (col, row) == (int(ring_x), int(ring_y)) == (16, 6)


def test_background_removes_a_sky_gradient_and_keeps_stars():
    yy, xx = np.mgrid[:49, :49]
    cutout = 5.0 + 0.02 * xx - 0.03 * yy  # sky level plus a gradient (airglow, zodi)
    cutout[20, 30] += 10.0  # a star
    cutout[3, 3] = np.nan  # a masked pixel
    flat = subtract_background(cutout)
    assert flat[20, 30] == pytest.approx(10.0)
    flat[20, 30] = 0.0
    assert np.isnan(flat[3, 3])
    assert np.nanmax(np.abs(flat)) == pytest.approx(0.0, abs=1e-9)


def test_saturated_holes_are_nan_cores_inside_bright_stars_only():
    yy, xx = np.mgrid[:21, :21]
    frame = 100.0 * np.exp(-((xx - 10) ** 2 + (yy - 10) ** 2) / 8.0)  # a bright star
    frame[10:12, 10:12] = np.nan  # its saturated core: no data
    frame[:, 0] = np.nan  # off the detector, touches the edge
    frame[3, 16] = np.nan  # a bad pixel on dark sky
    holes = saturated_holes(frame)
    assert holes.sum() == 4
    assert holes[10:12, 10:12].all()


def test_epoch_labels_are_date_ranges_and_unique_for_30_day_bins():
    # MJD 60902 = 2025-08-15. One 70-day pass is cut into three 30-day bins.
    mjds = [60902.2, 60915.0, 60931.5, 60933.0, 60950.0, 60962.0, 60972.0]
    labels = [epoch_label([mjds[i] for i in g]) for g in group_epochs(mjds)]
    assert labels == ["2025-08-15 to 09-13", "2025-09-15 to 10-14", "2025-10-24"]


def test_epoch_label_spanning_new_year_shows_both_years():
    assert epoch_label([61029.0, 61053.0]) == "2025-12-20 to 2026-01-13"


def two_passes_of_six_detectors():
    """2 survey passes 180 days apart; each has 5 images on each of D1..D6."""
    return [{"detector": f"D{d}", "mjd": start + d + 0.1 * i} for start in (60000.0, 60180.0)
            for d in range(1, 7) for i in range(5)]


def test_plan_uses_one_detector_only_when_asked():
    epochs = plan_epochs(two_passes_of_six_detectors(), 4, "D6")
    assert [len(e) for e in epochs] == [4, 4]
    assert {im["detector"] for e in epochs for im in e} == {"D6"}


def test_plan_mixes_all_detectors_by_default():
    epochs = plan_epochs(two_passes_of_six_detectors(), 12)
    assert [Counter(im["detector"] for im in e) for e in epochs] == [{f"D{d}": 2 for d in range(1, 7)}] * 2


def test_bad_pixels_mask_saturation_and_defects_but_keep_bloomed_star_pixels():
    clean, overflow, transient, hot, bloom, source = 0, 2, 1, 1024, 67108864, 2097152
    flags = np.array([clean, overflow, transient, transient | bloom, hot, bloom, source, overflow | bloom])
    assert bad_pixels(flags).tolist() == [False, True, True, False, True, False, False, True]


def test_off_center_saturated_core_counts_but_a_bad_pixel_by_a_faint_star_does_not():
    # Real cores seen on R Dra and Barnard's Star have rims of 0.12 to 0.8 of the frame maximum.
    yy, xx = np.mgrid[:31, :31]
    frame = 100.0 * np.exp(-((xx - 10) ** 2 + (yy - 10) ** 2) / 8.0)  # bright star
    frame += 3.0 * np.exp(-((xx - 24) ** 2 + (yy - 24) ** 2) / 2.0)  # faint star
    frame[11:14, 11:14] = np.nan  # saturated core, off the star's center: rim median is 0.22 of max
    frame[24, 25] = np.nan  # bad pixel next to the faint star: rim median is 0.01 of max
    holes = saturated_holes(frame)
    assert holes.sum() == 9
    assert holes[11:14, 11:14].all()
