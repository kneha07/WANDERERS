"""Tests for the SPHEREx stage (pipeline/survey/spherex.py). No network: synthetic cubes with the real DR1 layout,
served by a local range reader; pure-numpy tests of the photometry and spectral indices."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

import _spherex_synth as SY
from _spherex_synth import SX, mover, stage_for, write_cube

REAL_8545 = {"CRPIX1": 22528.5, "CRPIX2": 5120.5, "PC1_1": -0.00274658203125, "PC1_2": -0.00274658203125,
             "PC2_1": 0.00274658203125, "PC2_2": -0.00274658203125}          # read from the real cube header
KAPTEYN = (77.9599373502188, -45.0438126993602, 2016.0, 6491.223339061598, -5708.614150045243)
WISE0855 = (133.79513, -7.24515, 2010.5, -8123.0, 673.0)


# ------------------------------------------------------------------------------------------- URLs, headers, WCS
def test_cube_url_directories():
    assert SX.cube_url(8545).endswith("/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix8545_cube.fits")
    assert "/Dir10000/Npix10226_cube.fits" in SX.cube_url(10226)
    assert "/Dir0/Npix9999_" in SX.cube_url(9999) and "/Dir10000/Npix10000_" in SX.cube_url(10000)
    assert SX.cube_url(0).startswith("https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/")


@pytest.mark.parametrize("text,expected", [("D3:17,D4:01", [(3, 17), (4, 1)]), ("", []), (None, []),
                                           ("D6:5; junk, D1:x", [(6, 5)]), ("d2:03", [(2, 3)])])
def test_parse_blankch(text, expected):
    assert SX.parse_blankch(text) == expected


def test_mjd_to_year_and_real_tile_epoch():
    assert SX.mjd_to_year(51544.5) == 2000.0
    assert abs(SY.EPOCH - 2025.88) < 0.01


def test_hpx_header_matches_the_real_tile_8545_header():
    h = SX.hpx_tile_header(8545)
    for k, v in REAL_8545.items():
        assert h[k] == v, k
    assert (h["CTYPE1"], h["CTYPE2"], h["PV2_1"], h["PV2_2"]) == ("RA---HPX", "DEC--HPX", 4.0, 3.0)


@pytest.mark.parametrize("k5", [8545, 10226, 0, 5000, 12287])
def test_hpx_wcs_array_corners_are_the_healpix_tile_corners(k5):
    from astropy_healpix import HEALPix
    import astropy.units as u
    w = SX.celestial_wcs(SX.hpx_tile_header(k5), 512, 512)
    ra, dec = w.pixel_to_world_values(np.array([255.5]), np.array([255.5]))
    lon, lat = HEALPix(nside=32, order="nested").healpix_to_lonlat([k5])
    assert SX._sep(ra[0], dec[0], lon.to_value(u.deg)[0], lat.to_value(u.deg)[0]) < 0.5
    cx, cy = w.pixel_to_world_values(np.array([0.0, 511.0, 511.0, 0.0]), np.array([0.0, 0.0, 511.0, 511.0]))
    assert set(SX.tiles_of(cx, cy).tolist()) == {k5}           # pixels just inside the corners belong to the tile


def test_hpx_round_trip_at_kapteyns_star():
    w = SX.celestial_wcs(SX.hpx_tile_header(8545), 512, 512)
    ra, dec = 77.96, -45.044
    x, y = w.world_to_pixel_values(ra, dec)
    r2, d2 = w.pixel_to_world_values(x, y)
    assert SX._sep(ra, dec, float(r2), float(d2)) < 1e-6
    assert 0 <= float(x) < 512 and 0 <= float(y) < 512


def test_kapteyn_has_moved_into_tile_8523_by_2025_and_wise0855_stays_in_10226():
    ra, dec, ep, pmra, pmdec = KAPTEYN
    pred = SX._propagate(ra, dec, pmra, pmdec, SY.EPOCH - ep)
    assert SX.tiles_of(*pred)[0] == 8523                     # what the real run found: SPHEREx tile 8523
    x, _ = SX.celestial_wcs(SX.hpx_tile_header(8523), 512, 512).world_to_pixel_values(*pred)
    assert 510 < float(x) < 512                              # right at that tile's edge: the stamp spans two tiles
    ra, dec, ep, pmra, pmdec = WISE0855
    assert SX.tiles_of(*SX._propagate(ra, dec, pmra, pmdec, SY.EPOCH - ep))[0] == 10226


def test_pixel_solid_angle_and_size():
    lay = SX.CubeLayout(k5=1, url="", data_offset=0, nx=512, ny=512, nplanes=102, wcs=None, mjd_beg=None, mjd_end=None)
    assert lay.pix_sr == pytest.approx(4 * math.pi / (12 * 4 ** 14))
    assert lay.pix_arcsec == pytest.approx(12.88, abs=0.01)
    assert lay.epoch is None and lay.span_yr == 0.0
    assert lay.offset(1, 2, 3) == ((1 * 512 + 2) * 512 + 3) * 4


def test_tangent_offsets_and_tiles_of_nan():
    xi, eta = SX.tangent_offsets([10.0, 10.0], [20.0, 20.0 + 1 / 3600], 10.0, 20.0)
    assert abs(xi[0]) < 1e-9 and abs(eta[0]) < 1e-9 and eta[1] == pytest.approx(1.0, abs=1e-6)
    assert SX.tiles_of([np.nan, 77.96], [0.0, -45.04]).tolist() == [-1, 8545]


# ------------------------------------------------------------------------------------------- photometry (pure numpy)
def _gauss_stamp(flux_mjy, cx=0.0, cy=0.0, pix=10.0, half=6, sigma_px=0.55, noise=0.0, nch=5, seed=0):
    g = np.arange(-half, half + 1) * pix
    xi, eta = [a.ravel() for a in np.meshgrid(g, g)]
    pix_sr = (pix / SX.ARCSEC_PER_RAD) ** 2
    prof = np.exp(-0.5 * ((xi - cx) ** 2 + (eta - cy) ** 2) / (sigma_px * pix) ** 2) / (2 * math.pi * sigma_px ** 2)
    rng = np.random.default_rng(seed)
    vals = (flux_mjy / (pix_sr * 1e9)) * prof[None, :] + 0.1 + rng.normal(0, noise, (nch, xi.size))
    return vals, xi, eta, pix, pix_sr


def test_aperture_photometry_recovers_the_flux():
    vals, xi, eta, pix, sr = _gauss_stamp(2.0, noise=1e-4)
    ph = SX.aperture_photometry(vals, xi, eta, pix, sr)
    assert np.allclose(ph["flux"], 2.0, rtol=0.05)
    assert np.all(ph["err"] > 0) and np.allclose(ph["bkg"], 0.1, atol=1e-3)


def test_aperture_photometry_gap_in_the_aperture_or_annulus_gives_nan():
    vals, xi, eta, pix, sr = _gauss_stamp(2.0, noise=1e-4)
    vals[1, np.argmin(np.hypot(xi, eta))] = np.nan            # saturated core in channel 1
    vals[2, np.hypot(xi, eta) >= SX.R_IN * pix] = np.nan      # no background in channel 2
    ph = SX.aperture_photometry(vals, xi, eta, pix, sr)
    assert np.isnan(ph["flux"][1]) and np.isnan(ph["flux"][2]) and np.isfinite(ph["flux"][[0, 3, 4]]).all()


def test_broadband_and_matched_filter():
    f, e, s = SX.broadband(np.array([1.0, 3.0, np.nan]), np.array([1.0, 1.0, 1.0]))
    assert f == pytest.approx(2.0) and e == pytest.approx(1 / math.sqrt(2)) and s == pytest.approx(2 * math.sqrt(2))
    assert SX.broadband(np.array([np.nan]), np.array([1.0])) == (None, None, None)
    a, sa, sn = SX.matched(np.array([2.0, 4.0]), np.array([0.5, 0.5]), np.array([0.5, 1.0]))
    assert a == pytest.approx(4.0) and sn > 0
    assert SX.matched(np.array([2.0]), np.array([0.5]), np.array([0.0])) == (None, None, None)


def test_wise_template_follows_the_neowise_colour():
    t_red = SX.wise_template(SY.WAVES, 16.7, 13.9)
    assert np.all(t_red[SY.WAVES < 2.8] == 0) and t_red.max() == 1.0
    i3, i46 = np.argmin(abs(SY.WAVES - 3.35)), np.argmin(abs(SY.WAVES - 4.6))
    assert t_red[i46] > 5 * t_red[i3]                      # W1-W2 = 2.8: most weight on the W2 channels
    t_star = SX.wise_template(SY.WAVES, 10.0, 10.0)
    assert t_star[i3] > t_star[i46]                         # a star (W1-W2 = 0) is brighter at 3.35 um in F_nu
    assert np.array_equal(SX.wise_template(SY.WAVES, None, None) > 0, (SY.WAVES >= 2.8) & (SY.WAVES <= 5.0))
    assert SX.wise_template(SY.WAVES, None, 14.0)[i46] > SX.wise_template(SY.WAVES, None, 14.0)[i3]


def test_centroid_finds_an_offset_source_and_none_without_signal():
    vals, xi, eta, pix, sr = _gauss_stamp(5.0, cx=4.0, cy=-3.0, noise=1e-4)
    ph = SX.aperture_photometry(vals, xi, eta, pix, sr)
    cx, cy, ce = SX.centroid(vals, xi, eta, ph["bkg"], ph["sig"], pix)
    assert abs(cx - 4.0) < 1.5 and abs(cy + 3.0) < 1.5 and ce < 0.5
    flat_vals = np.full_like(vals, 0.1) + np.random.default_rng(3).normal(0, 1e-4, vals.shape)
    ph2 = SX.aperture_photometry(flat_vals, xi, eta, pix, sr)
    res = SX.centroid(-np.abs(flat_vals - 0.1) + 0.1, xi, eta, ph2["bkg"], ph2["sig"], pix)
    assert res is None


def test_error_floor_and_gone_verdicts():
    ph = SX.with_floor({"flux": np.array([100.0]), "err": np.array([0.0])})
    assert ph["err"][0] == pytest.approx(3.0)
    assert SX.gone_verdict(None, None, 10.0) is None
    assert SX.gone_verdict(1.0, 0.1, 10.0) is True              # nothing there
    assert SX.gone_verdict(8.0, 0.5, 10.0) is True              # a faint thing: < 1/10 of the flux now
    assert SX.gone_verdict(50.0, 9.0, 10.0) is False            # a comparable source is still there
    assert SX.gone_verdict(50.0, 9.0, None) is False            # nothing at the new spot, something at the old
    assert SX.gone_verdict(4.0, 3.0, 10.0) is None              # in between


def test_w2_ratio():
    f2 = SX.W2_ZERO_MJY * 10 ** (-0.4 * 12.0)
    flux = np.where(SY.WAVES > 4.1, f2, 0.0)
    assert SX.w2_ratio(SY.WAVES, flux, np.full(102, f2 / 50), 12.0) == pytest.approx(1.0)
    assert SX.w2_ratio(SY.WAVES, flux, np.full(102, f2 / 50), None) is None
    assert SX.w2_ratio(SY.WAVES, flux, np.full(102, f2 * 10), 12.0) is None     # not measured at 3 sigma


# ------------------------------------------------------------------------------------------- spectrum and indices
def test_band_groups_are_24_per_detector_runs():
    groups = SX.band_groups(SY.DETS, SY.SUBS)
    assert len(groups) == 24 and sum(len(g) for g in groups) == 102
    assert all(len(set(SY.DETS[g])) == 1 for g in groups)


def test_rebin_spectrum_weighted_mean_and_empty_band():
    flux = np.ones(102)
    flux[:5] = np.nan
    b = SX.rebin_spectrum(SY.WAVES, flux, np.full(102, 0.1), SX.band_groups(SY.DETS, SY.SUBS))
    assert np.isnan(b["mjy"][0]) and np.allclose(b["mjy"][1:], 1.0) and np.all((b["err"][2:] > 0.044) & (b["err"][2:] <= 0.05))
    assert np.all(np.diff(b["um"]) > 0) and 0.75 < b["um"][0] < 0.85 and 4.85 < b["um"][-1] < 5.0


def _planck_nu(wl_um, T):
    x = 14387.77 / (wl_um * T)
    return wl_um ** -3 / np.expm1(x)


def test_vega_like_spectrum_has_zero_w1w2_and_rj_star_is_blue_or_neutral():
    vega = np.where(SY.WAVES < 4.0, SX.W1_ZERO_MJY, SX.W2_ZERO_MJY) * 1e-6
    c = SX.synthetic_w1w2(SY.WAVES, vega, vega / 100)
    assert abs(c["w1w2"]) < 0.01 and c["w1w2_lim"] is False
    rj = 10.0 * (SY.WAVES / 3.35) ** -2
    assert abs(SX.synthetic_w1w2(SY.WAVES, rj, rj / 100)["w1w2"]) < 0.2


def test_brown_dwarf_spectrum_is_very_red_with_methane_and_a_4um_peak():
    f = SY.brown_dwarf(5.0)(SY.WAVES)
    ix = SX.spectral_indices(SY.WAVES, f, f * 0.03 + 0.01,
                             SX.rebin_spectrum(SY.WAVES, f, f * 0.03 + 0.01, SX.band_groups(SY.DETS, SY.SUBS)))
    assert ix["w1w2"] > 2 and ix["methane"] is True and ix["ch4_depth"] > 0.5
    assert 4.0 <= ix["peak_um"] <= 4.8
    assert any("methane" in h.lower() and "hint" in h.lower() for h in ix["hints"])
    assert any("very red" in h for h in ix["hints"])
    assert set(ix) == set(SX.INDEX_KEYS)


@pytest.mark.parametrize("T", [1500, 3000, 6000, 10000])
def test_no_methane_hint_for_any_blackbody(T):
    f = _planck_nu(SY.WAVES, T)
    f = f / f.max() * 10
    d, e = SX.methane_depth(SY.WAVES, f, f * 0.01)
    assert d <= 0.01                                          # power-law continuum: RJ exact, Wien bends the other way
    assert SX.spectral_indices(SY.WAVES, f, f * 0.01)["methane"] is False


def test_methane_needs_three_sigma_and_ten_percent():
    rj = 10.0 * (SY.WAVES / 3.35) ** -2
    shallow = np.where((SY.WAVES >= 3.2) & (SY.WAVES <= 3.45), rj * 0.95, rj)     # a 5 % dip: below the allowance
    assert SX.spectral_indices(SY.WAVES, shallow, shallow * 0.001)["methane"] is False
    deep = np.where((SY.WAVES >= 3.2) & (SY.WAVES <= 3.45), rj * 0.6, rj)
    assert SX.spectral_indices(SY.WAVES, deep, deep * 0.001)["methane"] is True
    assert SX.spectral_indices(SY.WAVES, deep, deep * 2.0)["methane"] is None     # continuum not measured


def test_undetected_short_band_gives_a_lower_limit():
    f = np.where(SY.WAVES > 4.0, 1.0, 0.0)
    c = SX.synthetic_w1w2(SY.WAVES, f, np.full(102, 0.02))
    assert c["w1w2_lim"] is True and c["w1w2"] > 3 and c["w1w2_err"] is None


# ------------------------------------------------------------------------------------------- result dicts
def test_compact_has_fixed_keys_rounding_and_is_json_safe():
    d = SX.compact({"checked": True, "detected": True, "confirmed": True, "snr": 12.3456, "offset_arcsec": float("nan"),
                    "spectrum": {"um": [1.23456], "mjy": [float("nan")], "err": [0.123456]},
                    "indices": {"w1w2": 2.345, "hints": ["x"] * 9}, "notes": ["a"], "tile": np.int64(5)})
    assert list(d) == SX.SPHEREX_KEYS
    assert d["snr"] == 12.3 and d["offset_arcsec"] is None and d["tile"] == 5
    assert d["spectrum"] == {"um": [1.23], "mjy": [None], "err": [0.12]}
    assert list(d["indices"]) == SX.INDEX_KEYS and len(d["indices"]["hints"]) == 4
    json.dumps(d, allow_nan=False)
    assert list(SX.compact("junk")) == SX.SPHEREX_KEYS and SX.compact("junk")["checked"] is False


def test_unchecked_and_retryable():
    u = SX.unchecked("network: timed out")
    assert list(SX.compact(u)) == SX.SPHEREX_KEYS and u["confirmed"] is False
    assert SX.is_retryable(u) and SX.is_retryable(SX.unchecked(SX.BUDGET))
    assert not SX.is_retryable(SX.unchecked("no SPHEREx cube for this tile"))
    assert not SX.is_retryable({"checked": True, "error": "network: x"})


# ------------------------------------------------------------------------------------------- synthetic cubes end to end
K = 10226                                       # an equatorial tile (WISE 0855's)
FAST = (-40000.0, 3000.0)                       # mas/yr: 40"/yr moves ~4 coarse pixels from 2014 to 2025.9


@pytest.fixture(scope="module")
def centre():
    lay_w = SX.celestial_wcs(SX.hpx_tile_header(K, 64), 64, 64)
    ra, dec = lay_w.pixel_to_world_values(np.array([31.5]), np.array([31.5]))
    return float(ra[0]), float(dec[0])


def _pred(m):
    return SX._propagate(m["ra"], m["dec"], m["pmra"], m["pmdec"], SY.EPOCH - m["epoch"])


def _old(m):
    return SX._propagate(m["ra"], m["dec"], m["pmra"], m["pmdec"], m["track"][0][0] - m["epoch"])


def test_read_layout_walks_the_headers_with_few_small_reads(tmp_path):
    p = write_cube(tmp_path / "c.fits", K)
    st, rd = stage_for({K: p})
    lay = st.layout(K)
    assert (lay.nx, lay.ny, lay.nplanes) == (64, 64, 102) and lay.data_offset == 2880 * 3 or lay.data_offset % 2880 == 0
    assert lay.epoch == pytest.approx(SY.EPOCH) and lay.span_yr == pytest.approx(0.606, abs=0.01)
    assert sorted(lay.blank) == [50, 51]                       # D3:17 and D4:01
    assert np.allclose(lay.wavelengths, SY.WAVES, rtol=1e-6)
    assert len(rd.calls) <= 6 and sum(b - a for _, a, b in rd.calls) < 100_000
    st.layout(K)
    assert len(rd.calls) <= 6                                  # cached


def test_source_where_predicted_is_detected_at_predicted(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1], epoch=2019.0)
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(m), SY.flat(3.0))])
    st, rd = stage_for({K: p})
    r = st.check_tile(K, [m])[0]
    assert r["checked"] and r["detected"] and r["at_predicted"] is True
    assert r["offset_arcsec"] <= 3 * r["offset_err"]
    assert r["gone_from_2014"] is True and r["confirmed"] is True
    assert r["expected_offset"] == pytest.approx(SX._sep(*_pred(m), *_old(m)), rel=1e-3)
    assert r["epoch"] == pytest.approx(SY.EPOCH, abs=1e-3) and r["tile"] == K


def test_spectrum_is_24_bands_of_the_injected_flux(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1])
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(m), SY.flat(3.0))])
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    sp = r["spectrum"]
    assert len(sp["um"]) == len(sp["mjy"]) == len(sp["err"]) == 24
    good = [v for v in sp["mjy"] if v is not None]
    assert len(good) == 24 and np.allclose(good, 3.0, rtol=0.1)
    assert all(e > 0 for e in sp["err"])
    assert len(json.dumps(r)) < 1500


def test_blank_channels_are_never_read(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1])
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(m), SY.flat(3.0))])
    st, rd = stage_for({K: p})
    st.check_tile(K, [m])
    lay = st.layouts[K]
    plane_bytes = lay.nx * lay.ny * 4
    touched = {(a - lay.data_offset) // plane_bytes for _, a, b in rd.calls
               if lay.data_offset <= a < lay.data_offset + lay.nplanes * plane_bytes}
    assert touched.isdisjoint(lay.blank) and len(touched) == 100


def test_stationary_source_with_a_bogus_motion_is_not_where_predicted(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1])
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_old(m), SY.flat(3.0))])    # still at its 2014 spot
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    assert r["checked"] and r["detected"] is False and r["gone_from_2014"] is False
    assert r["at_predicted"] is False and r["confirmed"] is False
    assert any("2014 position" in n for n in r["notes"])


def test_nothing_there_is_not_detected(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1])
    p = write_cube(tmp_path / "c.fits", K)
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    assert r["checked"] and r["detected"] is False and r["at_predicted"] is None and r["confirmed"] is False
    assert r["spectrum"] is None and r["indices"] is None


def test_source_two_pixels_away_is_not_at_predicted(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1])
    pred = _pred(m)
    off = SX._propagate(pred[0], pred[1], 0.0, 1.0, 1.4 * SX.R_AP * 103.0 * 1000.0)   # ~1.4 apertures north
    p = write_cube(tmp_path / "c.fits", K, sources=[(*off, SY.flat(30.0))])
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    assert r["at_predicted"] is not True and r["confirmed"] is False


def test_slow_mover_is_there_but_cannot_be_confirmed(tmp_path, centre):
    m = mover(*centre, pmra=300.0, pmdec=0.0)
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(m), SY.flat(3.0))])
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    assert r["at_predicted"] is True and r["confirmed"] is False and r["gone_from_2014"] is None
    assert any("Too slow" in n for n in r["notes"])


def test_red_brown_dwarf_gets_spectral_hints(tmp_path, centre):
    m = mover(*centre, pmra=FAST[0], pmdec=FAST[1], w1=16.0, w2=12.5)
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(m), SY.brown_dwarf(5.0))])
    r = stage_for({K: p})[0].check_tile(K, [m])[0]
    ix = r["indices"]
    assert r["confirmed"] and ix["w1w2"] > 2 and ix["methane"] is True and ix["peak_um"] >= 4.0


def test_two_close_movers_share_their_reads(tmp_path, centre):
    a = mover(*centre, pmra=300.0, pmdec=0.0, id="a")
    b = mover(centre[0] + 0.01, centre[1] + 0.005, pmra=300.0, pmdec=0.0, id="b")
    p = write_cube(tmp_path / "c.fits", K, sources=[(*_pred(a), SY.flat(3.0)), (*_pred(b), SY.flat(3.0))])
    st, rd = stage_for({K: p})
    res = st.check_tile(K, [a, b])
    n_layout = len([c for c in rd.calls if c[1] < st.layouts[K].data_offset or c[1] > st.layouts[K].offset(102, 0, 0)])
    assert all(r["checked"] for r in res)
    assert len(rd.calls) - n_layout == 100                      # one read per plane for both movers


def _neighbour(k5, side=0):
    from astropy_healpix import HEALPix
    nb = HEALPix(nside=32, order="nested").neighbours(k5)
    return int(nb[side])


def test_stamp_at_the_tile_edge_uses_the_neighbouring_cube(tmp_path):
    w = SX.celestial_wcs(SX.hpx_tile_header(K, 64), 64, 64)
    ra, dec = w.pixel_to_world_values(np.array([63.5]), np.array([31.5]))     # on the tile's edge (x = 63.5)
    ra, dec = float(ra[0]), float(dec[0])
    nb = int(SX.tiles_of(*w.pixel_to_world_values(np.array([64.2]), np.array([31.5])))[0])
    assert nb != K
    m = mover(ra, dec, pmra=0.0, pmdec=0.0, epoch=SY.EPOCH)
    files = {K: write_cube(tmp_path / "a.fits", K, sources=[(ra, dec, SY.flat(4.0))]),
             nb: write_cube(tmp_path / "b.fits", nb, sources=[(ra, dec, SY.flat(4.0))])}
    st, rd = stage_for(files)
    r = st.check_tile(K, [m])[0]
    assert r["checked"] and r["detected"] and nb in st.layouts
    good = [v for v in r["spectrum"]["mjy"] if v is not None]
    assert np.allclose(good, 4.0, rtol=0.15)
    # without the neighbour's cube half the aperture has no data: no usable channel, not a wrong flux
    st2, _ = stage_for({K: files[K]})
    r2 = st2.check_tile(K, [m])[0]
    assert r2["checked"] is False and "no usable" in r2["error"]


def test_a_mover_that_crossed_into_the_neighbour_is_measured_there(tmp_path):
    w = SX.celestial_wcs(SX.hpx_tile_header(K, 64), 64, 64)
    ra0, dec0 = (float(v[0]) for v in w.pixel_to_world_values(np.array([60.0]), np.array([31.5])))
    ra1, dec1 = (float(v[0]) for v in w.pixel_to_world_values(np.array([70.0]), np.array([31.5])))
    nb = int(SX.tiles_of(ra1, dec1)[0])
    sep = SX._sep(ra0, dec0, ra1, dec1)
    dra = (ra1 - ra0) * math.cos(math.radians(dec0)) * 3.6e6 / (SY.EPOCH - 2019.0)
    ddec = (dec1 - dec0) * 3.6e6 / (SY.EPOCH - 2019.0)
    m = mover(ra0, dec0, epoch=2019.0, pmra=dra, pmdec=ddec)
    pred = _pred(m)
    assert SX.tiles_of(*pred)[0] == nb and sep > 100
    files = {K: write_cube(tmp_path / "a.fits", K), nb: write_cube(tmp_path / "b.fits", nb, sources=[(*pred, SY.flat(3.0))])}
    r = stage_for(files)[0].check_tile(K, [m])[0]
    assert r["tile"] == nb and r["detected"] and r["at_predicted"] is True
    assert any(f"tile {nb}" in n for n in r["notes"])


# ------------------------------------------------------------------------------------------- failures never raise
def test_network_failure_on_the_headers_gives_checked_false(tmp_path, centre):
    p = write_cube(tmp_path / "c.fits", K)
    st, _ = stage_for({K: p}, fail_after=0)
    res = st.check_tile(K, [mover(*centre), mover(*centre, id="x")])
    assert [r["checked"] for r in res] == [False, False]
    assert all(r["error"].startswith("network: ") and SX.is_retryable(r) for r in res)


def test_network_failure_while_reading_planes(tmp_path, centre):
    p = write_cube(tmp_path / "c.fits", K, sources=[(*centre, SY.flat(3.0))])
    st, rd = stage_for({K: p}, fail_after=8)
    r = st.check_tile(K, [mover(*centre)])[0]
    assert r["checked"] is False and r["error"].startswith("network: ")


def test_missing_cube_bad_mover_and_spent_budget(tmp_path, centre):
    st, _ = stage_for({})
    assert st.check_tile(K, [mover(*centre)])[0]["error"] == "no SPHEREx cube for this tile"
    p = write_cube(tmp_path / "c.fits", K)
    st, _ = stage_for({K: p})
    bad = st.check_tile(K, [{"id": "x"}])[0]
    assert bad["checked"] is False and "missing" in bad["error"]
    late = st.check_tile(K, [mover(*centre)], deadline=-1.0)[0]
    assert late["error"] == SX.BUDGET and SX.is_retryable(late)


def test_module_check_tile_never_raises():
    class Boom:
        def check_tile(self, *a, **k):
            raise RuntimeError("boom")
    res = SX.check_tile(K, [{"id": "a"}], stage=Boom())
    assert res[0]["checked"] is False and "internal" in res[0]["error"]


class _Resp:
    def __init__(self, status, data=b"", headers=None):
        self.status, self._data, self.headers = status, data, headers or {}

    def read(self):
        return self._data

    def release_conn(self):
        pass


def test_http_reader_refuses_a_whole_file_answer_and_maps_404():
    rd = SX.HttpRangeReader(workers=2)
    rd.pool.request = lambda *a, **k: _Resp(200, b"x" * 10)
    with pytest.raises(SX.NetworkError):
        rd.read("u", 0, 10)
    rd.pool.request = lambda *a, **k: _Resp(404)
    with pytest.raises(SX.CubeMissing):
        rd.read("u", 0, 10)
    rd.pool.request = lambda *a, **k: _Resp(206, b"abcd", {"Content-Range": "bytes 0-3/320909760"})
    assert rd.read("u", 0, 4) == b"abcd" and rd.sizes["u"] == 320909760 and rd.counter.bytes == 4


def test_http_reader_wraps_connection_errors():
    import urllib3
    rd = SX.HttpRangeReader(workers=2)

    def boom(*a, **k):
        raise urllib3.exceptions.MaxRetryError(None, "u", "down")
    rd.pool.request = boom
    with pytest.raises(SX.NetworkError):
        rd.read("u", 0, 10)


def test_tile_headers_kept_in_memory_are_capped(tmp_path, centre, monkeypatch):
    p = write_cube(tmp_path / "c.fits", K)
    st, _ = stage_for({K: p})
    monkeypatch.setattr(SX, "MAX_LAYOUTS", 2)
    for k in (1, 2, 3):
        st.layouts[k] = object()
    st.check_tile(K, [mover(*centre)])
    assert set(st.layouts) == {K}
