"""Pure-logic tests for the SPHEREx blink pipeline. No network."""
import base64
import io
from collections import Counter

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from PIL import Image

from backend.spherex import (choose_images, display_xy, epoch_label, gaia_tracks, group_epochs, output_wcs, parse_coords, plan_epochs,
                             aperture_photometry, bad_pixels, centroid, saturated_holes, subtract_background, to_png,
                             gaia_overlay, mean_centroid, wavelength_range)


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


def star(n, gx, gy, peak=100.0, sigma=1.0):
    yy, xx = np.mgrid[:n, :n]
    return peak * np.exp(-((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * sigma**2))


def test_centroid_finds_the_star_in_png_coordinates():
    img = star(41, 20.3, 14.7)
    c = centroid(img, 20.0, 15.0)  # search near the predicted grid position
    # PNG coordinates: x = grid x + 0.5; y counts down from the top: 41 - 0.5 - 14.7
    assert (c["x"], c["y"]) == pytest.approx((20.8, 25.8), abs=0.05)


def test_centroid_ignores_a_nan_core_and_finds_nothing_on_empty_sky():
    img = star(41, 20.0, 15.0)
    img[15, 20] = np.nan  # saturated core
    assert (centroid(img, 20.0, 15.0)["x"], centroid(img, 20.0, 15.0)["y"]) == pytest.approx((20.5, 25.5), abs=0.05)
    noise = np.random.default_rng(1).normal(0.0, 1.0, (41, 41))
    assert centroid(noise, 20.0, 15.0) is None


def test_aperture_photometry_in_mjy_with_annulus_background():
    img = np.full((41, 41), 2.0)  # sky, MJy/sr
    img[14:17, 19:22] += 8.0  # a 3x3 source: 72 MJy/sr summed over pixels
    # 72 MJy/sr x (6.15 arcsec in rad)^2 = 6.40e-8 MJy = 64.0 mJy; a flat sky has no scatter
    assert aperture_photometry(img, 20.0, 15.0) == pytest.approx({"flux": 64.0, "err": 0.0}, abs=0.05)


def test_aperture_photometry_refuses_a_nan_in_the_aperture():
    img = np.full((41, 41), 2.0)
    img[15, 20] = np.nan  # saturated core: not measurable
    assert aperture_photometry(img, 20.0, 15.0) is None


def test_gaia_ghosts_move_by_proper_motion_east_left_north_up():
    center = SkyCoord(150.0, 2.2, unit="deg")
    grid, n = output_wcs(center, 49), 49
    stars = [{"ra": 150.0, "dec": 2.2, "pmra": 6150.0, "pmdec": 0.0, "g": 12.0},  # 1 px/yr to the east
             {"ra": 150.0, "dec": 2.2, "pmra": None, "pmdec": 12300.0, "g": 13.0}]  # 2 px/yr to the north
    mjds = [57388.5, 57388.5 + 2 * 365.25]  # Gaia epoch 2016.0, then two years later
    east, north = gaia_tracks(stars, grid, n, mjds)
    assert np.ravel(east["xy"]).tolist() == pytest.approx([24.5, 24.5, 22.5, 24.5], abs=0.01)
    assert np.ravel(north["xy"]).tolist() == pytest.approx([24.5, 24.5, 24.5, 20.5], abs=0.01)


def test_wavelength_range_spans_the_detector_bands_used():
    images = [{"em_min": 1.63, "em_max": 2.41}, {"em_min": 4.42, "em_max": 5.0}, {"em_min": 0.75, "em_max": 1.09}]
    assert wavelength_range(images) == [0.75, 5.0]


def test_centroid_error_has_a_systematic_floor_larger_for_saturated_cores():
    img = star(41, 20.0, 15.0, peak=1e6)  # so bright that the pixel noise error is ~0
    assert centroid(img, 20.0, 15.0)["ex"] == pytest.approx(0.1, abs=0.005)
    img[15, 20] = np.nan
    assert centroid(img, 20.0, 15.0)["ex"] == pytest.approx(0.3, abs=0.005)


def test_centroid_measures_the_star_not_the_predicted_position():
    img = star(41, 21.2, 15.6, peak=1000.0, sigma=1.5)  # the star sits 1.2 px east and 0.6 px off the prediction
    yy, xx = np.mgrid[:41, :41]
    img[np.hypot(xx - 21.2, yy - 15.6) <= 1.5] = np.nan  # saturated core
    c = centroid(img, 20.0, 15.0)
    assert (c["x"], c["y"]) == pytest.approx((21.7, 41 - 0.5 - 15.6), abs=0.02)


def test_frame_centroid_is_the_mean_of_the_detector_centroids_with_the_larger_error():
    detectors = [{"x": 10.0, "y": 20.0, "ex": 0.1, "ey": 0.1}, {"x": 10.4, "y": 20.0, "ex": 0.1, "ey": 0.1}, None]
    c = mean_centroid(detectors)
    assert (c["x"], c["y"]) == pytest.approx((10.2, 20.0))
    # x: the detectors disagree, so the scatter sets the error: std 0.283 / sqrt(2) = 0.2
    # y: they agree, so the propagated error stays: sqrt(0.1^2 + 0.1^2) / 2 = 0.071
    assert (c["ex"], c["ey"]) == pytest.approx((0.2, 0.071), abs=0.001)
    assert mean_centroid([None, None]) is None


def test_gaia_overlay_keeps_the_150_brightest_stars_that_enter_the_view():
    center = SkyCoord(150.0, 2.2, unit="deg")
    grid, n = output_wcs(center, 49), 49
    fixed = [{"source_id": str(k), "ra": 150.0, "dec": 2.2, "pmra": 0.0, "pmdec": 0.0, "gmag": 18.9 - 0.01 * k}
             for k in range(200)]
    far = {"source_id": "far", "ra": 150.2, "dec": 2.2, "pmra": 0.0, "pmdec": 0.0, "gmag": 5.0}  # bright, never inside
    # 30 px south of the center in 2016 (outside), moving 3 px/yr north: inside by 2026
    mover = {"source_id": "mover", "ra": 150.0, "dec": 2.2 - 30 * 6.15 / 3600, "pmra": 0.0, "pmdec": 3 * 6150.0,
             "gmag": 4.0}
    gaia = gaia_overlay(fixed + [far, mover], grid, n, [57388.5, 61041.0])
    ids = [s["source_id"] for s in gaia["stars"]]
    assert (len(ids), ids[:2], "far" in ids) == (150, ["mover", "199"], False)
    assert (gaia["release"], gaia["epoch_mjd"]) == ("Gaia DR3", 57388.5)
