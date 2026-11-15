"""Offline tests for pipeline/fetch.py's S3 fallback and its image selection: when IRSA's SIA or cutout service fails,
fetch.py finds the images in the S3 footprint index and reads the cutouts from the bucket (pipeline/spherex_s3.py).

IRSA is replaced by a function that always fails and the bucket by tests/_spherex_s3_fakes.FakeBucket: no network.
Run from the repository root:  .venv/bin/python -m pytest -q tests/test_fetch_s3.py
"""
import io
import json
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.io.votable import from_table
from astropy.table import Table
from astropy.wcs import WCS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402
import spherex_releases as sr  # noqa: E402
import spherex_s3 as s3  # noqa: E402
from _spherex_s3_fakes import FakeBucket, level2_key, make_level2  # noqa: E402

warnings.simplefilter("ignore")
REF = {"source": "test", "epoch": 2016.0, "ra": 10.0, "dec": 20.0, "pmra": 0.0, "pmdec": 0.0, "parallax": None}


def row(det, t, stem, release="dr1"):
    key = f"{release}/level2/W/p/{det}/{stem}.fits"
    return {"access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/" + key, "t_min": t, "t_max": t + 0.001,
            "energy_bandpassname": f"SPHEREx-D{det}", "obs_id": stem, "dataproduct_subtype": "science",
            "dataproduct_type": "image", "calib_level": 2, "em_min": 1e-6, "em_max": 2e-6,
            "obs_collection": f"spherex_{release}", "s_region": "",
            "cloud_access": json.dumps({"aws": {"bucket_name": "nasa-irsa-spherex", "key": key, "region": "us-east-1"}})}


def table(rows):
    t = fetch.sia_table(rows)
    t.sort(["energy_bandpassname", "t_min"])
    return t


def stems(t, idx):
    return [str(t[i]["obs_id"]) for i in idx]


@pytest.fixture(autouse=True)
def irsa_state(monkeypatch):
    monkeypatch.setattr(fetch, "IRSA_DOWN", {"sia": False, "cutout": False})
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)


def irsa_down(url, tries=6, timeout=120):
    raise RuntimeError(f"gave up on {url[:60]}")


# ---------------------------------------------------------------- image selection -------------------------------

def test_select_keeps_everything_under_the_cap():
    t = table([row(1, 61000 + i, f"a{i}") for i in range(10)])
    assert fetch.select_images(t, set(), max_images=12) == list(range(10))


def test_select_spreads_an_equal_share_per_detector_in_time():
    t = table([row(d, 61000 + i, f"d{d}_{i}") for d in range(1, 7) for i in range(30)])
    pick = fetch.select_images(t, set(), max_images=60)
    assert len(pick) == 60
    for d in range(1, 7):
        times = sorted(float(t[i]["t_min"]) for i in pick if t[i]["energy_bandpassname"] == f"SPHEREx-D{d}")
        assert len(times) == 10 and times[0] == 61000 and times[-1] == 61029


def test_select_gives_a_new_release_its_share_next_to_cached_images():
    # 30 DR1 images per detector, all on disk from an earlier fetch, then a QR3 pass of 15 more: the old rule filled
    # each detector's quota with cached DR1 images, so no QR3 image was ever chosen
    rows = [row(d, 61000 + i, f"dr1_{d}_{i}") for d in range(1, 7) for i in range(30)]
    rows += [row(d, 61300 + i, f"qr3_{d}_{i}", "qr3") for d in range(1, 7) for i in range(15)]
    t = table(rows)
    cached = {f"dr1_{d}_{i}" for d in range(1, 7) for i in range(30)}
    pick = fetch.select_images(t, cached, max_images=60)
    new = [s for s in stems(t, pick) if s.startswith("qr3")]
    assert all(s in stems(t, pick) for s in cached)                    # everything on disk is kept
    per_det = {d: sum(1 for s in new if s.startswith(f"qr3_{d}_")) for d in range(1, 7)}
    assert all(n >= 3 for n in per_det.values()), per_det             # about 10 * 15 / 45 per detector


def test_select_uses_a_cached_image_of_the_same_pass_instead_of_a_download():
    rows = [row(1, 61000 + i, f"x{i}") for i in range(40)]
    t = table(rows)
    cached = {"x1", "x15"}
    pick = fetch.select_images(t, cached, max_images=12)               # quota 2: picks x0 and x39
    assert stems(t, pick) == ["x1", "x15", "x39"]                      # x0 -> cached x1 (1 day away); x39 has none


def test_select_downloads_when_the_cached_image_is_from_another_pass():
    t = table([row(1, 61000 + i * 10, f"x{i}") for i in range(40)])   # one image every 10 days
    pick = fetch.select_images(t, {"x5"}, max_images=12)               # x0 is 50 days from x5: download it
    assert stems(t, pick) == ["x0", "x5", "x39"]


# ---------------------------------------------------------------- finding images ---------------------------------

def bucket_with_target(tmp_path, ra=10.0, dec=20.0):
    """A bucket with two QR3 weeks around (ra, dec) and an index of it in tmp_path/index."""
    b = FakeBucket()
    for week, obs, mjd in (("2026W33_1A", "2026W33_1A_0001_1", 61270.0), ("2026W34_1A", "2026W34_1A_0001_1", 61277.0)):
        for det in (1, 4):
            raw, _, _ = make_level2(nx=128, ny=128, ra=ra + (0.003 if det == 4 else 0), dec=dec, det=det, obs=obs,
                                    mjd=mjd, seed=det)
            b.put(level2_key("qr3", week, obs, det), raw)
    raw, _, _ = make_level2(nx=128, ny=128, ra=ra + 30, dec=dec, det=2, obs="2026W34_1A_0002_1", mjd=61277.1)
    b.put(level2_key("qr3", "2026W34_1A", "2026W34_1A_0002_1", 2), raw)          # elsewhere on the sky
    s3.build_index(b, "qr3", workers=2, root=tmp_path / "index", log=lambda m: None)
    return b


@pytest.fixture
def s3_world(tmp_path, monkeypatch):
    b = bucket_with_target(tmp_path)
    monkeypatch.setattr(s3, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(fetch, "_s3_reader", b)
    monkeypatch.setattr(fetch, "get", irsa_down)
    d = tmp_path / "cache" / "t1"
    d.mkdir(parents=True)
    return b, d


def test_sia_failure_falls_back_to_the_s3_index_and_says_so(s3_world):
    b, d = s3_world
    logs = []
    tb, how = fetch.find_images("spherex_qr3", REF, fetch.predict(REF, 2025.9), d, log=logs.append)
    assert how == "S3 index" and fetch.IRSA_DOWN["sia"]
    assert any("IRSA SIA failed" in m and "S3" in m for m in logs)
    assert sorted(str(x["obs_id"]) for x in tb) == ["2026W33_1A_0001_1", "2026W33_1A_0001_1",
                                                    "2026W34_1A_0001_1", "2026W34_1A_0001_1"]
    assert sorted(str(x["energy_bandpassname"]) for x in tb) == ["SPHEREx-D1"] * 2 + ["SPHEREx-D4"] * 2
    answer = json.loads((d / "spherex_qr3_s3.json").read_text())
    assert answer["index_complete"] and answer["release"] == "spherex_qr3" and len(answer["images"]) == 4
    assert not (d / "spherex_qr3_sia.xml").exists()


def test_the_s3_answer_counts_as_searched_for_the_release_bookkeeping(s3_world, tmp_path):
    b, d = s3_world
    fetch.find_images("spherex_qr3", REF, fetch.predict(REF, 2025.9), d, log=lambda m: None)
    (d / "spherex_sia.xml").write_text("<VOTABLE/>")
    assert sr.searched_releases(d.parent, ["t1"]) == {"t1": ["spherex_dr1", "spherex_qr3"]}


def test_after_one_sia_failure_later_targets_go_straight_to_s3(s3_world):
    b, d = s3_world
    calls = []
    fetch.IRSA_DOWN["sia"] = True
    real = fetch.get
    fetch.get = lambda *a, **k: calls.append(a) or real(*a, **k)
    try:
        logs = []
        _, how = fetch.find_images("spherex_qr3", REF, fetch.predict(REF, 2025.9), d, log=logs.append)
    finally:
        fetch.get = real
    assert how == "S3 index" and calls == [] and "failed earlier in this run" in logs[0]


def test_a_cached_sia_answer_is_still_used_when_irsa_is_down(s3_world):
    b, d = s3_world
    t = Table({"access_url": ["https://irsa/x.fits"], "t_min": [61000.0], "energy_bandpassname": ["SPHEREx-D1"],
               "obs_id": ["o1"], "dataproduct_subtype": ["science"]})
    from_table(t).to_xml(str(d / "spherex_sia.xml"))
    fetch.IRSA_DOWN["sia"] = True
    tb, how = fetch.find_images("spherex_dr1", REF, fetch.predict(REF, 2025.9), d, log=lambda m: None)
    assert how == "IRSA SIA" and list(tb["obs_id"]) == ["o1"]


def test_no_index_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(s3, "INDEX_DIR", tmp_path / "empty")
    monkeypatch.setattr(fetch, "get", irsa_down)
    with pytest.raises(RuntimeError, match="no S3 image index"):
        fetch.find_images("spherex_qr3", REF, fetch.predict(REF, 2025.9), tmp_path, log=lambda m: None)


def test_an_empty_search_still_stacks_with_irsa_rows(s3_world):
    from astropy.table import vstack
    b, d = s3_world
    far = dict(REF, ra=200.0, dec=-40.0)
    tb, how = fetch.find_images("spherex_qr3", far, fetch.predict(far, 2025.9), d, log=lambda m: None)
    assert len(tb) == 0 and how == "S3 index"
    assert json.loads((d / "spherex_qr3_s3.json").read_text())["images"] == []
    assert len(vstack([fetch.sia_table([row(1, 61000, "a")]), tb])) == 1


# ---------------------------------------------------------------- cutouts ----------------------------------------

def test_cutout_failure_at_irsa_reads_the_bucket_once_irsa_fails(s3_world):
    b, d = s3_world
    key = level2_key("qr3", "2026W33_1A", "2026W33_1A_0001_1", 1)
    r = s3.sia_like_rows([{"key": key, "obs_id": "o", "detector": 1, "mjd": 61270.0, "mjd_end": 61270.0,
                           "corners": [[0, 0]] * 8, "em_min": 1, "em_max": 2}], "qr3")[0]
    tried, logs = [], []
    fetch.get = lambda url, tries=6, timeout=120: tried.append((url, tries)) or irsa_down(url)
    c = fetch.predict(REF, 2026.6)
    one = fetch.get_cutout(r, c, 20, log=logs.append)
    two = fetch.get_cutout(r, c, 20, log=logs.append)
    assert one == two and fits.open(io.BytesIO(one))["IMAGE"].data.shape == (20, 20)
    assert len(tried) == 1 and "?center=" in tried[0][0] and len(logs) == 1 and "S3 bucket" in logs[0]


def test_rows_from_the_s3_index_never_ask_irsa(s3_world):
    b, d = s3_world
    key = level2_key("qr3", "2026W34_1A", "2026W34_1A_0001_1", 4)
    r = s3.sia_like_rows([{"key": key, "obs_id": "o", "detector": 4, "mjd": 61277.0, "mjd_end": 61277.0,
                           "corners": [[0, 0]] * 8, "em_min": 1, "em_max": 2}], "qr3")[0]
    fetch.get = lambda *a, **k: pytest.fail("IRSA was asked")
    assert fetch.get_cutout(r, fetch.predict(REF, 2026.6), 20, from_s3=True) is not None


def test_irsa_cutouts_get_two_tries_once_sia_failed(monkeypatch):
    tries = []
    monkeypatch.setattr(fetch, "get", lambda url, tries_=None, **k: tries.append(k.get("tries")) or irsa_down(url))
    fetch.IRSA_DOWN["sia"] = True
    r = row(1, 61000, "nokey")
    r["cloud_access"] = ""
    with pytest.raises(RuntimeError):
        fetch.get_cutout(r, fetch.predict(REF, 2026.0), 20, log=lambda m: None)
    assert tries == [2]


# ---------------------------------------------------------------- the whole fetch --------------------------------

def test_fetch_falls_back_to_s3_for_search_and_cutouts(s3_world, tmp_path, monkeypatch, capsys):
    b, d = s3_world
    tid = "t1"
    (d / "gaia.json").write_text(json.dumps({"ref": REF, "field_stars": []}))
    # AllWISE already cached (fetch.py skips it), NEOWISE stubbed out
    from_table(Table({"energy_bandpassname": ["W1"], "dataproduct_subtype": ["science"],
                      "access_url": ["https://irsa/w1"]})).to_xml(str(d / "allwise_sia.xml"))
    for band in ("W1", "W2"):
        (d / f"allwise_{band}.fits").write_bytes(b"cached")
    monkeypatch.setitem(sys.modules, "neowise", types.SimpleNamespace(run=lambda tid: None))
    monkeypatch.setitem(fetch.TARGETS, tid, {"name": "Test target", "fov_arcsec": 60})
    monkeypatch.setattr(fetch, "CACHE", d.parent)
    monkeypatch.setattr(fetch, "RELEASES", ["spherex_dr1", "spherex_qr3"])
    fetch.fetch(tid)
    out = capsys.readouterr().out
    assert "spherex_dr1: not available" in out                      # no DR1 answer cached and no DR1 index here
    assert "IRSA SIA failed" in out and "spherex_qr3: 4 images (S3 index)" in out
    files = sorted(p.name for p in (d / "spherex").glob("*.fits"))
    assert len(files) == 4 and all(f.startswith("level2_2026W3") for f in files)
    size = int(60 / fetch.SPX_PIX) + 4
    for f in (d / "spherex").glob("*.fits"):
        hd = fits.open(f)
        assert [h.name for h in hd] == ["PRIMARY", "IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE"]
        assert hd["IMAGE"].data.shape == (size, size)
        px, py = WCS(s3.sky_header(hd["IMAGE"].header)).all_world2pix(10.0, 20.0, 0)
        assert size // 2 - 1 <= px < size // 2 and size // 2 - 1 <= py < size // 2
    assert not list((d / "spherex").glob("*.part"))
    # a second run downloads nothing
    n = b.requests
    fetch.fetch(tid)
    assert b.requests - n <= 2                                          # only the week listing for the answer
