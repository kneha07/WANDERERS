"""Validation harness, part 1: synthetic detections (inject), the noise model, cadence copying, synthetic empty
skies and the year-by-year reader. No network.
    "<venv>/bin/python" -m pytest tests/test_survey_validate.py -q"""
import math
import re
import sys
import unittest
from pathlib import Path

try:
    import pyarrow as pa
    import pytest
except ImportError as e:  # e.g. `python -m unittest discover` without the survey's dependencies
    raise unittest.SkipTest(f"survey validation tests need pyarrow and pytest ({e})")
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from survey import validate as V  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
KAPTEYN = FIX / "neowise_kapteyn_4arcmin.parquet"
W0855 = FIX / "neowise_wise0855_4arcmin.parquet"


@pytest.fixture(scope="module")
def w0855():
    return pq.read_table(W0855)


@pytest.fixture(scope="module")
def kapteyn():
    return pq.read_table(KAPTEYN)


def cols_of(table):
    return {c: table.column(c).to_numpy(zero_copy_only=False) for c in table.column_names}


def injected_part(before, after):
    return after.slice(before.num_rows)


def dense_cadence(n_visits=40, per_visit=50, seed=0):
    return V.synthetic_cadence(seed, n_visits=n_visits, per_visit=per_visit, overlap_fraction=0.0)


# ------------------------------------------------------------------ astrometry helpers
def test_mjd_year_roundtrip():
    mjd = np.array([51544.5, 56700.25, 60400.0])
    assert np.allclose(V.year_to_mjd(V.mjd_to_year(mjd)), mjd)
    assert V.mjd_to_year(51544.5) == pytest.approx(2000.0)
    assert V.mjd_to_year(51544.5 + 365.25) == pytest.approx(2001.0)


@pytest.mark.parametrize("ra0,dec0", [(10.0, 20.0), (359.99, -5.0), (0.01, 45.0), (200.0, 89.98), (77.0, -89.97)])
def test_tangent_offset_roundtrip(ra0, dec0):
    dx, dy = np.array([-120.0, 0.0, 33.3, 500.0]), np.array([45.0, -300.0, 0.0, 250.0])
    ra, dec = V.offset_radec(ra0, dec0, dx, dy)
    bx, by = V.tangent_offset(ra0, dec0, ra, dec)
    assert np.allclose(bx, dx, atol=1e-6) and np.allclose(by, dy, atol=1e-6)
    assert np.all((ra >= 0) & (ra < 360))


def test_offset_radec_wraps_ra_across_zero():
    ra, dec = V.offset_radec(359.999, 0.0, 10.0, 0.0)  # 10" east of RA 359.999
    assert 0 <= ra < 0.01 and ra == pytest.approx((359.999 + 10 / 3600) % 360, abs=1e-9)


def test_sep_arcsec_known_values():
    assert V.sep_arcsec(10, 0, 10, 1) == pytest.approx(3600.0, rel=1e-9)
    assert V.sep_arcsec(359.9999, 0, 0.0001, 0) == pytest.approx(0.72, rel=1e-6)
    assert V.sep_arcsec(0, 90, 180, 90) == pytest.approx(0.0, abs=1e-6)


def test_destination_distance_and_position_angle():
    ra, dec = V.destination(100.0, 30.0, 0.5, 60.0)
    assert V.sep_arcsec(100.0, 30.0, ra, dec) == pytest.approx(1800.0, rel=1e-9)
    dx, dy = V.tangent_offset(100.0, 30.0, ra, dec)
    assert math.degrees(math.atan2(dx, dy)) == pytest.approx(60.0, abs=0.01)


def test_propagate_moves_by_pm_times_time():
    ra, dec = V.propagate(150.0, -30.0, 2016.0, 3000.0, -4000.0, 2026.0)
    assert V.sep_arcsec(150.0, -30.0, ra, dec) == pytest.approx(50.0, rel=1e-4)


def test_cap_area():
    assert V.cap_area_deg2(180.0) == pytest.approx(41252.96, rel=1e-5)
    assert V.cap_area_deg2(0.1) == pytest.approx(math.pi * 0.01, rel=1e-4)


def test_tiles_contract_numbers():
    assert V.N_TILES == 12288
    assert V.TILE_AREA_DEG2 == pytest.approx(3.357, abs=1e-3)
    assert V.tile_of(77.96, -45.04) == 8545  # Kapteyn's Star, as in docs/survey-contract.md


@pytest.mark.parametrize("k5", [0, 1023, 8545, 10226, 12287])
def test_tile_center_lies_in_its_tile(k5):
    ra, dec = V.tile_center(k5)
    assert V.tile_of(ra, dec) == k5


def test_parallax_factors_match_vector_geometry():
    # independent check: displacement of the direction to a star 1/plx AU away, seen from the Earth
    mjd = np.array([57000.0, 57100.0, 57200.0, 57300.0])
    ra, dec, plx_arcsec = 40.0, 25.0, 0.5
    fe, fn = V.parallax_factors(ra, dec, mjd)
    xyz = V.earth_xyz_au(mjd)
    a, d = math.radians(ra), math.radians(dec)
    u = np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])
    dist_au = 1 / math.radians(plx_arcsec / 3600)
    for k in range(len(mjd)):
        v = dist_au * u - xyz[:, k]
        v /= np.linalg.norm(v)
        ra_k, dec_k = math.degrees(math.atan2(v[1], v[0])) % 360, math.degrees(math.asin(v[2]))
        dx, dy = V.tangent_offset(ra, dec, ra_k, dec_k)
        assert dx == pytest.approx(plx_arcsec * fe[k], abs=2e-5)
        assert dy == pytest.approx(plx_arcsec * fn[k], abs=2e-5)


def test_pm_from_vtan():
    assert V.pm_from_vtan(4740.47, 47.4047) == pytest.approx(474.047, rel=1e-6)  # 4.74 * 4.74"/yr / 47.4 km/s
    assert V.pm_from_vtan(1000.0, None) == 0.0


# ------------------------------------------------------------------ noise model
def test_snr_model_calibration_points():
    assert V.snr_model(14.34, "w2") == pytest.approx(4.8, abs=0.3)   # W2 single-exposure 5-sigma ~14.3
    assert V.snr_model(16.02, "w1") == pytest.approx(4.8, abs=0.3)   # W1 ~16.0
    assert 55 < V.snr_model(8.0, "w2") < 75 and 55 < V.snr_model(8.0, "w1") < 80  # bright plateau
    m = np.linspace(6, 18, 50)
    assert np.all(np.diff(V.snr_model(m, "w2")) < 0) and np.all(np.diff(V.snr_model(m, "w1")) < 0)


@pytest.mark.parametrize("band", ["w1", "w2"])
@pytest.mark.parametrize("path", [W0855, KAPTEYN])
def test_snr_model_agrees_with_real_detections(band, path):
    c = cols_of(pq.read_table(path))
    snr, mag = np.asarray(c[f"{band}snr"], float), np.asarray(c[f"{band}mpro"], float)
    ok = np.isfinite(snr) & np.isfinite(mag) & (snr >= 10) & (snr < 50) & (mag > 9)
    ratio = np.median(snr[ok] / V.snr_model(mag[ok], band))
    assert 0.8 < ratio < 1.25, ratio


def test_reported_sigma_agrees_with_real_detections(w0855):
    c = cols_of(w0855)
    comb = np.hypot(np.nan_to_num(np.asarray(c["w1snr"], float)).clip(0), np.nan_to_num(np.asarray(c["w2snr"], float)).clip(0))
    sra = np.asarray(c["sigra"], float)
    ok = np.isfinite(sra) & (comb > 5)
    model, _ = V.reported_sigma(comb[ok])
    assert np.median(sra[ok] / model) == pytest.approx(1.0, abs=0.1)


def test_true_sigma_values():
    s10 = V.true_sigma(10.0, 10.0)[0]
    s14 = V.true_sigma(14.0, 14.0)[0]
    s_lim = V.true_sigma(15.7, 15.5)[0]
    assert 0.04 < s10 < 0.09
    assert 0.12 < s14 < 0.2
    assert 0.4 < s_lim < 1.0
    m = np.linspace(9, 15.5, 30)
    assert np.all(np.diff(V.true_sigma(m, m)[0]) > 0)


def test_saturation_scatter():
    assert V.saturation_scatter(9.0, 9.0) == 0
    assert V.saturation_scatter(6.0, 5.8) == pytest.approx(0.9)       # Kapteyn's Star: ~0.9" per exposure
    assert V.saturation_scatter(2.0, 2.0) == pytest.approx(1.0)       # capped
    assert V.true_sigma(6.0, 5.8)[0] > 0.85


def test_ph_qual_letters():
    assert list(V.ph_qual_letter([25, 10, 9.9, 3.1, 3.0, 2.0, 1.9, -3])) == list("AABBCCUU")


# ------------------------------------------------------------------ cadence
def test_exposures_from_fixture_are_unique_and_sorted(w0855):
    e = V.exposures(w0855)
    assert len(e["mjd"]) == len(np.unique(cols_of(w0855)["mjd"])) == 439
    assert np.all(np.diff(e["mjd"]) > 0)
    assert len(e["scan_id"]) == len(e["frame_num"]) == 439


def test_exposures_near_a_spot_are_frames_covering_it(w0855):
    all_e = V.exposures(w0855)
    loc = V.exposures(w0855, near=(133.79, -7.24), radius_arcsec=60)
    loc45 = V.exposures(w0855, near=(133.79, -7.24), radius_arcsec=45)
    assert set(loc["mjd"]) <= set(all_e["mjd"])
    # ~3/4 of the frames in the 6' cut-out cover its centre: 12-26 per visit, every visit present
    assert 0.6 * len(all_e["mjd"]) < len(loc["mjd"]) < 0.9 * len(all_e["mjd"])
    assert np.bincount(V.split_visits(loc["mjd"])).min() >= 10
    assert abs(len(loc45["mjd"]) - len(loc["mjd"])) <= 0.03 * len(loc["mjd"])  # stable: a coverage plateau


def test_exposures_far_away_fall_back_to_whole_table(w0855):
    e = V.exposures(w0855, near=(10.0, 10.0), radius_arcsec=10)
    assert len(e["mjd"]) == 439


def test_split_visits_on_fixture(w0855, kapteyn):
    for t in (w0855, kapteyn):
        assert V.split_visits(cols_of(t)["mjd"]).max() + 1 == 21


def test_synthetic_cadence_shape():
    c = V.synthetic_cadence(3, n_visits=12, per_visit=10)
    assert V.split_visits(c["mjd"]).max() + 1 == 12
    assert len(c["mjd"]) >= 120 and np.all(np.diff(c["mjd"]) >= 0)


def test_default_cadences_are_the_real_fixtures():
    cads = V.default_cadences()
    assert sorted(len(c["mjd"]) for c in cads) == [439, 860]


# ------------------------------------------------------------------ inject()
SPEC = {"ra": 133.80, "dec": -7.22, "pm": 3000.0, "pa": 45.0, "w2": 13.0, "plx": 200.0}


def test_inject_appends_rows_and_keeps_the_input(w0855):
    out = V.inject(w0855, [SPEC], np.random.default_rng(1))
    assert out.num_rows > w0855.num_rows
    assert out.slice(0, w0855.num_rows).equals(w0855.cast(out.schema))


def test_inject_keeps_schema(w0855):
    out = V.inject(w0855, [SPEC], np.random.default_rng(1))
    assert out.schema.names == w0855.schema.names
    assert [f.type for f in out.schema] == [f.type for f in w0855.schema]


def test_inject_copies_the_real_cadence(w0855):
    out = V.inject(w0855, [SPEC], np.random.default_rng(1))
    inj, real = cols_of(injected_part(w0855, out)), cols_of(w0855)
    frame_of = {m: (s, f) for m, s, f in zip(real["mjd"], real["scan_id"], real["frame_num"])}
    assert set(inj["mjd"]) <= set(real["mjd"])
    assert all(frame_of[m] == (s, f) for m, s, f in zip(inj["mjd"], inj["scan_id"], inj["frame_num"]))
    assert V.split_visits(inj["mjd"]).max() + 1 == 21
    # a bright mover is seen in almost every exposure that covered its position
    assert len(inj["mjd"]) > 0.9 * len(V.exposures(w0855, near=(SPEC["ra"], SPEC["dec"]))["mjd"])


def test_inject_columns_complete_and_consistent(w0855):
    out = V.inject(w0855, [dict(SPEC, w2=14.5, w1=15.5)], np.random.default_rng(2))
    inj = injected_part(w0855, out)
    c = cols_of(inj)
    for name in ("source_id", "ra", "dec", "sigra", "sigdec", "sigradec", "mjd", "w1mpro", "w1snr", "w2mpro",
                 "w2snr", "cc_flags", "ph_qual", "nb", "na", "qual_frame", "qi_fact", "saa_sep", "moon_masked",
                 "scan_id", "frame_num"):
        assert inj.column(name).null_count == 0, name
    assert set(c["cc_flags"]) == {"0000"} and set(c["moon_masked"]) == {"00"}
    assert set(c["qual_frame"]) == {10} and set(c["nb"]) == {1} and set(c["na"]) == {0}
    assert set(c["saa_sep"]) == {100.0} and set(c["qi_fact"]) == {1.0}
    for band, k in (("w1", 0), ("w2", 1)):
        snr = np.asarray(c[f"{band}snr"], float)
        sig = np.asarray(c[f"{band}sigmpro"], float)
        assert np.all(np.isnan(sig[snr < 2])) and np.all(np.isfinite(sig[snr >= 2]))
        assert np.allclose(sig[snr >= 2], 1.0857 / snr[snr >= 2], atol=2e-3)
        assert [q[k] for q in c["ph_qual"]] == list(V.ph_qual_letter(snr))
    comb = np.hypot(np.clip(c["w1snr"], 0, None), np.clip(c["w2snr"], 0, None))
    assert np.all(comb >= V.NOISE["detect_snr"] - 0.1)
    assert np.allclose(c["sigra"], V.NOISE["sig_ra_coeff"] / comb, rtol=0.03, atol=2e-4)
    assert np.allclose(c["sigradec"], V.NOISE["cov_frac"] * np.asarray(c["sigra"]), atol=2e-4)


def test_inject_source_ids_unique_and_formatted(w0855):
    out = V.inject(w0855, [SPEC, dict(SPEC, ra=133.78)], np.random.default_rng(3))
    ids = out.column("source_id").to_pylist()
    assert len(set(ids)) == len(ids)
    new = ids[w0855.num_rows:]
    assert all(re.fullmatch(r"\d{5}[a-z]\d{3}-9\d{5}", i) for i in new)
    c = cols_of(injected_part(w0855, out))
    assert all(i.startswith(f"{s}{f:03d}-") for i, s, f in zip(new, c["scan_id"], c["frame_num"]))


def test_inject_avoids_source_id_collisions():
    cad = V.synthetic_cadence(0, n_visits=3, per_visit=2, overlap_fraction=0)
    first = f"{cad['scan_id'][0]}{cad['frame_num'][0]:03d}-900000"
    base = V._to_table({"source_id": np.array([first], dtype=object), "ra": np.array([10.0]),
                        "dec": np.array([10.0]), "mjd": np.array([cad["mjd"][0]])}, V.SCHEMA)
    out = V.inject(base, [{"ra": 10.0, "dec": 10.0, "pm": 0.0, "w2": 10.0}], np.random.default_rng(0), cadence=cad)
    ids = out.column("source_id").to_pylist()
    assert len(set(ids)) == len(ids) == 1 + len(cad["mjd"])


def test_inject_is_deterministic_with_seed(w0855):
    a = V.inject(w0855, [SPEC], np.random.default_rng(42))
    b = V.inject(w0855, [SPEC], np.random.default_rng(42))
    c = V.inject(w0855, [SPEC], np.random.default_rng(43))
    assert a.equals(b)
    assert not a.equals(c)


def test_inject_noise_free_follows_the_line_exactly():
    cad = V.synthetic_cadence(1)
    spec = {"ra": 50.0, "dec": 20.0, "pmra": 4000.0, "pmdec": -2500.0, "w2": 12.0, "epoch": 2019.0}
    out = V.inject(V.SCHEMA.empty_table(), spec, None, cadence=cad, noise=False)
    c = cols_of(out)
    t = V.mjd_to_year(c["mjd"])
    dx, dy = V.tangent_offset(50.0, 20.0, c["ra"], c["dec"])
    assert np.allclose(dx, 4.0 * (t - 2019.0), atol=1e-3) and np.allclose(dy, -2.5 * (t - 2019.0), atol=1e-3)
    assert len(c["mjd"]) == len(cad["mjd"])


def test_inject_astrometric_noise_matches_model():
    cad = dense_cadence()
    rng = np.random.default_rng(7)
    for w2, w1 in ((10.0, 10.0), (13.5, 13.5), (14.3, 16.5)):
        out = V.inject(V.SCHEMA.empty_table(), {"ra": 30.0, "dec": 10.0, "pm": 0.0, "w2": w2, "w1": w1},
                       rng, cadence=cad)
        c = cols_of(out)
        dx, dy = V.tangent_offset(30.0, 10.0, c["ra"], c["dec"])
        sx, sy = V.true_sigma(w1, w2)
        assert np.std(dx) == pytest.approx(sx, rel=0.08), (w2, np.std(dx), sx)
        assert np.std(dy) == pytest.approx(sy, rel=0.08)
        assert abs(np.mean(dx)) < 4 * sx / math.sqrt(len(dx))
        # the catalogue's own sigra is smaller than the real scatter, as in the real data
        assert np.median(c["sigra"]) < np.std(dx)


def test_inject_photometric_noise_matches_model():
    cad = dense_cadence()
    out = V.inject(V.SCHEMA.empty_table(), {"ra": 30.0, "dec": 10.0, "pm": 0.0, "w2": 12.0, "w1": 12.5},
                   np.random.default_rng(8), cadence=cad)
    c = cols_of(out)
    s2 = np.asarray(c["w2snr"], float)
    assert np.mean(s2) == pytest.approx(float(V.snr_model(12.0, "w2")), abs=0.1)
    assert np.std(s2) == pytest.approx(1.0, abs=0.06)
    assert np.median(c["w2mpro"]) == pytest.approx(12.0, abs=0.01)
    assert np.std(c["w2mpro"]) == pytest.approx(1.0857 / V.snr_model(12.0, "w2"), rel=0.1)


def test_inject_detections_drop_below_snr5_at_the_w2_limit():
    cad = dense_cadence()
    rng = np.random.default_rng(9)
    frac = []
    for w2 in (13.0, 14.34, 15.5):
        out = V.inject(V.SCHEMA.empty_table(), {"ra": 30.0, "dec": 10.0, "pm": 0.0, "w2": w2, "w1": w2 + 3},
                       rng, cadence=cad)
        frac.append(np.mean(np.asarray(out.column("w2snr").to_numpy(), float) >= 5) * out.num_rows / len(cad["mjd"]))
    assert frac[0] > 0.97
    assert frac[1] == pytest.approx(0.45, abs=0.07)
    assert frac[2] < 0.1


def test_inject_report_counts_good_visits():
    cad = V.synthetic_cadence(2)
    rep = []
    V.inject(V.SCHEMA.empty_table(), [{"ra": 1.0, "dec": 2.0, "pm": 500.0, "w2": w2, "w1": w2 + 2}
                                      for w2 in (11.0, 14.5, 17.0)], np.random.default_rng(1), cadence=cad,
             report=rep)
    assert [r["n_visits_good"] for r in rep][0] == 21
    assert rep[0]["n_good"] >= rep[1]["n_good"] >= rep[2]["n_good"]
    assert rep[2]["n_visits_good"] == 0
    assert rep[0]["spec"]["epoch"] == pytest.approx(float(np.mean(V.mjd_to_year(cad["mjd"]))))


def test_inject_pm_and_pa_equal_pmra_pmdec():
    cad = V.synthetic_cadence(1)
    a = V.inject(V.SCHEMA.empty_table(), {"ra": 5.0, "dec": 5.0, "pm": 2000.0, "pa": 30.0, "w2": 12.0},
                 np.random.default_rng(1), cadence=cad)
    b = V.inject(V.SCHEMA.empty_table(), {"ra": 5.0, "dec": 5.0, "pmra": 1000.0, "pmdec": 2000.0 * math.cos(math.radians(30)),
                                          "w2": 12.0}, np.random.default_rng(1), cadence=cad)
    assert np.allclose(a.column("ra").to_numpy(), b.column("ra").to_numpy(), atol=1e-7)


def test_inject_across_ra_zero():
    cad = V.synthetic_cadence(1)
    out = V.inject(V.SCHEMA.empty_table(), {"ra": 359.9995, "dec": 1.0, "pmra": 10000.0, "pmdec": 0.0, "w2": 12.0,
                                            "epoch": 2014.2}, None, cadence=cad, noise=False)
    ra = out.column("ra").to_numpy()
    assert np.all((ra >= 0) & (ra < 360))
    assert ra.min() < 0.1 and ra.max() > 359.9
    c = cols_of(out)
    dx, _ = V.tangent_offset(359.9995, 1.0, c["ra"], c["dec"])
    assert np.allclose(dx, 10.0 * (V.mjd_to_year(c["mjd"]) - 2014.2), atol=1e-3)


def test_inject_next_to_the_pole():
    cad = V.synthetic_cadence(1)
    spec = {"ra": 123.0, "dec": 89.995, "pm": 10000.0, "pa": 90.0, "w2": 12.0, "epoch": 2019.0}
    out = V.inject(V.SCHEMA.empty_table(), spec, None, cadence=cad, noise=False)
    c = cols_of(out)
    t = V.mjd_to_year(c["mjd"])
    sep = V.sep_arcsec(c["ra"][0], c["dec"][0], c["ra"][-1], c["dec"][-1])
    assert sep == pytest.approx(10.0 * (t[-1] - t[0]), rel=1e-4)
    assert np.all(c["dec"] <= 90.0)


def test_inject_parallax_noise_free_matches_formula():
    cad = V.synthetic_cadence(4)
    spec = {"ra": 200.0, "dec": -30.0, "pm": 0.0, "w2": 12.0, "plx": 700.0, "epoch": 2019.0}
    out = V.inject(V.SCHEMA.empty_table(), spec, None, cadence=cad, noise=False)
    c = cols_of(out)
    fe, fn = V.parallax_factors(200.0, -30.0, c["mjd"])
    dx, dy = V.tangent_offset(200.0, -30.0, c["ra"], c["dec"])
    assert np.allclose(dx, 0.7 * fe, atol=1e-3) and np.allclose(dy, 0.7 * fn, atol=1e-3)


def test_parallax_wobble_with_the_real_wise_cadence(w0855):
    # WISE looks ~90 deg from the Sun, so visits 6 months apart see the star displaced by ~ +/- plx
    spec = {"ra": 133.79, "dec": -7.24, "pm": 0.0, "w2": 12.0, "plx": 500.0}
    out = V.inject(w0855, spec, None, noise=False)
    c = cols_of(injected_part(w0855, out))
    dx, dy = V.tangent_offset(133.79, -7.24, c["ra"], c["dec"])
    amp = np.hypot(dx, dy)
    assert 0.40 < np.median(amp) <= 0.5 + 1e-3


def test_inject_into_an_empty_table_needs_a_cadence():
    with pytest.raises(ValueError):
        V.inject(V.SCHEMA.empty_table(), SPEC, np.random.default_rng(0))


def test_inject_needs_position_columns(w0855):
    with pytest.raises(ValueError):
        V.inject(w0855.drop_columns(["mjd"]), SPEC, np.random.default_rng(0))


def test_inject_many_movers_adds_each(w0855):
    rep = []
    out = V.inject(w0855, [dict(SPEC, ra=133.78 + 0.005 * i) for i in range(4)], np.random.default_rng(5),
                   report=rep)
    assert out.num_rows - w0855.num_rows == sum(r["n_rows"] for r in rep)
    assert len(rep) == 4


def test_inject_promotes_non_nullable_columns_when_needed():
    cad = V.synthetic_cadence(0, n_visits=4, per_visit=3)
    strict = pa.schema([f.with_nullable(False) for f in V.SCHEMA])
    base = V._to_table(V._concat_cols([V._simulate({"ra": np.array([1.0]), "dec": np.array([1.0]),
                                                    "epoch": np.array([2019.0]), "pmra": np.zeros(1),
                                                    "pmdec": np.zeros(1), "plx": np.zeros(1),
                                                    "w1": np.array([10.0]), "w2": np.array([10.0])},
                                                   cad, np.random.default_rng(0))]) | {"source_id": np.array(
        [f"x{i}" for i in range(len(cad["mjd"]))], dtype=object)}, V.SCHEMA).cast(strict)
    out = V.inject(base, {"ra": 1.01, "dec": 1.0, "pm": 0.0, "w2": 14.5, "w1": 17.5}, np.random.default_rng(1),
                   cadence=cad)
    assert out.schema.field("w1sigmpro").nullable
    assert not out.schema.field("ra").nullable


def test_normalize_spec_defaults():
    s = V.normalize_spec({"ra": -10.0, "dec": 5.0, "pm": 1000.0, "pa": 90.0, "w2": 14.0, "w1w2": 1.5})
    assert s["ra"] == pytest.approx(350.0)
    assert s["pmra"] == pytest.approx(1000.0) and abs(s["pmdec"]) < 1e-9
    assert s["w1"] == pytest.approx(15.5) and s["plx"] == 0.0 and s["epoch"] == 2019.0
    assert s["pa"] == pytest.approx(90.0)
    with pytest.raises(ValueError):
        V.normalize_spec({"ra": 1.0, "dec": 1.0})
    with pytest.raises(ValueError):
        V.normalize_spec({"dec": 1.0, "w2": 10.0})


# ------------------------------------------------------------------ synthetic empty skies
@pytest.fixture(scope="module")
def sky():
    cad = V.default_cadences()[0]
    table, truth = V.empty_sky(np.random.default_rng(11), cad, (150.0, 30.0), 0.12, return_truth=True)
    return table, truth, cad


def test_empty_sky_schema_and_unique_ids(sky):
    table, _, _ = sky
    assert table.schema.names == V.COLUMNS
    ids = table.column("source_id").to_pylist()
    assert len(set(ids)) == len(ids)
    assert table.column("ra").null_count == 0 and table.column("mjd").null_count == 0


def test_empty_sky_source_counts_follow_the_model(sky):
    _, truth, _ = sky
    p = V.SKY_DEFAULTS
    lo, hi = p["w1_range"]
    expected = p["n15_per_deg2"] * (10 ** (p["alpha"] * (hi - 15)) - 10 ** (p["alpha"] * (lo - 15))) * truth["area_deg2"]
    assert abs(truth["n_stars"] - expected) < 4 * math.sqrt(expected)
    w1 = truth["stars"]["w1"]
    h1, h2 = np.sum((w1 >= 14) & (w1 < 15)), np.sum((w1 >= 16) & (w1 < 17))
    assert math.log10(h2 / h1) / 2 == pytest.approx(p["alpha"], abs=0.06)


def test_empty_sky_density_of_good_detections_is_realistic(sky):
    table, truth, cad = sky
    good = V.good_detection_mask(cols_of(table))
    per = good.sum() / truth["area_deg2"] / len(cad["mjd"])
    assert 1000 < per < 4000  # real fixtures: ~1000 (Kapteyn field) to ~2200 (WISE 0855 field) /deg^2/exposure


def test_empty_sky_stars_barely_move(sky):
    _, truth, _ = sky
    pm = np.hypot(truth["stars"]["pmra"], truth["stars"]["pmdec"])
    assert pm.max() <= V.SKY_DEFAULTS["star_pm_max"] + 1e-9 < 150.0


def test_empty_sky_uses_the_given_cadence(sky):
    table, truth, cad = sky
    assert set(np.unique(table.column("mjd").to_numpy())) <= set(cad["mjd"])
    sep = V.sep_arcsec(150.0, 30.0, table.column("ra").to_numpy(), table.column("dec").to_numpy())
    assert sep.max() <= truth["radius_deg"] * 3600 + 30  # sources are inside (spikes may poke out a little)


def test_empty_sky_transients_live_in_one_visit_each():
    cad = V.default_cadences()[0]
    table, truth = V.empty_sky(np.random.default_rng(3), cad, (40.0, -10.0), 0.2, return_truth=True,
                               n15_per_deg2=0.0, artefacts_per_deg2_per_exposure=0.0, transients_per_deg2=300.0)
    assert len(truth["transients"]) > 5 and table.num_rows > 0
    visits = V.split_visits(cad["mjd"])
    vis_of = dict(zip(cad["mjd"], visits))
    row_visits = {vis_of[m] for m in table.column("mjd").to_numpy()}
    assert row_visits <= {t["visit"] for t in truth["transients"]}
    # each object moves >= 1"/hour, so nothing sits still for a whole visit
    rates = [t["rate_arcsec_hr"] for t in truth["transients"]]
    assert min(rates) >= 1.0 and max(rates) <= 200.0


def test_empty_sky_artefacts_are_single_clean_detections():
    cad = V.synthetic_cadence(0)
    table, truth = V.empty_sky(np.random.default_rng(4), cad, (40.0, 40.0), 0.2, return_truth=True,
                               n15_per_deg2=0.0, transients_per_deg2=0.0, artefacts_per_deg2_per_exposure=200.0)
    expected = 200.0 * truth["area_deg2"] * len(cad["mjd"])
    assert abs(table.num_rows - expected) < 5 * math.sqrt(expected)
    c = cols_of(table)
    assert set(c["cc_flags"]) == {"0000"}
    snr_max = np.maximum(c["w1snr"], c["w2snr"])
    assert np.all(snr_max >= 5)


def test_empty_sky_diffraction_spikes_are_mostly_flagged():
    cad = V.synthetic_cadence(0)
    table, truth = V.empty_sky(np.random.default_rng(5), cad, (40.0, 40.0), 0.3, return_truth=True,
                               n15_per_deg2=3000.0, w1_range=(7.0, 9.0), transients_per_deg2=0.0,
                               artefacts_per_deg2_per_exposure=0.0)
    assert truth["n_bright"] > 0
    cc = np.array(table.column("cc_flags").to_pylist())
    spikes = cc == "DD00"
    frac_flagged = spikes.sum() / (spikes.sum() + np.sum((cc == "0000") & (np.asarray(table.column("w1mpro")) > 12.5)))
    assert frac_flagged == pytest.approx(1 - V.SKY_DEFAULTS["unflagged_spike_fraction"], abs=0.01)


def test_empty_sky_is_deterministic():
    cad = V.synthetic_cadence(0, n_visits=6)
    a = V.empty_sky(np.random.default_rng(9), cad, (10.0, 10.0), 0.05)
    b = V.empty_sky(np.random.default_rng(9), cad, (10.0, 10.0), 0.05)
    assert a.equals(b)


def test_empty_sky_density_parameter_scales_counts():
    cad = V.synthetic_cadence(0, n_visits=2)
    _, t1 = V.empty_sky(np.random.default_rng(1), cad, (10.0, 60.0), 0.2, return_truth=True)
    _, t5 = V.empty_sky(np.random.default_rng(1), cad, (10.0, 60.0), 0.2, return_truth=True, density=5.0)
    assert t5["n_stars"] / t1["n_stars"] == pytest.approx(5.0, rel=0.15)


# ------------------------------------------------------------------ reader
def test_year_labels():
    assert list(V.year_label([56639.0, 56639.0 + 365.3, 60000.0, 70000.0, 50000.0])) == \
        ["year1", "year2", "year10", "addendum", "year1"]


def test_table_reader_splits_by_year_and_loses_nothing(w0855):
    reader = V.table_reader(w0855, k5=10226)
    parts = [reader(10226, y) for y in V.YEAR_LABELS]
    assert sum(p.num_rows for p in parts if p is not None) == w0855.num_rows
    assert sum(p is not None for p in parts) >= 10
    assert reader(10226, "year99") is None
    assert reader(10227, "year5") is None  # another tile reads as missing
    mjd = np.concatenate([p.column("mjd").to_numpy() for p in parts if p is not None])
    assert np.array_equal(np.sort(mjd), np.sort(w0855.column("mjd").to_numpy()))


# ------------------------------------------------------------- a known star the data cannot show says why
def test_known_note_explains_a_star_the_table_cannot_hold():
    row = {"name": "61 Cygni A", "pm_found": None, "data": "survey tile 3325",
           "why_missed": "At W1 ≈ 2 it is far brighter than NEOWISE can measure"}
    note = V.known_note(row)
    assert note.startswith("No mover reported within 10″")
    assert note.endswith("At W1 ≈ 2 it is far brighter than NEOWISE can measure.")


def test_known_note_without_a_reason_is_unchanged():
    assert V.known_note({"pm_found": None}) == "No mover reported within 10″ of the star's predicted position."


def test_61_cygni_a_carries_its_reason():
    star = next(s for s in V.KNOWN_STARS if s["name"] == "61 Cygni A")
    assert "halo" in star["why_missed"] and "cc_flags" in star["why_missed"]
    assert all("why_missed" not in s for s in V.KNOWN_STARS if s["name"] != "61 Cygni A")
