"""Offline tests for pipeline/spherex_s3.py: the bucket listing, the footprint index built from FITS headers read with
Range requests, footprint tests (RA wrap, poles), the epoch-propagated search and the Range-request cutouts.

Every file is synthetic (tests/_spherex_s3_fakes.py) and every read goes through a fake bucket: no network.
Run from the repository root:  .venv/bin/python -m pytest -q tests/test_spherex_s3.py
"""
import io
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import spherex_s3 as s3  # noqa: E402
from _spherex_s3_fakes import FakeBucket, level2_key, make_level2  # noqa: E402

warnings.simplefilter("ignore")
WEEK = "2026W33_1A"


def put(bucket, release="qr3", week=WEEK, obs="2026W33_1A_0001_1", det=1, proc="l2b-v27-2026-300", **kw):
    raw, h, data = make_level2(det=det, obs=obs, **kw)
    k = level2_key(release, week, obs, det, proc)
    bucket.put(k, raw)
    return k, h, data


def exposure(bucket, obs, ra, dec, mjd, week=WEEK, dets=(1, 4), flags="all_sky", shift_deg=0.0, **kw):
    """One exposure: the given detectors, partners (4-6) offset by shift_deg in RA like the dichroic pairs."""
    keys = {}
    for d in dets:
        dra = shift_deg if d > 3 else 0.0
        keys[d] = put(bucket, week=week, obs=obs, det=d, ra=ra + dra, dec=dec, mjd=mjd, flags=flags, **kw)[0]
    return keys


# ---------------------------------------------------------------- listing ---------------------------------------

def test_release_folders_keep_release_names_only_oldest_first():
    b = FakeBucket({"qr3/level2/x": b"1", "dr1/level2/x": b"1", "qr2/level2/x": b"1", "index.html": b"<html>",
                    "docs/readme": b"1", "dr10/level2/x": b"1"})
    assert s3.release_folders(b) == ["dr1", "dr10", "qr2", "qr3"]


def test_week_folders_sorted_by_year_week_half_and_letter():
    b = FakeBucket({f"qr3/level2/{w}/p/1/f.fits": b"1" for w in
                    ("2026W40_2A", "2026W24_2B", "2026W24_1A", "2025W52_2A", "2026W24_2A", "notaweek")})
    assert s3.week_folders(b, "qr3") == ["2025W52_2A", "2026W24_1A", "2026W24_2A", "2026W24_2B", "2026W40_2A"]


def test_week_label_and_iso_week_end():
    assert s3.week_label("2026W40_2A") == "2026 week 40"
    assert s3.week_end("2026W40_2A") == "2026-10-04"            # ISO week 40 of 2026: Sep 28 - Oct 4
    assert s3.week_end("2025W33_2C") == "2025-08-17"


def test_newest_weeks_skips_a_release_without_level2():
    b = FakeBucket({"qr3/level2/2026W20_2A/p/1/a.fits": b"1", "qr3/level2/2026W40_2A/p/1/a.fits": b"1",
                    "dr1/level2/2026W20_1A/p/1/a.fits": b"1", "qr9/other/x": b"1"})
    assert s3.newest_weeks(b, ["dr1", "qr3", "qr9"]) == {"dr1": "2026W20_1A", "qr3": "2026W40_2A"}


def test_list_week_takes_both_processing_folders_and_only_level2_images():
    b = FakeBucket()
    k1 = put(b, proc="l2b-v27-2026-300")[0]
    k2 = put(b, obs="2026W33_1A_0002_1", det=5, proc="l2b_retry-v27-2026-301")[0]
    b.put(f"qr3/level2/{WEEK}/l2b-v27-2026-300/manifest.txt", b"x")
    assert sorted(k for k, _ in s3.list_week(b, "qr3", WEEK)) == sorted([k1, k2])


def test_parse_key():
    k = "qr3/level2/2026W40_2A/l2b-v27-2026-285/1/level2_2026W40_2A_0001_1D1_spx_l2b-v27-2026-285.fits"
    assert s3.parse_key(k) == ("2026W40_2A_0001_1", 1)
    assert s3.parse_key("qr3/level2/x.fits") is None


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class FakeSession:
    def __init__(self, answers):
        self.answers, self.calls, self.headers = list(answers), [], {}

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers, dict(params or {})))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    def mount(self, *a):
        pass


def listing(prefixes=(), keys=(), token=None):
    ns = "http://s3.amazonaws.com/doc/2006-03-01/"
    body = "".join(f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes)
    body += "".join(f"<Contents><Key>{k}</Key><Size>{n}</Size></Contents>" for k, n in keys)
    trunc = f"<IsTruncated>true</IsTruncated><NextContinuationToken>{token}</NextContinuationToken>" if token else \
        "<IsTruncated>false</IsTruncated>"
    return f'<?xml version="1.0"?><ListBucketResult xmlns="{ns}"><Prefix>x</Prefix>{trunc}{body}</ListBucketResult>'.encode()


def test_s3_reader_follows_listing_pages(monkeypatch):
    monkeypatch.setattr(s3.time, "sleep", lambda s: None)
    sess = FakeSession([FakeResponse(200, listing(["qr3/"], [("a.fits", 5)], token="T1")),
                        FakeResponse(200, listing(["dr1/"], [("b.fits", 7)]))])
    r = s3.S3Reader(session=sess)
    prefixes, keys = r.list("", delimiter="/")
    assert prefixes == ["qr3/", "dr1/"] and keys == [("a.fits", 5), ("b.fits", 7)]
    assert sess.calls[1][2]["continuation-token"] == "T1"


def test_s3_reader_retries_5xx_and_sends_a_range(monkeypatch):
    monkeypatch.setattr(s3.time, "sleep", lambda s: None)
    sess = FakeSession([FakeResponse(503), OSError("reset") if False else FakeResponse(502),
                        FakeResponse(206, b"abcd")])
    r = s3.S3Reader(session=sess)
    assert r.read("k.fits", 10, 14) == b"abcd"
    assert sess.calls[-1][1] == {"Range": "bytes=10-13"} and r.requests == 1 and r.bytes == 4


def test_s3_reader_gives_up_on_404_without_retrying(monkeypatch):
    monkeypatch.setattr(s3.time, "sleep", lambda s: None)
    sess = FakeSession([FakeResponse(404)] * 5)
    with pytest.raises(s3.S3Error, match="HTTP 404"):
        s3.S3Reader(session=sess).read("missing.fits", 0, 10)
    assert len(sess.calls) == 1


def test_s3_reader_rejects_a_listing_that_is_not_xml(monkeypatch):
    sess = FakeSession([FakeResponse(200, b"<html>proxy error")])
    with pytest.raises(s3.S3Error):
        s3.S3Reader(session=sess).list("")


# ---------------------------------------------------------------- headers ---------------------------------------

def card(text):
    return text.ljust(80).encode()


def test_parse_cards_types_quotes_and_hierarch():
    buf = b"".join([card("STR     = 'it''s ok  '           / a comment"), card("INT     =                   42"),
                    card("FLT     =       -1.5D-03 / D exponent"), card("BOOL    =                    T"),
                    card("HIERARCH SPS_FLAGS = 'all_sky,downlink' / flags"), card("COMMENT = not a value card?"),
                    card("HISTORY something"), card("END")])
    c = s3.parse_cards(buf)
    assert c["STR"] == "it's ok" and c["INT"] == 42 and c["FLT"] == pytest.approx(-1.5e-3) and c["BOOL"] is True
    assert c["SPS_FLAGS"] == "all_sky,downlink"


def test_find_end_and_header_length():
    buf = card("SIMPLE  =                    T") + card("END") + b" " * 2720
    assert s3.find_end(buf) == 160 and s3.header_length(160) == 2880
    assert s3.find_end(card("SIMPLE  =                    T")) == -1


def test_head_cards_reads_both_headers_of_a_level2_file():
    raw, h, _ = make_level2()
    prim, c, hl, h0 = s3.head_cards(raw[:s3.HEAD_BLOCKS * s3.BLOCK])
    assert h0 == 2880 and prim["VERSION"] == "7.0.5" and c["EXTNAME"] == "IMAGE" and c["DETECTOR"] == 1
    assert c["CRVAL1"] == h["CRVAL1"] and c["A_0_2"] == h["A_0_2"] and c["SPS_FLAGS"] == "all_sky"


def test_head_cards_says_when_the_bytes_are_too_short():
    raw, _, _ = make_level2()
    with pytest.raises(ValueError):
        s3.head_cards(raw[:4000])


def test_read_head_reads_more_for_a_long_header():
    b = FakeBucket()
    k, h, _ = put(b, extra_history=400)                  # an IMAGE header of about 13 blocks
    buf = s3.read_head(b, k)
    assert s3.head_cards(buf)[1]["OBSID"] == "2026W33_1A_0001_1"
    assert len(b.reads) >= 2 and b.reads[0] == (k, 0, s3.HEAD_BLOCKS * s3.BLOCK)


# ---------------------------------------------------------------- geometry --------------------------------------

@pytest.mark.parametrize("ra,dec,rot", [(10.0, 20.0, 30.0), (359.9, -5.0, 120.0), (200.0, 88.5, 0.0), (45.0, -89.0, 77.0)])
def test_fast_sip_tan_matches_astropy(ra, dec, rot):
    _, h, _ = make_level2(nx=64, ny=48, ra=ra, dec=dec, rot_deg=rot)
    px, py = np.array([-0.5, 10.3, 63.5, 31.5]), np.array([-0.5, 40.2, 47.5, 23.5])
    a_ra, a_dec = WCS(s3.sky_header(h)).all_pix2world(px, py, 0)
    f_ra, f_dec = s3.sip_tan_pix2world(dict(h), px, py)
    assert np.max(s3.separation_deg(f_ra, f_dec, a_ra, a_dec)) * 3600 < 1e-4


def test_footprint_goes_round_the_image_edges():
    _, h, _ = make_level2(nx=64, ny=48)
    ra, dec, pts = s3.footprint(dict(h))
    w = WCS(s3.sky_header(h))
    cra, cdec = w.all_pix2world(31.5, 23.5, 0)
    assert len(pts) == 8 and s3.separation_deg(ra, dec, float(cra), float(cdec)) < 1e-5
    c0 = w.all_pix2world(-0.5, -0.5, 0)
    assert s3.separation_deg(pts[0][0], pts[0][1], float(c0[0]), float(c0[1])) < 1e-5


def rec_for(h, **extra):
    ra, dec, pts = s3.footprint(dict(h))
    return {"ra": ra, "dec": dec, "corners": pts, **extra}


def test_covers_inside_and_outside():
    _, h, _ = make_level2(nx=64, ny=48, ra=10.0, dec=20.0)
    r = rec_for(h)
    w = WCS(s3.sky_header(h))
    inside = w.all_pix2world(5.0, 40.0, 0)
    outside = w.all_pix2world(70.0, 20.0, 0)
    assert s3.covers(r, float(inside[0]), float(inside[1]))
    assert not s3.covers(r, float(outside[0]), float(outside[1]))


def test_covers_with_a_margin_takes_a_point_just_outside():
    _, h, _ = make_level2(nx=64, ny=48, ra=10.0, dec=20.0, rot_deg=0.0)
    r = rec_for(h)
    w = WCS(s3.sky_header(h))
    just_out = w.all_pix2world(64.5, 20.0, 0)              # one pixel (6.15") past the edge
    assert not s3.covers(r, float(just_out[0]), float(just_out[1]))
    assert s3.covers(r, float(just_out[0]), float(just_out[1]), margin_deg=0.002)
    assert not s3.covers(r, float(just_out[0]), float(just_out[1]), margin_deg=0.0005)


def test_covers_across_ra_zero():
    _, h, _ = make_level2(nx=64, ny=64, ra=0.02, dec=10.0, rot_deg=10.0)
    r = rec_for(h)
    assert any(p[0] > 359 for p in r["corners"]) and any(p[0] < 1 for p in r["corners"])
    assert s3.covers(r, 359.99, 10.0) and s3.covers(r, 0.05, 10.0)
    assert not s3.covers(r, 180.02, 10.0) and not s3.covers(r, 0.5, 10.0)


def test_covers_an_image_that_holds_the_north_pole():
    _, h, _ = make_level2(nx=64, ny=64, ra=123.0, dec=89.98, rot_deg=45.0)
    r = rec_for(h)
    for ra in (0.0, 90.0, 180.0, 270.0, 359.0):
        assert s3.covers(r, ra, 89.995), ra
    assert not s3.covers(r, 123.0, 89.5)


def test_covers_near_the_south_pole():
    _, h, _ = make_level2(nx=64, ny=64, ra=300.0, dec=-89.97, rot_deg=-20.0)
    r = rec_for(h)
    assert s3.covers(r, 300.0, -89.97) and s3.covers(r, 120.0, -89.995) and s3.covers(r, 31.0, -89.99)
    assert not s3.covers(r, 300.0, -89.0)


def test_covers_rejects_the_far_side_of_the_sky():
    _, h, _ = make_level2(ra=10.0, dec=20.0)
    assert not s3.covers(rec_for(h), 190.0, -20.0, margin_deg=1.0)


def test_candidates_cut_by_centre_distance_across_ra_zero():
    idx = [{"ra": 359.0, "dec": 0.0, "k": 1}, {"ra": 1.5, "dec": 0.0, "k": 2}, {"ra": 5.0, "dec": 0.0, "k": 3}]
    assert [r["k"] for r in s3.candidates(idx, 0.2, 0.0)] == [1, 2]
    assert s3.candidates([], 0, 0) == []


def test_jyear_matches_astropy():
    from astropy.time import Time
    assert s3.jyear(61314.5) == pytest.approx(Time(61314.5, format="mjd").jyear, abs=1e-9)


# ---------------------------------------------------------------- the index -------------------------------------

def week_bucket():
    b = FakeBucket()
    exposure(b, "2026W33_1A_0001_1", 10.0, 20.0, 61270.25, dets=(1, 2, 4, 5), shift_deg=0.003)
    exposure(b, "2026W33_1A_0002_1", 10.4, 20.0, 61270.26, dets=(1, 4), shift_deg=0.003)
    exposure(b, "2026W33_1A_0003_1", 10.8, 20.0, 61270.27, dets=(6,), proc="l2b_retry-v27-2026-301")
    return b


def test_index_record_fields():
    b = FakeBucket()
    k, h, _ = put(b, det=2, mjd=61300.125, flags="all_sky,downlink")
    rec = s3.index_record(k, 123, s3.read_head(b, k), "qr3", WEEK)
    assert set(rec) == set(s3.INDEX_FIELDS)
    assert rec["detector"] == 2 and rec["mjd"] == 61300.125 and rec["obs_id"] == "2026W33_1A_0001_1"
    assert (rec["em_min"], rec["em_max"]) == s3.DETECTOR_BANDS[2] and rec["sps_flags"] == "all_sky,downlink"
    assert rec["size"] == 123 and rec["inferred_from"] is None and len(rec["corners"]) == 8


def test_build_index_reads_half_the_headers_and_infers_dichroic_partners(tmp_path):
    b = week_bucket()
    st = s3.build_index(b, "qr3", weeks=[WEEK], workers=4, root=tmp_path, log=lambda m: None)
    recs = {(r["obs_id"], r["detector"]): r for r in s3.load_index("qr3", tmp_path)}
    assert set(recs) == {("2026W33_1A_0001_1", 1), ("2026W33_1A_0001_1", 2), ("2026W33_1A_0001_1", 4),
                         ("2026W33_1A_0001_1", 5), ("2026W33_1A_0002_1", 1), ("2026W33_1A_0002_1", 4),
                         ("2026W33_1A_0003_1", 6)}
    assert st["read"] == 4 and st["inferred"] == 3          # D1, D2, D1 read; D4, D5, D4 inferred; lone D6 read
    d4 = recs[("2026W33_1A_0001_1", 4)]
    assert d4["inferred_from"] == recs[("2026W33_1A_0001_1", 1)]["key"] and d4["corners"] == recs[("2026W33_1A_0001_1", 1)]["corners"]
    assert (d4["em_min"], d4["em_max"]) == s3.DETECTOR_BANDS[4] and "/4/" in d4["key"]
    assert recs[("2026W33_1A_0003_1", 6)]["inferred_from"] is None
    assert s3.index_coverage("qr3", tmp_path) == [WEEK]


def test_build_index_is_resumable_and_skips_finished_weeks(tmp_path):
    b = week_bucket()
    s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    n_reads, n_lists = len(b.reads), len(b.lists)
    st = s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    assert st["weeks_skipped"] == 1 and st["read"] == 0
    assert len(b.reads) == n_reads and len(b.lists) == n_lists        # not even listed again


def test_build_index_is_incremental_when_a_new_week_appears(tmp_path):
    b = week_bucket()
    s3.build_index(b, "qr3", workers=2, root=tmp_path, log=lambda m: None)
    exposure(b, "2026W34_1A_0001_1", 30.0, 0.0, 61277.0, week="2026W34_1A", dets=(3, 6))
    st = s3.build_index(b, "qr3", workers=2, root=tmp_path, log=lambda m: None)
    assert st["weeks_skipped"] == 1 and st["read"] == 1 and st["inferred"] == 1
    assert len(s3.load_index("qr3", tmp_path)) == 9
    assert s3.index_coverage("qr3", tmp_path) == [WEEK, "2026W34_1A"]


def test_a_broken_last_line_is_skipped_and_its_image_read_again(tmp_path):
    b = week_bucket()
    s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    p = s3.index_path("qr3", tmp_path)
    lines = p.read_text().splitlines()
    lone = next(l for l in lines if '"detector":6' in l)
    p.write_text("\n".join(l for l in lines if l != lone) + "\n" + lone[:40])     # killed mid-write
    s3.state_path("qr3", tmp_path).unlink()                                      # and before the state was saved
    assert len(s3.load_index("qr3", tmp_path)) == 6
    st = s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    assert st["read"] == 1 and len(s3.load_index("qr3", tmp_path)) == 7


def test_a_failing_file_leaves_the_week_unfinished_until_it_reads(tmp_path):
    b = week_bucket()
    bad = level2_key("qr3", WEEK, "2026W33_1A_0002_1", 1)
    b.fail.add(bad)
    st = s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    assert st["failed"] == 1 and s3.index_coverage("qr3", tmp_path) == []
    b.fail.clear()
    st = s3.build_index(b, "qr3", weeks=[WEEK], workers=2, root=tmp_path, log=lambda m: None)
    assert st["read"] == 1 and s3.index_coverage("qr3", tmp_path) == [WEEK] and len(s3.load_index("qr3", tmp_path)) == 7


def test_plan_reads_without_pairs_reads_every_detector_asked():
    keys = [(level2_key("qr3", WEEK, "2026W33_1A_0001_1", d), 10) for d in (1, 2, 4, 5)]
    reads, inferred = s3.plan_reads(keys, (1, 4, 5), infer_pairs=False)
    assert sorted(s3.parse_key(k)[1] for k in reads) == [1, 4, 5] and inferred == {}
    reads, inferred = s3.plan_reads(keys, (4,), infer_pairs=True)        # D4 wanted: read D1, infer D4
    assert [s3.parse_key(k)[1] for k in reads] == [1] and len(inferred) == 1


# ---------------------------------------------------------------- search ----------------------------------------

def indexed(tmp_path, b):
    s3.build_index(b, "qr3", workers=2, root=tmp_path, log=lambda m: None)
    return s3.load_index("qr3", tmp_path)


def test_search_uses_the_target_position_at_each_image_time(tmp_path):
    b = FakeBucket()
    # two exposures of the same field, 100 days apart; a fast mover crosses the image edge in between
    _, h, _ = put(b, obs="2026W33_1A_0001_1", det=1, ra=10.0, dec=20.0, mjd=61270.0, rot_deg=0.0)
    put(b, week="2026W48_1A", obs="2026W48_1A_0001_1", det=1, ra=10.0, dec=20.0, mjd=61370.0, rot_deg=0.0)
    idx = indexed(tmp_path, b)
    w = WCS(s3.sky_header(h))
    edge_ra = float(w.all_pix2world(63.5, 23.5, 0)[0])        # the image's east/west edge at the centre row
    step = (edge_ra - 10.0) * 2 / 100                          # crosses from the centre to well past the edge

    def at(mjd):
        return 10.0 + step * (mjd - 61270.0), 20.0
    found = s3.search(idx, at, 10.0, 20.0, margin_deg=0.0)
    assert [r["obs_id"] for r in found] == ["2026W33_1A_0001_1"]
    found = s3.search(idx, lambda mjd: (10.0, 20.0), 10.0, 20.0)
    assert [r["obs_id"] for r in found] == ["2026W33_1A_0001_1", "2026W48_1A_0001_1"]       # time order


def test_search_keeps_the_wide_survey_only(tmp_path):
    b = FakeBucket()
    put(b, obs="2026W33_1A_0001_1", det=1, flags="all_sky,go_back_s12")
    put(b, obs="2026W33_1A_0002_1", det=1, flags="deep_north")
    put(b, obs="2026W33_1A_0003_1", det=1, flags="all_sky,downlink")
    found = s3.search(indexed(tmp_path, b), lambda m: (10.0, 20.0), 10.0, 20.0)
    assert [r["obs_id"] for r in found] == ["2026W33_1A_0001_1", "2026W33_1A_0003_1"]
    assert len(s3.search(s3.load_index("qr3", tmp_path), lambda m: (10.0, 20.0), 10.0, 20.0, survey=None)) == 3


def test_in_survey():
    assert s3.in_survey({"sps_flags": "all_sky"}) and s3.in_survey({"sps_flags": "all_sky,downlink"})
    assert not s3.in_survey({"sps_flags": "deep_south,downlink"}) and not s3.in_survey({"sps_flags": None})


def test_search_checks_an_inferred_partner_with_its_own_header(tmp_path):
    b = FakeBucket()
    # D4 sits 0.03 deg (16 px) east of D1 here: a target just inside D1's west edge is outside D4's real footprint
    keys = exposure(b, "2026W33_1A_0001_1", 10.0, 20.0, 61270.0, dets=(1, 4), shift_deg=0.03, rot_deg=0.0)
    idx = indexed(tmp_path, b)
    d1 = next(r for r in idx if r["detector"] == 1)
    _, h, _ = make_level2(ra=10.0, dec=20.0, rot_deg=0.0)
    w = WCS(s3.sky_header(h))
    near_west = w.all_pix2world(62.0, 23.5, 0)                 # PC1_1 < 0: high x is west (smaller RA... or larger)
    tra, tdec = float(near_west[0]), float(near_west[1])
    assert s3.covers(d1, tra, tdec)
    n_reads = len(b.reads)
    found = s3.search(idx, lambda m: (tra, tdec), 10.0, 20.0, reader=b, release="qr3", root=tmp_path)
    real_d4 = rec_for(make_level2(ra=10.03, dec=20.0, rot_deg=0.0)[1])
    want = {1} | ({4} if s3.covers(real_d4, tra, tdec, s3.SIA_RADIUS_DEG) else set())
    assert {r["detector"] for r in found} == want and 4 not in want
    assert any(k == keys[4] for k, _, _ in b.reads[n_reads:])           # D4's own header was read
    # the exact record went into the index: no inferred D4 any more
    assert all(r["inferred_from"] is None for r in s3.load_index("qr3", tmp_path))


def test_search_answer_says_whether_the_index_was_complete():
    recs = [{"key": "k", "obs_id": "o", "detector": 1, "mjd": 61270.0}]
    a = s3.search_answer("qr3", recs, ["2026W20_2A", "2026W21_1A"], ["2026W20_2A", "2026W21_1A"], {}, "2026-11-15T12:00:00Z")
    assert a["index_complete"] and a["release"] == "spherex_qr3" and a["images"][0]["t_min"] == 61270.0
    a = s3.search_answer("qr3", recs, ["2026W20_2A", "2026W21_1A"], ["2026W20_2A"], {}, "2026-11-15T12:00:00Z")
    assert not a["index_complete"] and a["missing_weeks"] == ["2026W21_1A"]
    assert not s3.search_answer("qr3", [], [], [], {}, "x")["index_complete"]


def test_sia_like_rows_have_irsa_urls_and_the_s3_key():
    rec = {"key": level2_key("qr3", WEEK, "2026W33_1A_0001_1", 3), "obs_id": "2026W33_1A_0001_1", "detector": 3,
           "mjd": 61270.5, "mjd_end": 61270.6, "corners": [[1, 2]] * 8, "em_min": 1e-6, "em_max": 2e-6}
    row = s3.sia_like_rows([rec], "qr3")[0]
    assert row["access_url"] == "https://irsa.ipac.caltech.edu/ibe/data/spherex/" + rec["key"]
    assert json.loads(row["cloud_access"])["aws"] == {"bucket_name": "nasa-irsa-spherex", "key": rec["key"],
                                                       "region": "us-east-1"}
    assert row["energy_bandpassname"] == "SPHEREx-D3" and row["obs_collection"] == "spherex_qr3"
    assert row["t_min"] == 61270.5 and row["dataproduct_subtype"] == "science"


# ---------------------------------------------------------------- cutouts ---------------------------------------

def test_cutout_box_puts_the_target_where_irsa_does():
    # an IRSA cutout (size 52) of a DR1 image: target at SIP pixel (1629.046, 279.408), origin (1604, 254)
    assert s3.cutout_box(1629.046, 279.408, 52, 2040, 2040) == (1604, 1656, 254, 306)
    assert s3.cutout_box(845.982, 633.943, 52, 2040, 2040) == (820, 872, 608, 660)
    x0, x1, y0, y1 = s3.cutout_box(100.999, 50.0, 51, 2040, 2040)
    assert x1 - x0 == 51 and x0 == 100 - 24


def test_cutout_box_is_clipped_at_the_low_edges():
    assert s3.cutout_box(3.2, 1.7, 52, 2040, 2040) == (0, 30, 0, 28)


def test_cutout_box_is_clipped_at_the_high_edges():
    assert s3.cutout_box(2038.5, 2039.9, 52, 2040, 2040) == (2013, 2040, 2014, 2040)


def test_cutout_box_misses():
    assert s3.cutout_box(-30.0, 100.0, 52, 2040, 2040) is None
    assert s3.cutout_box(100.0, 2066.0, 52, 2040, 2040) is None
    assert s3.cutout_box(float("nan"), 100.0, 52, 2040, 2040) is None


def test_shift_header_moves_only_the_reference_pixels():
    _, h, _ = make_level2()
    s = s3.shift_header(h, 10, 7, 20, 21)
    assert (s["NAXIS1"], s["NAXIS2"]) == (20, 21)
    assert s["CRPIX1"] == h["CRPIX1"] - 10 and s["CRPIX2"] == h["CRPIX2"] - 7
    assert (s["CRPIX1A"], s["CRPIX2A"], s["CRPIX1W"], s["CRPIX2W"]) == (-9.0, -6.0, -9.0, -6.0)
    changed = {k for k in h if k not in ("NAXIS1", "NAXIS2") and h[k] != s[k]}
    assert changed == {"CRPIX1", "CRPIX2", "CRPIX1A", "CRPIX2A", "CRPIX1W", "CRPIX2W"}


def cut(b, k, box):
    return fits.open(io.BytesIO(s3.cutout_section(b, k, lambda w, nx, ny: box)))


def test_cutout_has_the_extensions_fetch_keeps():
    b = FakeBucket()
    k, _, _ = put(b)
    hd = cut(b, k, (10, 30, 5, 25))
    assert [h.name for h in hd] == ["PRIMARY", "IMAGE", "FLAGS", "VARIANCE", "WCS-WAVE"]
    assert hd[0].header["VERSION"] == "7.0.5" and hd["FLAGS"].data.dtype.kind == "i"


def test_cutout_pixels_equal_a_direct_section_of_every_image():
    b = FakeBucket()
    k, _, data = put(b, seed=7)
    hd = cut(b, k, (10, 30, 5, 25))
    for name in ("IMAGE", "FLAGS", "VARIANCE"):
        assert np.array_equal(hd[name].data, data[name][5:25, 10:30]), name
        assert hd[name].data.dtype == data[name].dtype.newbyteorder(">") or hd[name].data.dtype.kind == data[name].dtype.kind


def test_cutout_wcs_matches_the_full_image_wcs_at_the_same_pixels():
    b = FakeBucket()
    k, h, _ = put(b)
    hd = cut(b, k, (10, 30, 5, 25))
    full = WCS(s3.sky_header(h))
    sub = WCS(s3.sky_header(hd["IMAGE"].header))
    xs, ys = np.array([0.0, 7.3, 19.0]), np.array([0.0, 11.1, 19.0])
    a = full.all_pix2world(xs + 10, ys + 5, 0)
    c = sub.all_pix2world(xs, ys, 0)
    assert np.max(s3.separation_deg(a[0], a[1], c[0], c[1])) * 3600 < 1e-4
    # and the 'A' WCS still gives full-image 0-based pixels
    assert WCS(hd["IMAGE"].header, key="A").wcs_pix2world([[0, 0]], 0).tolist()[0] == [10.0, 5.0]


def test_cutout_headers_equal_the_originals_except_size_and_offsets():
    b = FakeBucket()
    raw, h, _ = make_level2()
    k = level2_key("qr3", WEEK, "2026W33_1A_0001_1", 1)
    b.put(k, raw)
    orig = fits.open(io.BytesIO(raw))
    hd = cut(b, k, (10, 30, 5, 25))
    moved = {"NAXIS1", "NAXIS2", "CRPIX1", "CRPIX2", "CRPIX1A", "CRPIX2A", "CRPIX1W", "CRPIX2W"}
    for name in ("IMAGE", "FLAGS", "VARIANCE"):
        a, c = orig[name].header, hd[name].header
        assert [x for x in a if x not in ("ZQUANTIZ",)] == [x for x in c], name
        assert {x for x in a if a[x] != c[x]} <= moved, name
    assert repr(orig["WCS-WAVE"].header) == repr(hd["WCS-WAVE"].header)
    for col in ("X", "Y", "VALUES"):
        assert np.array_equal(orig["WCS-WAVE"].data[col], hd["WCS-WAVE"].data[col])


def test_cutout_at_an_image_corner_is_clipped():
    b = FakeBucket()
    k, h, data = put(b, nx=64, ny=48)
    w = WCS(s3.sky_header(h))
    ra, dec = w.all_pix2world(2.2, 46.4, 0)
    hd = fits.open(io.BytesIO(s3.cutout(b, k, float(ra), float(dec), 20)))
    x0, y0 = int(1 - hd["IMAGE"].header["CRPIX1A"]), int(1 - hd["IMAGE"].header["CRPIX2A"])
    assert (x0, y0) == (0, 37) and hd["IMAGE"].data.shape == (11, 13)
    assert np.array_equal(hd["IMAGE"].data, data["IMAGE"][37:48, 0:13])


def test_cutout_off_the_image_is_none():
    b = FakeBucket()
    k, _, _ = put(b, ra=10.0, dec=20.0)
    assert s3.cutout(b, k, 15.0, 20.0, 20) is None


def test_cutout_reads_a_few_small_ranges_only():
    b = FakeBucket()
    k, h, _ = put(b, nx=256, ny=256)
    w = WCS(s3.sky_header(h))
    ra, dec = w.all_pix2world(128.0, 128.0, 0)
    assert s3.cutout(b, k, float(ra), float(dec), 20) is not None
    assert b.requests <= 8
    rows = 20 * 256 * 4
    assert b.bytes < 2 * rows + 60 * s3.BLOCK < len(b.objects[k]) / 3


def test_cutout_centres_the_target_like_irsa():
    b = FakeBucket()
    k, h, _ = put(b, nx=128, ny=128)
    w = WCS(s3.sky_header(h))
    ra, dec = w.all_pix2world(60.7, 70.2, 0)
    hd = fits.open(io.BytesIO(s3.cutout(b, k, float(ra), float(dec), 52)))
    assert (1 - hd["IMAGE"].header["CRPIX1A"], 1 - hd["IMAGE"].header["CRPIX2A"]) == (60 - 25, 70 - 25)
    px, py = WCS(s3.sky_header(hd["IMAGE"].header)).all_world2pix(float(ra), float(dec), 0)
    assert 25 <= px < 26 and 25 <= py < 26


def test_check_pairs_measures_the_partner_offsets():
    b = FakeBucket()
    exposure(b, "2026W33_1A_0001_1", 10.0, 0.0, 61270.0, dets=(1, 2, 3, 4, 5, 6), shift_deg=20 / 3600)
    exposure(b, "2026W33_1A_0002_1", 50.0, 0.0, 61270.1, dets=(1, 2, 3, 4, 5, 6), shift_deg=20 / 3600)
    st = s3.check_pairs(b, "qr3", [WEEK], per_week=2, log=lambda m: None)
    assert st["pairs"] == 6 and st["max_mjd_difference_s"] == 0
    assert 19.9 < st["max_offset_arcsec"] < 20.1 and 19.9 < st["mean_offset_arcsec"][0]


def test_load_index_near_reads_only_nearby_images_and_keeps_the_latest_line(tmp_path):
    p = s3.index_path("qr3", tmp_path)
    recs = [{"key": "a", "ra": 359.5, "dec": 0.0, "v": 1}, {"key": "b", "ra": 20.0, "dec": 0.0, "v": 1},
            {"key": "a", "ra": 359.5, "dec": 0.0, "v": 2}, {"key": "c", "ra": 1.0, "dec": 1.0, "v": 1}]
    p.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs) + '{"key":"broken","ra":0.1,')
    near = {r["key"]: r["v"] for r in s3.load_index("qr3", tmp_path, near=(0.2, 0.0, 3.0))}
    assert near == {"a": 2, "c": 1}
    assert s3.indexed_keys("qr3", tmp_path) == {"a", "b", "c", "broken"}
    assert len(s3.load_index("qr3", tmp_path)) == 3
    assert s3.load_index("qr9", tmp_path, near=(0, 0, 1)) == [] and s3.indexed_keys("qr9", tmp_path) == set()


def test_inferred_footprints_are_widened_by_more_than_the_measured_pair_offset():
    assert s3.PAIR_MARGIN_DEG * 3600 > s3.PAIR_CHECK["max_offset_arcsec"]
