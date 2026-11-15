"""Tests for the six-detector combination and the per-frame contamination metadata in pipeline/analyze.py.

    python -m pytest -q tests/test_combined_quality.py

Synthetic images and FLAGS planes (no network, no downloads); the last group reads the committed app/data/ targets
and is skipped when they are not there.
"""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

fits = pytest.importorskip("astropy.io.fits")
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"


@pytest.fixture(scope="module")
def A():
    spec = importlib.util.spec_from_file_location("wanderers_analyze_cq", ROOT / "pipeline" / "analyze.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as exc:                       # pipeline requirements not installed
        pytest.skip(f"pipeline dependencies missing: {exc}")
    return mod


# A FLAGS extension like SPHEREx's: MSKNnnnn name, MSKMnnnn bitmask, MSKDnnnn description.
PLANES = {"TRANSIENT": 0, "OVERFLOW": 1, "NONFUNC": 6, "HOT": 10, "FULLSAMPLE": 12, "OUTLIER": 19, "SOURCE": 21, "HALO": 28}


def flags_hdu(data, planes=PLANES, describe=True):
    hdu = fits.ImageHDU(np.asarray(data, dtype=np.int32), name="FLAGS")
    for name, bit in planes.items():
        hdu.header[f"MSKN{bit:04d}"] = name
        hdu.header[f"MSKM{bit:04d}"] = 1 << bit
        if describe:
            hdu.header[f"MSKD{bit:04d}"] = f"meaning of {name.lower()}"
    return hdu


def bit(name):
    return 1 << PLANES[name]


def clean(n=21):
    return np.zeros((n, n), dtype=np.int32), np.ones((n, n))


C = 10.0          # target position in a 21 x 21 cut-out


# ---------- robust_scale and combine_detectors ----------
def noise_img(seed, shape=(60, 60), bg=0.0, sigma=1.0):
    return bg + sigma * np.random.default_rng(seed).standard_normal(shape)


def test_robust_scale_is_median_and_mad(A):
    img = noise_img(1, bg=5.0, sigma=2.0)
    bg, nz = A.robust_scale(img)
    assert bg == pytest.approx(5.0, abs=0.15)
    assert nz == pytest.approx(2.0, rel=0.1)


def test_robust_scale_refuses_flat_or_tiny_images(A):
    assert A.robust_scale(np.ones((30, 30))) is None           # no spread to divide by
    assert A.robust_scale(np.full((30, 30), np.nan)) is None    # nothing finite
    assert A.robust_scale(np.arange(10.0)) is None              # too few pixels


def test_each_detector_is_normalised_so_units_and_sky_level_do_not_matter(A):
    a, b = noise_img(2), noise_img(3)
    ref, _ = A.combine_detectors({1: a, 2: b})
    scaled, used = A.combine_detectors({1: a, 2: 1000.0 * b + 500.0})   # same picture, other units and sky level
    np.testing.assert_allclose(scaled, ref, atol=1e-9)
    assert [d for d, _, _ in used] == [1, 2]


def test_a_noisy_long_wavelength_detector_does_not_dominate(A):
    imgs = {d: noise_img(10 + d) for d in range(1, 6)}
    imgs[6] = noise_img(16, bg=50.0, sigma=40.0)                # bright, noisy sky at the long end
    comb, used = A.combine_detectors(imgs)
    z6 = (imgs[6] - used[-1][1]) / used[-1][2]
    assert np.corrcoef(comb.ravel(), z6.ravel())[0, 1] < 0.6     # one of six, not the whole picture
    assert A.robust_scale(comb)[1] == pytest.approx(1.0, rel=0.15)   # the result is in units of the noise


def test_a_source_seen_by_every_detector_gains_signal_to_noise(A):
    yy, xx = np.indices((60, 60))
    star = 6.0 * np.exp(-((xx - 30) ** 2 + (yy - 30) ** 2) / 4.0)      # 6 sigma peak in each detector
    imgs = {d: noise_img(20 + d) + star for d in range(1, 7)}
    comb, _ = A.combine_detectors(imgs)
    single = max(A.detection_snr(imgs[d], 30, 30) for d in imgs)
    assert A.detection_snr(comb, 30, 30) > 1.5 * single


def test_blank_pixels_use_the_detectors_that_have_a_value(A):
    a, b, c = noise_img(30), noise_img(31), noise_img(32)
    a[5, 5] = np.nan
    a[7, 7] = b[7, 7] = c[7, 7] = np.nan
    comb, used = A.combine_detectors({1: a, 2: b, 3: c})
    z = {d: (img - bg) / nz for (d, bg, nz), img in zip(used, (a, b, c))}
    assert comb[5, 5] == pytest.approx((z[2][5, 5] + z[3][5, 5]) / np.sqrt(2))
    assert comb[6, 6] == pytest.approx((z[1][6, 6] + z[2][6, 6] + z[3][6, 6]) / np.sqrt(3))
    assert np.isnan(comb[7, 7])                                   # blank in every detector stays blank


def test_a_detector_missing_from_a_visit_is_left_out(A):
    comb, used = A.combine_detectors({1: noise_img(40), 2: None, 3: noise_img(41), 6: noise_img(42)})
    assert comb is not None
    assert [d for d, _, _ in used] == [1, 3, 6]


def test_fewer_detectors_than_the_minimum_give_no_picture(A):
    comb, used = A.combine_detectors({4: noise_img(50), 5: None})
    assert comb is None and [d for d, _, _ in used] == [4]
    comb, used = A.combine_detectors({4: noise_img(50), 5: np.ones((60, 60))})   # a flat image cannot be normalised
    assert comb is None
    one, _ = A.combine_detectors({4: noise_img(50)}, min_detectors=1)
    assert one is not None


def sel_entry(det, year, lam=2.0, mjd=60800.0, q=None):
    return {"det": det, "year": year, "lam": lam, "mjd": mjd, "q": q or {}}


def test_build_combined_frame_structure(A):
    frames = {1: {"img": noise_img(60), "_sel": [sel_entry(1, 2025.3), sel_entry(1, 2025.31)]},
              3: {"img": noise_img(61), "_sel": [sel_entry(3, 2025.32)]},
              5: {"img": None, "_sel": [sel_entry(5, 2025.33)]}}             # no picture: not counted
    f = A.build_combined(frames)
    assert f["mission"] == "SPHEREx" and f["detectors"] == [1, 3]
    assert f["n_images"] == 3 and f["year"] == pytest.approx(2025.31)
    assert f["label"].startswith("SPHEREx ") and f["png"] is None
    assert [n["det"] for n in f["normalisation"]] == [1, 3] and f["normalisation"][0]["n_images"] == 2
    assert all(n["noise"] > 0 for n in f["normalisation"])
    assert set(f["_parts"]) == {1, 3}
    assert A.build_combined({2: frames[1]}) is None                  # one detector is not a combination


def test_combined_channel_label_and_bands(A):
    assert A.COMBINED == "all"
    assert A.COMBINED_LABEL == "All 6 detectors combined (0.75–5.0 µm)"
    assert sorted(A.DETECTOR_BANDS) == [1, 2, 3, 4, 5, 6]
    assert A.DETECTOR_BANDS[1][0] == 0.75 and A.DETECTOR_BANDS[6][1] == 5.0
    los = [A.DETECTOR_BANDS[k][0] for k in range(1, 7)]
    assert los == sorted(los)


# ---------- flag planes from the header ----------
def test_flag_planes_reads_names_bits_and_meanings(A):
    p = A.flag_planes(flags_hdu(np.zeros((3, 3))))
    assert p["OVERFLOW"] == (2, "meaning of overflow")
    assert p["HALO"][0] == 1 << 28


def test_flag_planes_without_descriptions_or_bitmask(A):
    hdu = flags_hdu(np.zeros((3, 3)), describe=False)
    hdu.header["MSKN0030"] = "ORPHAN"                              # no MSKM0030: not a usable plane
    p = A.flag_planes(hdu)
    assert p["HOT"] == (1 << 10, "") and "ORPHAN" not in p


# ---------- one image: saturation, bad pixels, verdict ----------
def test_clean_image_is_good(A):
    d, img = clean()
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["quality"] == "good" and q["aperture_px"] == 29
    assert (q["bad_px_aperture"], q["flagged_px_aperture"], q["saturated"]) == (0, 0, False)
    assert q["flags_aperture"] == [] and q["flags_target_pixel"] == []


def test_overflow_at_the_target_pixel_is_saturated_and_poor(A):
    d, img = clean()
    d[10, 10] = bit("OVERFLOW") | bit("TRANSIENT")
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["saturated"] is True and q["quality"] == "poor"
    assert q["flags_target_pixel"] == ["TRANSIENT", "OVERFLOW"]
    assert "saturated" in q["quality_reason"]


def test_overflow_next_to_the_target_is_not_saturation_at_the_target(A):
    d, img = clean()
    d[10, 12] = bit("OVERFLOW")
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["saturated"] is False and q["quality"] == "caution"
    assert q["bad_px_aperture"] == 1 and "OVERFLOW" in q["flags_aperture"]


def test_target_pixel_rounds_to_the_nearest_pixel(A):
    d, img = clean()
    d[10, 10] = bit("OVERFLOW")
    assert A.image_quality(flags_hdu(d), img, 10.4, 9.6)["saturated"] is True
    assert A.image_quality(flags_hdu(d), img, 10.6, 10.0)["saturated"] is False


def test_blank_target_pixel_is_poor(A):
    d, img = clean()
    img[10, 10] = np.nan
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["target_blank"] is True and q["quality"] == "poor" and q["bad_px_aperture"] == 1


def test_a_bad_flag_at_the_target_pixel_is_named(A):
    d, img = clean()
    d[10, 10] = bit("HOT")
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["quality"] == "poor" and "HOT" in q["quality_reason"]


def test_flags_outside_the_bad_set_are_counted_but_do_not_lower_the_verdict(A):
    d, img = clean()
    d[9, 10] = bit("OUTLIER")
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["quality"] == "good" and q["flagged_px_aperture"] == 1 and q["bad_px_aperture"] == 0
    assert q["flags_aperture"] == ["OUTLIER"]


def test_informational_planes_are_not_flags(A):
    d, img = clean()
    d[10, 10] = bit("SOURCE") | bit("FULLSAMPLE")
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["flags_target_pixel"] == [] and q["flags_aperture"] == [] and q["flagged_px_aperture"] == 0
    assert q["quality"] == "good"


def test_pixels_outside_the_aperture_do_not_count(A):
    d, img = clean()
    d[10, 14] = bit("HOT")                     # 4 pixels away, outside the 3-pixel aperture
    img[0, 0] = np.nan
    q = A.image_quality(flags_hdu(d), img, C, C)
    assert q["bad_px_aperture"] == 0 and q["quality"] == "good"


def test_target_outside_the_cutout_is_poor(A):
    d, img = clean()
    q = A.image_quality(flags_hdu(d), img, -6.0, 30.0)
    assert q["target_in_image"] is False and q["quality"] == "poor" and q["aperture_px"] == 0


def test_no_overflow_plane_means_never_saturated(A):
    d, img = clean()
    d[10, 10] = 0b10
    planes = {k: v for k, v in PLANES.items() if k != "OVERFLOW"}
    q = A.image_quality(flags_hdu(d, planes), img, C, C)
    assert q["saturated"] is False and q["flags_target_pixel"] == []


def test_bad_pixel_count_matches_what_photometry_leaves_out(A):
    rng = np.random.default_rng(7)
    for _ in range(20):
        d = rng.choice([0, bit("HOT"), bit("OUTLIER"), bit("SOURCE"), bit("TRANSIENT")], size=(21, 21), p=[.8, .05, .05, .05, .05]).astype(np.int32)
        img = rng.normal(size=(21, 21)); img[rng.random((21, 21)) < .03] = np.nan
        x, y = rng.uniform(7, 13, 2)
        hdu = flags_hdu(d)
        q = A.image_quality(hdu, img, x, y)
        _, nbad = A.photometry(img, A.bad_mask(hdu), x, y)
        assert q["bad_px_aperture"] == nbad
        assert q["flags_aperture"] == A.flags_at(hdu, x, y)


def test_quality_check_keeps_the_pipeline_qa_outcome(A):
    d, img = clean()
    assert A.image_quality(flags_hdu(d), img, C, C, dqa="Pass")["dqa"] == "Pass"
    assert A.image_quality(flags_hdu(d), img, C, C)["dqa"] is None


def test_flag_legend_counts_images_per_flag(A):
    d1, img = clean(); d1[10, 10] = bit("OVERFLOW"); d1[10, 11] = bit("HALO")
    d2, _ = clean(); d2[11, 10] = bit("HALO")
    spx = []
    for d in (d1, d2):
        h = flags_hdu(d)
        spx.append({"planes": A.flag_planes(h), "q": A.image_quality(h, img, C, C)})
    L = {r["name"]: r for r in A.flag_legend(spx)}
    assert L["HALO"]["images_aperture"] == 2 and L["HALO"]["images_target_pixel"] == 0
    assert L["OVERFLOW"]["images_target_pixel"] == 1 and L["OVERFLOW"]["bit"] == 1
    assert L["OVERFLOW"]["bad"] and not L["OUTLIER"]["bad"] and L["SOURCE"]["informational"]
    assert L["HOT"]["hidden_in_pictures"] and not L["HALO"]["hidden_in_pictures"]
    assert L["OVERFLOW"]["description"] == "meaning of overflow"
    assert [r["bit"] for r in A.flag_legend(spx)] == sorted(r["bit"] for r in A.flag_legend(spx))


# ---------- stacked frames ----------
def q_of(verdict="good", sat=False, bad=0, dqa="Pass", aperture=(), pixel=(), blank=False):
    return {"quality": verdict, "quality_reason": f"image is {verdict}", "saturated": sat, "bad_px_aperture": bad,
            "aperture_px": 29, "dqa": dqa, "flags_aperture": list(aperture), "flags_target_pixel": list(pixel),
            "target_blank": blank, "target_in_image": True}


def test_no_images_is_poor(A):
    assert A.stack_quality([])["verdict"] == "poor"


def test_one_image_takes_its_own_verdict(A):
    r = A.stack_quality([q_of("caution", bad=3)])
    assert (r["verdict"], r["reason"]) == ("caution", "image is caution")


def test_half_the_images_unusable_is_poor(A):
    r = A.stack_quality([q_of("poor", pixel=["HOT"]), q_of(), q_of("poor", sat=True), q_of()])
    assert r["verdict"] == "poor" and "2 of 4 images are unusable" in r["reason"]
    assert "1 saturated" in r["reason"] and "1 flagged" in r["reason"]


def test_one_saturated_image_is_enough_for_caution(A):
    r = A.stack_quality([q_of("poor", sat=True, pixel=["OVERFLOW"])] + [q_of()] * 7)
    assert r["verdict"] == "caution" and "saturated" in r["reason"] and r["n_saturated"] == 1


def test_a_quarter_unusable_is_caution_less_is_good(A):
    assert A.stack_quality([q_of("poor", pixel=["HOT"])] + [q_of()] * 3)["verdict"] == "caution"
    r = A.stack_quality([q_of("poor", pixel=["HOT"])] + [q_of()] * 4)
    assert r["verdict"] == "good" and "fewer than a quarter" in r["reason"]


def test_half_with_flagged_pixels_nearby_is_caution(A):
    r = A.stack_quality([q_of("caution", bad=2), q_of("caution", bad=1), q_of(), q_of()])
    assert r["verdict"] == "caution" and "within 3 pixels" in r["reason"]
    r = A.stack_quality([q_of("caution", bad=2), q_of(), q_of(), q_of()])
    assert r["verdict"] == "good" and "nearby" in r["reason"]


def test_failed_pipeline_check_is_caution(A):
    r = A.stack_quality([q_of(dqa="Fail"), q_of(), q_of()])
    assert r["verdict"] == "caution" and "L2DQAFLG" in r["reason"] and r["n_dqa_fail"] == 1


def test_blank_stacked_picture_is_poor(A):
    r = A.stack_quality([q_of(), q_of()], blank_at_target=True)
    assert r["verdict"] == "poor" and r["reason"] == "The stacked picture is blank at the target."
    off = dict(q_of("poor"), target_in_image=False, aperture_px=0)
    assert A.stack_quality([off], blank_at_target=True)["reason"] == "The target falls outside this image."
    assert A.stack_quality([off, off], blank_at_target=True)["reason"] == "The target falls outside all 2 images."


def test_stack_counts(A):
    r = A.stack_quality([q_of("poor", sat=True, bad=4, aperture=["OVERFLOW", "HALO"], pixel=["OVERFLOW"]),
                         q_of("caution", bad=1, aperture=["HALO"]), q_of(), q_of(), q_of()])
    assert r["flag_counts"] == {"OVERFLOW": 1, "HALO": 2} and r["pixel_flag_counts"] == {"OVERFLOW": 1}
    assert (r["bad_px_worst"], r["images_with_bad_px"], r["n_poor"], r["aperture_px"]) == (4, 2, 1, 29)
    assert r["flags_checked"] is True


def test_clean_stack_says_so(A):
    r = A.stack_quality([q_of()] * 6)
    assert r["verdict"] == "good" and "any of the 6 images" in r["reason"]


# ---------- the combined frame ----------
def dq(v):
    return {"verdict": v}


def test_combined_poor_when_half_the_detectors_are_poor(A):
    r = A.combined_quality({1: dq("poor"), 2: dq("poor"), 3: dq("poor"), 4: dq("good"), 5: dq("good"), 6: dq("good")}, [q_of()] * 6)
    assert r["verdict"] == "poor" and "D1, D2, D3" in r["reason"]


def test_combined_caution_names_the_poor_detector(A):
    r = A.combined_quality({1: dq("good"), 3: dq("poor"), 4: dq("caution"), 6: dq("good")}, [q_of()] * 8)
    assert r["verdict"] == "caution" and "D3" in r["reason"] and "D4" in r["reason"]
    assert r["detector_verdicts"] == {"1": "good", "3": "poor", "4": "caution", "6": "good"}


def test_combined_good_with_a_minority_needing_caution(A):
    r = A.combined_quality({d: dq("caution" if d == 5 else "good") for d in range(1, 7)}, [q_of()] * 12)
    assert r["verdict"] == "good" and "D5" in r["reason"]
    r = A.combined_quality({d: dq("caution" if d <= 3 else "good") for d in range(1, 7)}, [q_of()] * 12)
    assert r["verdict"] == "caution"
    assert A.combined_quality({d: dq("good") for d in range(1, 7)}, [q_of()] * 12)["reason"] == "All 6 detector co-adds are good at the target."


def test_combined_saturation_is_caution(A):
    r = A.combined_quality({d: dq("good") for d in range(1, 7)}, [q_of("poor", sat=True)] + [q_of()] * 11)
    assert r["verdict"] == "caution" and "saturated" in r["reason"]


# ---------- WISE and NEOWISE frames ----------
def test_wise_frame_checks_blank_pixels_only(A):
    img = np.ones((40, 40))
    r = A.wise_quality(img, 20, 20)
    assert r["verdict"] == "good" and r["flags_checked"] is False and "only blank pixels" in r["reason"]
    img[20, 22] = np.nan
    assert A.wise_quality(img, 20, 20)["verdict"] == "caution"
    img[20, 20] = np.nan
    assert A.wise_quality(img, 20, 20)["verdict"] == "poor"
    assert A.wise_quality(np.ones((40, 40)), 80, 20)["verdict"] == "poor"


def test_wise_saturated_core_is_poor_and_explained(A):
    r = A.wise_quality(np.ones((40, 40)), 20, 20, saturated_core=True)
    assert r["verdict"] == "poor" and r["n_saturated"] == 1 and "centre of the blank hole" in r["reason"]


# ---------- observation metadata ----------
def test_single_detector_metadata(A):
    sel = [sel_entry(6, 2025.34, lam=4.62, mjd=60800.70), sel_entry(6, 2025.35, lam=4.98, mjd=60805.25)]
    o = A.spherex_obs(sel)
    assert o["mission"] == "SPHEREx" and o["detectors"] == [6] and o["band_um"] == [4.42, 5.0]
    assert o["instrument"] == "SPHEREx detector D6 (MWIR array)"
    assert o["lam_um"] == [4.62, 4.98]
    assert o["start"] == "2025-05-05 16:48" and o["end"] == "2025-05-10 06:00"


def test_several_detectors_metadata(A):
    o = A.spherex_obs([sel_entry(1, 2025.3, lam=np.nan), sel_entry(4, 2025.3, lam=np.nan)])
    assert o["detectors"] == [1, 4] and o["band_um"] == [0.75, 3.82] and o["lam_um"] is None
    assert o["instrument"] == "SPHEREx detectors D1, D4"
    assert A.spherex_obs([sel_entry(2, 2025.3)])["instrument"].endswith("(SWIR array)")


def test_saved_frames_drop_pictures_and_internal_keys(A):
    f = {"year": 2025.0, "png": "a.png", "img": np.ones(3), "_sel": [1], "_parts": {}, "quality": {"verdict": "good"}}
    assert A.public(f) == {"year": 2025.0, "png": "a.png", "quality": {"verdict": "good"}}


def test_quality_rules_cover_every_kind_of_frame(A):
    text = " ".join(A.QUALITY_RULES)
    for word in ("OVERFLOW", "half", "quarter", "combined", "WISE", "L2DQAFLG"):
        assert word in text


# ---------- the regenerated targets in app/data ----------
def targets():
    idx = DATA / "index.json"
    return [e["id"] for e in json.loads(idx.read_text())] if idx.exists() else []


def load(tid):
    return json.loads((DATA / tid / "target.json").read_text())


real = pytest.mark.skipif(not targets(), reason="app/data not present")
VERDICTS = {"good", "caution", "poor"}


@real
@pytest.mark.parametrize("tid", targets())
def test_every_frame_has_observation_metadata_and_a_verdict(tid):
    t = load(tid)
    assert "all" in t["frames"] and t["channels"]["all"] == "All 6 detectors combined (0.75–5.0 µm)"
    for ch, frames in t["frames"].items():
        for f in frames:
            o, q = f["obs"], f["quality"]
            assert o["mission"] == f["mission"] and o["instrument"], (ch, f["label"])
            assert o["start"] and o["end"] and o["start"] <= o["end"], (ch, f["label"])
            assert q["verdict"] in VERDICTS and q["reason"].endswith((".", ")")), (ch, f["label"])
            assert isinstance(q["n_saturated"], int) and isinstance(q["bad_px_worst"], int)
            assert q["aperture_px"] > 0 or q["verdict"] == "poor", (ch, f["label"])   # 0: the target is off the image
            if f["mission"] == "SPHEREx":
                assert q["flags_checked"] is True and o["detectors"] and o["lam_um"], (ch, f["label"])
                assert q["n_saturated"] <= f["n_images"] and q["images_with_bad_px"] <= f["n_images"]
                assert all(0 < n <= f["n_images"] for n in q["flag_counts"].values())
            else:
                assert q["flags_checked"] is False and o["detectors"] is None


@real
@pytest.mark.parametrize("tid", targets())
def test_combined_frames_add_up_the_detector_coadds(tid):
    t = load(tid)
    for f in t["frames"]["all"]:
        v = int(f["png"].split("_v")[1].split(".")[0])
        parts = {int(ch[1]): fr for ch in ("d1", "d2", "d3", "d4", "d5", "d6") for fr in t["frames"].get(ch, [])
                 if fr["png"] == f"{ch}_spherex_v{v}.png"}
        assert f["detectors"] == sorted(parts) and len(parts) >= 2
        assert f["n_images"] == sum(p["n_images"] for p in parts.values())
        assert [n["det"] for n in f["normalisation"]] == f["detectors"]
        assert set(f["quality"]["detector_verdicts"]) == {str(d) for d in f["detectors"]}
        assert {str(d): p["quality"]["verdict"] for d, p in parts.items()} == f["quality"]["detector_verdicts"]
        assert isinstance(f["detected"], bool) and f["snr"] >= 0
        for name in (f["png"], t["diff"]["all"]):
            assert name and (DATA / tid / name).exists()
        assert f["png"] in t["ghosts"]


@real
@pytest.mark.parametrize("tid", targets())
def test_image_rows_carry_the_contamination_fields(tid):
    t = load(tid)
    legend = {r["name"]: r for r in t["flag_legend"]}
    for m in t["metadata"]:
        assert m["quality"] in VERDICTS and m["quality_reason"]
        assert m["used_in_spectrum"] == (m["bad_px_aperture"] == 0)
        assert m["saturated"] == ("OVERFLOW" in m["flags_target_pixel"])
        assert m["bad_px_aperture"] <= m["aperture_px"] and m["flagged_px_aperture"] <= m["aperture_px"]
        assert set(m["flags_target_pixel"]) <= set(m["flags_at_target"])
        for name in m["flags_at_target"]:
            assert legend[name]["description"], name
        if m["saturated"]:
            assert m["quality"] == "poor"


@real
@pytest.mark.parametrize("tid", targets())
def test_motion_is_still_measured_at_34_and_46_um_only(tid):
    t = load(tid)
    assert {p["ch"] for p in t["track"]} <= {"w1", "w2"}
    assert set(t["stacks"]) == {"w1", "w2"}


@real
def test_barnard_shows_its_saturation():
    t = load("barnard")                        # bright enough to overflow SPHEREx pixels in nearly every image
    for ch in ("w2", "w1", "all", "d1", "d6"):
        spx = [f for f in t["frames"][ch] if f["mission"] == "SPHEREx"]
        assert spx and all(f["quality"]["verdict"] == "poor" for f in spx), ch
    assert sum(f["quality"]["n_saturated"] > 0 for f in t["frames"]["w2"] if f["mission"] == "SPHEREx") >= 7
    assert sum(m["saturated"] for m in t["metadata"]) > len(t["metadata"]) / 2
    assert "saturated" in t["frames"]["all"][0]["quality"]["reason"] or "poor" in t["frames"]["all"][0]["quality"]["reason"]
