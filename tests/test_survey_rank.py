"""Gaia DR3 cross-match of survey movers (pipeline/survey/rank.py). No network: the TAP call (rank._tap_query) is
replaced by a fake Gaia that answers the real ADQL circles from a small list of stars, and urlopen is blocked.
Optional live check against ESA: SURVEY_NET=1 pytest tests/test_survey_rank.py -k real
"""
import io
import json
import math
import os
import random
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from survey import rank as R  # noqa: E402

KAPTEYN_ID = 4810594479418041856
CIRCLE = re.compile(r"CIRCLE\('ICRS',\s*([-+\d.eE]+),\s*([-+\d.eE]+),\s*([-+\d.eE]+)\)")


# --------------------------------------------------------------------------------------------- helpers
def oracle(ra, dec, pmra, pmdec, dt):
    """Independent propagation with astropy (great-circle offset; identical to linear motion at these scales)."""
    pm = math.hypot(pmra, pmdec)
    if pm == 0 or dt == 0:
        return ra % 360.0, dec
    pa = math.atan2(pmra, pmdec)
    sep = pm * dt
    if sep < 0:
        pa, sep = pa + math.pi, -sep
    c = SkyCoord(ra * u.deg, dec * u.deg).directional_offset_by(pa * u.rad, sep * u.mas)
    return c.ra.deg, c.dec.deg


def offset(ra, dec, east_arcsec, north_arcsec):
    c = SkyCoord(ra * u.deg, dec * u.deg).spherical_offsets_by(east_arcsec * u.arcsec, north_arcsec * u.arcsec)
    return c.ra.deg, c.dec.deg


def star(sid, ra, dec, pmra=0.0, pmdec=0.0, g=15.0, plx=5.0, ref_epoch=2016.0):
    return {"source_id": sid, "ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "parallax": plx,
            "phot_g_mean_mag": g, "ref_epoch": ref_epoch}


def local_pm(st, epoch):
    """The star's motion as the core would measure it at `epoch`: pmra/pmdec along the local RA/Dec axes there
    (near a pole these differ from the 2016 components)."""
    t = epoch - st.get("ref_epoch", 2016.0)
    args = (st["ra"], st["dec"], st["pmra"] or 0.0, st["pmdec"] or 0.0)
    mid = SkyCoord(*oracle(*args, t), unit="deg")
    a = mid.spherical_offsets_to(SkyCoord(*oracle(*args, t - 0.01), unit="deg"))
    b = mid.spherical_offsets_to(SkyCoord(*oracle(*args, t + 0.01), unit="deg"))
    return ((b[0] - a[0]).to_value(u.mas) / 0.02, (b[1] - a[1]).to_value(u.mas) / 0.02)


def mover_for(st, epoch=2019.2, k5=8545, mid="8545-0001", dpm=(0.0, 0.0), off=(0.0, 0.0), **kw):
    """A mover that is the star `st` seen at `epoch` (optionally offset on the sky and with a perturbed motion)."""
    pmra, pmdec = local_pm(st, epoch)
    pmra, pmdec = pmra + dpm[0], pmdec + dpm[1]
    ra, dec = oracle(st["ra"], st["dec"], st["pmra"] or 0.0, st["pmdec"] or 0.0, epoch - st.get("ref_epoch", 2016.0))
    if off != (0.0, 0.0):
        ra, dec = offset(ra, dec, *off)
    m = {"id": mid, "k5": k5, "ra": ra, "dec": dec, "epoch": epoch, "pmra": pmra, "pmdec": pmdec,
         "pm": math.hypot(pmra, pmdec), "pm_err": 5.0, "pm_snr": 300.0, "chi2r": 1.2, "n_visits": 20,
         "span_yr": 10.0, "w1": 12.0, "w2": 11.8, "w1w2": 0.2, "plx": None, "plx_err": None, "track": [],
         "flags": []}
    m.update(kw)
    return m


def blank_mover(ra, dec, pmra, pmdec, epoch=2019.2, k5=8545, mid="8545-0009", **kw):
    m = {"id": mid, "k5": k5, "ra": ra, "dec": dec, "epoch": epoch, "pmra": pmra, "pmdec": pmdec,
         "pm": math.hypot(pmra, pmdec), "pm_err": 5.0, "pm_snr": 300.0, "chi2r": 1.2, "n_visits": 20,
         "span_yr": 10.0, "w1": 15.0, "w2": 13.0, "w1w2": 2.0, "flags": []}
    m.update(kw)
    return m


class FakeGaia:
    """Answers ADQL like the ESA service would: Gaia rows inside any CIRCLE of the query (and G < limit)."""

    def __init__(self, stars, columns=R.GAIA_COLUMNS):
        self.stars, self.columns, self.calls = stars, columns, []

    def rows_for(self, adql):
        circles = [tuple(map(float, c)) for c in CIRCLE.findall(adql)]
        lim = re.search(r"phot_g_mean_mag < ([\d.]+)", adql)
        out = []
        for s in self.stars:
            if lim and (s["phot_g_mean_mag"] is None or s["phot_g_mean_mag"] >= float(lim.group(1))):
                continue
            if s["ra"] is None or s["dec"] is None:      # broken rows are passed through for robustness tests
                out.append(s)
                continue
            here = SkyCoord(s["ra"] * u.deg, s["dec"] * u.deg)
            if any(here.separation(SkyCoord(a * u.deg, d * u.deg)).deg <= r for a, d, r in circles):
                out.append(s)
        return out

    def __call__(self, tap_url, adql, timeout):
        self.calls.append(adql)
        rows = [[s.get(c) for c in self.columns] for s in self.rows_for(adql)]
        text = json.dumps({"metadata": [{"name": c, "datatype": "double"} for c in self.columns], "data": rows})
        return json.loads(text)   # through real JSON text, like the service


@pytest.fixture(autouse=True)
def offline(monkeypatch, request):
    """No sleeping between retries, and no real network unless the test is the opt-in live one."""
    monkeypatch.setattr(R, "RETRY_SLEEP_S", 0.0)
    monkeypatch.setattr(R, "_down_until", {})          # no mirror cool-down carried over between tests
    if not request.node.name.startswith("test_real_"):
        def blocked(*a, **k):
            raise urllib.error.URLError("network disabled in tests")
        monkeypatch.setattr(R.urllib.request, "urlopen", blocked)


@pytest.fixture
def gaia(monkeypatch):
    def install(stars, **kw):
        fake = FakeGaia(stars, **kw)
        monkeypatch.setattr(R, "_tap_query", fake)
        return fake
    return install


def failing(exc, calls=None):
    def f(tap_url, adql, timeout):
        if calls is not None:
            calls.append(adql)
        raise exc
    return f


KAP = star(KAPTEYN_ID, 77.95994, -45.04381, 6491.2, -5708.6, g=8.06, plx=254.2)
SLOW = star(111, 120.0, 10.0, 300.0, -200.0, g=14.2)


# --------------------------------------------------------------------------------------------- geometry
def test_propagate_zero_motion_is_identity():
    ra, dec = R.propagate(123.4, -56.7, 0.0, 0.0, 8.0)
    assert ra == pytest.approx(123.4, abs=1e-12) and dec == pytest.approx(-56.7, abs=1e-12)


@pytest.mark.parametrize("ra,dec", [(10.0, 20.0), (359.999, 0.5), (0.0005, -30.0), (45.0, 89.99), (200.0, -89.995)])
def test_propagate_matches_astropy(ra, dec):
    got = R.propagate(ra, dec, 4000.0, -3000.0, 3.5)
    want = oracle(ra, dec, 4000.0, -3000.0, 3.5)
    assert R.separation_arcsec(*got, *want) < 1e-4


def test_propagate_backwards_undoes_forwards():
    there = R.propagate(77.96, -45.04, 6491.2, -5708.6, 3.2)
    back = R.propagate(*there, 6491.2, -5708.6, -3.2)
    assert R.separation_arcsec(*back, 77.96, -45.04) < 0.01   # pm direction rotates slightly over 27"


def test_separation_across_ra_wrap():
    assert R.separation_arcsec(359.9999, 0.0, 0.0001, 0.0) == pytest.approx(0.72, rel=1e-6)


def test_separation_near_pole():
    assert R.separation_arcsec(0.0, 89.9999, 180.0, 89.9999) == pytest.approx(0.72, rel=1e-6)


def test_propagated_ra_stays_in_range_across_zero():
    ra, dec = R.propagate(359.9995, 5.0, 5000.0, 0.0, 2.0)
    assert 0.0 <= ra < 360.0 and ra < 1.0


# --------------------------------------------------------------------------------------------- queries
def test_one_query_per_tile(gaia, tmp_path):
    fake = gaia([])
    movers = [blank_mover(120 + i * 0.01, 10, 500, 0, k5=100, mid=f"100-{i}") for i in range(5)]
    movers += [blank_mover(200 + i * 0.01, -10, 500, 0, k5=200, mid=f"200-{i}") for i in range(3)]
    R.crossmatch_gaia(movers, tmp_path)
    assert len(fake.calls) == 2
    assert sorted(len(CIRCLE.findall(q)) for q in fake.calls) == [3, 5]


def test_adql_selects_gaia_dr3_columns(gaia, tmp_path):
    fake = gaia([])
    R.crossmatch_gaia([blank_mover(120, 10, 500, 0)], tmp_path)
    q = fake.calls[0]
    assert "FROM gaiadr3.gaia_source" in q
    for c in ["source_id", "ra", "dec", "pmra", "pmdec", "parallax", "phot_g_mean_mag"]:
        assert re.search(rf"\b{c}\b", q.split("FROM")[0])
    assert "CONTAINS(POINT('ICRS', ra, dec)" in q
    assert "phot_g_mean_mag <" not in q          # no magnitude cut unless the answer is too large


def test_large_tile_split_into_batches(gaia, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "MAX_CONES_PER_QUERY", 3)
    fake = gaia([])
    R.crossmatch_gaia([blank_mover(120 + i * 0.01, 10, 500, 0, mid=f"m{i}") for i in range(7)], tmp_path)
    assert [len(CIRCLE.findall(q)) for q in fake.calls] == [3, 3, 1]


def test_query_text_independent_of_input_order(gaia, tmp_path):
    movers = [blank_mover(120 + i * 0.01, 10, 500, 0, mid=f"m{i}") for i in range(6)]
    fake = gaia([])
    R.crossmatch_gaia([dict(m) for m in movers], None)
    first = list(fake.calls)
    random.Random(4).shuffle(movers)
    fake.calls.clear()
    R.crossmatch_gaia([dict(m) for m in movers], None)
    assert fake.calls == first


def test_circle_centred_on_movers_2016_position(gaia, tmp_path):
    fake = gaia([KAP])
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    ra, dec, r = map(float, CIRCLE.findall(fake.calls[0])[0])
    assert R.separation_arcsec(ra, dec, KAP["ra"], KAP["dec"]) < 0.05
    assert r * 3600 >= 3.0 + 0.5 * 3.2


def test_circle_ra_normalised_at_wrap(gaia, tmp_path):
    fake = gaia([])
    R.crossmatch_gaia([blank_mover(0.0003, 2.0, 6000.0, 0.0, epoch=2020.0)], tmp_path)
    ra, dec, r = map(float, CIRCLE.findall(fake.calls[0])[0])
    assert 359.99 < ra < 360.0
    assert R.separation_arcsec(ra, dec, 0.0003, 2.0) == pytest.approx(24.0, abs=0.1)


def test_circle_dec_valid_at_pole(gaia, tmp_path):
    fake = gaia([])
    R.crossmatch_gaia([blank_mover(10.0, 89.9995, 0.0, 3000.0, epoch=2020.0)], tmp_path)
    ra, dec, r = map(float, CIRCLE.findall(fake.calls[0])[0])
    assert -90.0 <= dec <= 90.0 and 0.0 <= ra < 360.0


# --------------------------------------------------------------------------------------------- matching
def test_match_star_at_2016_propagated_to_2019(gaia, tmp_path):
    gaia([KAP, SLOW])
    m = mover_for(KAP, epoch=2019.2)
    R.crossmatch_gaia([m], tmp_path)
    g = m["gaia"]
    assert g["checked"] is True and g["match"] is True
    assert g["source_id"] == str(KAPTEYN_ID)
    assert g["sep_arcsec"] < 0.05
    assert g["pm"] == pytest.approx(math.hypot(6491.2, -5708.6), abs=0.1)
    assert g["g"] == pytest.approx(8.06)
    assert set(g) == {"checked", "match", "source_id", "sep_arcsec", "pm", "g"}


def test_no_gaia_star_means_checked_without_match(gaia, tmp_path):
    gaia([SLOW])
    m = blank_mover(133.7864, -7.2439, -8123.0, 673.0, epoch=2019.5, k5=10226)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"] == {"checked": True, "match": False, "source_id": None, "sep_arcsec": None, "pm": None,
                         "g": None}


def test_fast_mover_matched_where_naive_matching_fails(gaia, tmp_path):
    fast = star(222, 133.79, -7.24, -8123.0, 673.0, g=20.5)
    gaia([fast])
    m = mover_for(fast, epoch=2020.5, k5=10226)
    naive = R.separation_arcsec(m["ra"], m["dec"], fast["ra"], fast["dec"])
    assert naive > 30.0                       # unpropagated positions are 37" apart: a 3" match would miss it
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["source_id"] == "222"
    assert m["gaia"]["sep_arcsec"] < 0.05


def test_unrelated_background_star_does_not_explain_fast_mover(gaia, tmp_path):
    m = blank_mover(150.0, 20.0, 5000.0, 2000.0, epoch=2019.5)
    bra, bdec = offset(m["ra"], m["dec"], 1.0, 0.0)            # a still star 1" from the mover's mean position
    gaia([star(333, bra, bdec, 2.0, -1.0, g=17.0)])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is True and m["gaia"]["match"] is False


def test_same_motion_allows_looser_position(gaia, tmp_path):
    st = star(444, 210.0, 30.0, 3000.0, 0.0)
    gaia([st])
    m = mover_for(st, epoch=2019.2, off=(4.0, 0.0), dpm=(100.0, 0.0))  # 4" off (> 3"), motion within 4 %
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["sep_arcsec"] == pytest.approx(4.0, abs=0.3)


def test_different_motion_and_offset_position_rejected(gaia, tmp_path):
    st = star(445, 210.0, 30.0, 3000.0, 0.0)
    gaia([st])
    m = mover_for(st, epoch=2019.2, off=(4.0, 0.0), dpm=(1200.0, 0.0))  # 4" off and 40 % faster
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is False


def test_same_motion_but_far_away_rejected(gaia, tmp_path):
    st = star(446, 210.0, 30.0, 3000.0, 0.0)
    gaia([st])
    m = mover_for(st, epoch=2019.2, off=(0.0, 10.0))
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is False


def test_slightly_wrong_motion_within_radius_still_matches(gaia, tmp_path):
    st = star(447, 30.0, -20.0, 1500.0, 900.0)
    gaia([st])
    m = mover_for(st, epoch=2019.0, dpm=(400.0, -300.0), off=(1.0, 1.0))   # 29 % off: rule 1 (within 3")
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True


def test_two_parameter_source_matches_where_mover_was_in_2016(gaia, tmp_path):
    m = blank_mover(150.0, 20.0, 5000.0, 2000.0, epoch=2019.5)
    ra16, dec16 = oracle(m["ra"], m["dec"], 5000.0, 2000.0, 2016.0 - 2019.5)
    gaia([star(555, ra16, dec16, None, None, g=20.7)])
    R.crossmatch_gaia([m], tmp_path)
    g = m["gaia"]
    assert g["match"] is True and g["source_id"] == "555" and g["pm"] is None and g["sep_arcsec"] < 0.1


def test_two_parameter_source_at_epoch_position_of_fast_mover_rejected(gaia, tmp_path):
    m = blank_mover(150.0, 20.0, 5000.0, 2000.0, epoch=2019.5)
    gaia([star(556, m["ra"], m["dec"], None, None, g=20.7)])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is False


def test_full_astrometry_match_preferred_over_two_parameter(gaia, tmp_path):
    st = star(600, 60.0, 15.0, 2000.0, 1000.0)
    m = mover_for(st, epoch=2019.0, off=(1.5, 0.0))
    ra16, dec16 = oracle(m["ra"], m["dec"], m["pmra"], m["pmdec"], -3.0)
    gaia([st, star(601, ra16, dec16, None, None)])            # the 2-parameter source is the closer one
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["source_id"] == "600" and m["gaia"]["pm"] is not None


def test_closest_of_two_candidates_wins(gaia, tmp_path):
    a = star(701, 60.0, 15.0, 2000.0, 1000.0)
    m = mover_for(a, epoch=2019.0, off=(1.0, 0.0))
    bra, bdec = offset(a["ra"], a["dec"], 1.4, 0.0)
    b = star(702, bra, bdec, 2000.0, 1000.0)                  # 0.4" from the mover, `a` is 1.0" away
    gaia([a, b])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["source_id"] == "702"


def test_null_g_magnitude_gives_none(gaia, tmp_path):
    st = star(800, 45.0, 45.0, 700.0, 100.0, g=None)
    gaia([st])
    m = mover_for(st)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["g"] is None


def test_big_source_id_kept_exact(gaia, tmp_path):
    gaia([KAP])
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["source_id"] == "4810594479418041856"


def test_source_id_given_as_string(gaia, tmp_path):
    st = dict(KAP, source_id="4810594479418041856")
    gaia([st])
    m = mover_for(st)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["source_id"] == "4810594479418041856"


def test_rows_with_null_position_skipped(gaia, tmp_path):
    gaia([star(900, None, None, 1.0, 1.0), KAP])
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True


def test_rows_with_non_numeric_values_skipped(monkeypatch, tmp_path):
    good = [KAPTEYN_ID, KAP["ra"], KAP["dec"], KAP["pmra"], KAP["pmdec"], 254.2, 8.06, 2016.0]
    monkeypatch.setattr(R, "_tap_query", lambda *a: {"metadata": [{"name": c} for c in R.GAIA_COLUMNS],
                                                       "data": [[1, "abc", 2.0, 0, 0, 0, 10, 2016.0], good]})
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True


def test_column_names_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_tap_query", lambda *a: {"metadata": [{"name": c.upper()} for c in R.GAIA_COLUMNS],
                                                       "data": [[KAP[c] for c in R.GAIA_COLUMNS]]})
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["source_id"] == str(KAPTEYN_ID)


def test_rows_as_objects_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_tap_query", lambda *a: {"metadata": [{"name": c} for c in R.GAIA_COLUMNS],
                                                       "data": [dict(KAP)]})
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True


def test_rows_without_ref_epoch_assume_2016(monkeypatch, tmp_path):
    cols = ["source_id", "ra", "dec", "pmra", "pmdec", "phot_g_mean_mag"]
    monkeypatch.setattr(R, "_tap_query", lambda *a: {"metadata": [{"name": c} for c in cols],
                                                       "data": [[KAPTEYN_ID, KAP["ra"], KAP["dec"], KAP["pmra"],
                                                                 KAP["pmdec"], 8.06]]})
    m = mover_for(KAP, epoch=2021.0)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["sep_arcsec"] < 0.05


def test_ref_epoch_column_is_used(gaia, tmp_path):
    st = star(1001, 300.0, -60.0, 10000.0, 0.0, ref_epoch=2015.5)   # 0.5 yr off 2016 = 5" at 10"/yr
    gaia([st])
    m = mover_for(st, epoch=2019.0)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["sep_arcsec"] < 0.05


# --------------------------------------------------------------------------------------------- wrap and poles
def test_match_across_ra_wrap(gaia, tmp_path):
    st = star(1100, 359.9990, 12.0, 6000.0, 500.0)
    m = mover_for(st, epoch=2019.5, k5=4600)
    assert m["ra"] < 1.0                      # the mover is already on the other side of RA 0
    gaia([st])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["sep_arcsec"] < 0.05


@pytest.mark.parametrize("dec", [89.998, -89.999])
def test_match_near_pole(gaia, tmp_path, dec):
    st = star(1200, 77.0, dec, 4000.0, 3000.0)
    m = mover_for(st, epoch=2020.0, k5=None)
    gaia([st])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and m["gaia"]["sep_arcsec"] < 0.05


def test_pole_mover_with_unrelated_motion_not_matched(gaia, tmp_path):
    st = star(1201, 77.0, 89.998, 4000.0, 3000.0)
    m = mover_for(st, epoch=2020.0, k5=None, dpm=(-8000.0, -6000.0), off=(0.0, 0.0))  # opposite direction
    gaia([st])
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is False


# --------------------------------------------------------------------------------------------- cache
def test_cache_hit_avoids_second_query(gaia, tmp_path):
    fake = gaia([KAP])
    first = [mover_for(KAP)]
    R.crossmatch_gaia(first, tmp_path)
    assert len(fake.calls) == 1
    second = [mover_for(KAP)]
    R.crossmatch_gaia(second, tmp_path)
    assert len(fake.calls) == 1 and second[0]["gaia"] == first[0]["gaia"]


def test_cache_is_one_json_file_per_tile(gaia, tmp_path):
    gaia([KAP])
    R.crossmatch_gaia([mover_for(KAP), blank_mover(133.79, -7.24, -8123, 673, k5=10226, mid="10226-1")],
                      tmp_path / "gaia")
    files = sorted(p.name for p in (tmp_path / "gaia").iterdir())
    assert files == ["gaia_dr3_tile_10226.json", "gaia_dr3_tile_8545.json"]
    doc = json.loads((tmp_path / "gaia" / "gaia_dr3_tile_8545.json").read_text())
    (entry,) = doc["answers"].values()
    assert "gaiadr3.gaia_source" in entry["query"] and entry["answer"]["data"][0][0] == KAPTEYN_ID


def test_cache_answers_survive_service_outage(gaia, tmp_path, monkeypatch):
    gaia([KAP])
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    monkeypatch.setattr(R, "_tap_query", failing(urllib.error.URLError("down")))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is True and m["gaia"]["match"] is True


def test_changed_movers_trigger_new_query_and_keep_old_answers(gaia, tmp_path):
    fake = gaia([KAP])
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    R.crossmatch_gaia([mover_for(KAP), mover_for(KAP, mid="8545-0002", off=(30.0, 0.0))], tmp_path)
    assert len(fake.calls) == 2
    doc = json.loads((tmp_path / "gaia_dr3_tile_8545.json").read_text())
    assert len(doc["answers"]) == 2


def test_corrupt_cache_file_ignored(gaia, tmp_path):
    (tmp_path / "gaia_dr3_tile_8545.json").write_text("{not json")
    fake = gaia([KAP])
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and len(fake.calls) == 1
    json.loads((tmp_path / "gaia_dr3_tile_8545.json").read_text())   # rewritten as valid JSON


def test_damaged_cache_entry_requeried(gaia, tmp_path):
    fake = gaia([KAP])
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    path = tmp_path / "gaia_dr3_tile_8545.json"
    doc = json.loads(path.read_text())
    for v in doc["answers"].values():
        v["answer"] = {"oops": 1}
    path.write_text(json.dumps(doc))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(fake.calls) == 2 and m["gaia"]["match"] is True


def test_no_cache_dir_still_works(gaia):
    fake = gaia([KAP])
    m = mover_for(KAP)
    R.crossmatch_gaia([m], None)
    R.crossmatch_gaia([mover_for(KAP)], None)
    assert m["gaia"]["match"] is True and len(fake.calls) == 2


# --------------------------------------------------------------------------------------------- failures
@pytest.mark.parametrize("exc", [urllib.error.URLError("no route"), socket.timeout("timed out"),
                                 TimeoutError("slow"), ConnectionResetError("reset"), OSError("dns")])
def test_network_failure_marks_not_checked(monkeypatch, tmp_path, exc):
    monkeypatch.setattr(R, "_tap_query", failing(exc))
    m = mover_for(KAP)
    out = R.crossmatch_gaia([m], tmp_path)
    assert out[0] is m
    assert m["gaia"]["checked"] is False and m["gaia"]["match"] is None and m["gaia"]["source_id"] is None
    assert "Gaia query failed" in m["gaia"]["error"]


def test_failure_in_one_tile_does_not_affect_another(monkeypatch, tmp_path):
    good = FakeGaia([KAP])

    def flaky(tap_url, adql, timeout):
        if "133.7" in adql:
            raise urllib.error.URLError("down")
        return good(tap_url, adql, timeout)
    monkeypatch.setattr(R, "_tap_query", flaky)
    a, b = mover_for(KAP), blank_mover(133.79, -7.24, -8123, 673, k5=10226, mid="10226-1")
    R.crossmatch_gaia([a, b], tmp_path)
    assert a["gaia"]["match"] is True and b["gaia"]["checked"] is False


def test_failures_are_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_tap_query", failing(urllib.error.URLError("down")))
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    fake = FakeGaia([KAP])
    monkeypatch.setattr(R, "_tap_query", fake)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(fake.calls) == 1 and m["gaia"]["match"] is True


def test_service_treated_as_down_after_repeated_failures(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", failing(urllib.error.URLError("down"), calls))
    movers = [blank_mover(10.0 * i, 0.0, 500, 0, k5=1000 + i, mid=f"t{i}") for i in range(8)]
    R.crossmatch_gaia(movers, tmp_path)
    assert len(calls) == R.MAX_CONSECUTIVE_FAILURES * R.ATTEMPTS * len(R.TAP_URLS)   # each query tries every service
    assert all(m["gaia"]["checked"] is False for m in movers)
    assert "unavailable" in movers[-1]["gaia"]["error"]


def test_transient_failure_retried(monkeypatch, tmp_path):
    good, calls = FakeGaia([KAP]), []

    def once_down(tap_url, adql, timeout):
        calls.append(adql)
        if len(calls) == 1:
            raise urllib.error.URLError("blip")
        return good(tap_url, adql, timeout)
    monkeypatch.setattr(R, "_tap_query", once_down)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(calls) == 2 and m["gaia"]["match"] is True


@pytest.mark.parametrize("status,expected_calls", [(503, R.ATTEMPTS * len(R.TAP_URLS)), (400, 1)])   # 5xx: every service tried
def test_server_errors_retried_but_rejected_queries_not(monkeypatch, tmp_path, status, expected_calls):
    calls = []
    monkeypatch.setattr(R, "_tap_query", failing(R.TapError(f"HTTP {status}: nope", status=status), calls))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(calls) == expected_calls and m["gaia"]["checked"] is False


@pytest.mark.parametrize("answer", [
    {"metadata": [{"name": c} for c in R.GAIA_COLUMNS]},                        # no data
    {"data": []},                                                                 # no metadata
    {"metadata": [{"name": "source_id"}, {"name": "ra"}], "data": [[1, 2.0]]},   # missing columns
    {"metadata": [{"name": c} for c in R.GAIA_COLUMNS], "data": [[1, 2.0, 3.0]]},  # short row
    {"metadata": [{"nom": "x"}], "data": []},                                     # column without a name
    [1, 2, 3], "SELECT failed", None, 42,
])
def test_malformed_answer_marks_not_checked(monkeypatch, tmp_path, answer):
    monkeypatch.setattr(R, "_tap_query", lambda *a: answer)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is False and "unusable" in m["gaia"]["error"]
    assert not (tmp_path / "gaia_dr3_tile_8545.json").exists()   # bad answers are not cached


def test_too_large_retried_with_magnitude_limit(monkeypatch, tmp_path):
    good, calls = FakeGaia([KAP]), []

    def picky(tap_url, adql, timeout):
        calls.append(adql)
        if "phot_g_mean_mag <" not in adql:
            raise R.TapError("Query result too large: more than 3000000 rows", status=500)
        return good(tap_url, adql, timeout)
    monkeypatch.setattr(R, "_tap_query", picky)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(calls) == 2 and "phot_g_mean_mag < 21" in calls[1]
    assert m["gaia"]["match"] is True


def test_too_large_twice_splits_the_batch(monkeypatch, tmp_path):
    good, calls = FakeGaia([KAP]), []

    def one_at_a_time(tap_url, adql, timeout):
        calls.append(adql)
        if len(CIRCLE.findall(adql)) > 1:
            raise R.TapError("Result size exceeds the limit")
        return good(tap_url, adql, timeout)
    monkeypatch.setattr(R, "_tap_query", one_at_a_time)
    movers = [mover_for(KAP)] + [blank_mover(78.0 + 0.01 * i, -45.0, 500, 0, mid=f"8545-1{i}") for i in range(3)]
    R.crossmatch_gaia(movers, tmp_path)
    assert all(m["gaia"]["checked"] for m in movers)
    assert movers[0]["gaia"]["match"] is True


def test_too_large_for_a_single_mover_marks_it_not_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_tap_query", failing(R.TapError("too many rows")))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is False and "too many Gaia sources" in m["gaia"]["error"]


def test_answer_at_row_limit_treated_as_truncated(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "MAX_ROWS", 2)
    fake = FakeGaia([KAP, dict(KAP, source_id=5, phot_g_mean_mag=22.0)])
    monkeypatch.setattr(R, "_tap_query", fake)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert len(fake.calls) == 2 and "phot_g_mean_mag < 21" in fake.calls[1]
    assert m["gaia"]["match"] is True


@pytest.mark.parametrize("message,too_large", [
    ("Query result too large", True), ("too many rows", True), ("Result size exceeds the limit", True),
    ("OVERFLOW", True), ("The number of rows exceeded the maximum", True), ("MAXREC reached", True),
    ("rate limit exceeded", False), ("Syntax error near SELECT", False), ("Service unavailable", False),
])
def test_too_large_detection(message, too_large):
    assert R._is_too_large(message) is too_large


# --------------------------------------------------------------------------------------------- odd inputs
def test_mover_without_tile_still_checked(gaia, tmp_path):
    gaia([KAP])
    m = mover_for(KAP, k5=None)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and (tmp_path / "gaia_dr3_tile_none.json").exists()


def test_empty_list_makes_no_query(gaia, tmp_path):
    fake = gaia([])
    assert R.crossmatch_gaia([], tmp_path) == []
    assert fake.calls == []


def test_returns_the_same_list_updated_in_place(gaia, tmp_path):
    gaia([KAP])
    movers = [mover_for(KAP), blank_mover(78.0, -45.0, 500, 0, mid="8545-0002")]
    out = R.crossmatch_gaia(movers, tmp_path)
    assert out is movers and all("gaia" in m for m in movers)


def test_generator_input_accepted(gaia, tmp_path):
    gaia([KAP])
    out = R.crossmatch_gaia((m for m in [mover_for(KAP)]), tmp_path)
    assert isinstance(out, list) and out[0]["gaia"]["match"] is True


@pytest.mark.parametrize("bad", [{"epoch": None}, {"ra": float("nan")}, {"dec": 95.0}, {"pmra": None},
                                 {"epoch": "soon"}])
def test_mover_without_usable_numbers_not_checked_and_not_queried(gaia, tmp_path, bad):
    fake = gaia([KAP])
    m = mover_for(KAP)
    m.update(bad)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is False and m["gaia"]["error"] and fake.calls == []


# --------------------------------------------------------------------------------------------- the real TAP call
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_tap_query_posts_adql_for_json(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None, context=None):
        seen.update(url=req.full_url, data=req.data, timeout=timeout, context=context, method=req.get_method())
        return FakeResponse(json.dumps({"metadata": [{"name": "source_id"}], "data": [[KAPTEYN_ID]]}).encode())
    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)
    out = R._tap_query(R.TAP_URL, "SELECT TOP 1 source_id FROM gaiadr3.gaia_source", 12)
    params = urllib.parse.parse_qs(seen["data"].decode())
    assert seen["url"] == "https://gea.esac.esa.int/tap-server/tap/sync" and seen["method"] == "POST"
    assert params["REQUEST"] == ["doQuery"] and params["LANG"] == ["ADQL"] and params["FORMAT"] == ["json"]
    assert params["QUERY"] == ["SELECT TOP 1 source_id FROM gaiadr3.gaia_source"]
    assert seen["timeout"] == 12 and isinstance(seen["context"], ssl.SSLContext)
    assert out["data"][0][0] == KAPTEYN_ID


def test_tap_query_http_error_keeps_service_message(monkeypatch):
    body = (b'<?xml version="1.0"?><VOTABLE><RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">'
            b'Query result too large</INFO></RESOURCE></VOTABLE>')

    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, io.BytesIO(body))
    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(R.TapError) as e:
        R._tap_query(R.TAP_URL, "SELECT 1", 5)
    assert "Query result too large" in str(e.value) and e.value.status == 500


def test_tap_query_error_votable_with_http_200(monkeypatch):
    body = b'<VOTABLE><INFO name="QUERY_STATUS" value="ERROR">Cannot parse query</INFO></VOTABLE>'
    monkeypatch.setattr(R.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body))
    with pytest.raises(R.TapError, match="Cannot parse query"):
        R._tap_query(R.TAP_URL, "SELEKT", 5)


def test_crossmatch_never_raises_when_network_is_down(tmp_path):
    m = mover_for(KAP)                        # real _tap_query; urlopen is blocked by the autouse fixture
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is False and "network disabled" in m["gaia"]["error"]


# --------------------------------------------------------------------------------------------- tile edges
def test_tile_edge_distance_matches_dense_sampling():
    from astropy_healpix import HEALPix
    lon, lat = HEALPix(nside=32, order="nested").boundaries_lonlat([8545], step=1000)
    brute = np.min(R.separation_arcsec(77.95994, -45.04381, lon.deg[0], lat.deg[0]))
    assert R.tile_edge_distance_arcsec(77.95994, -45.04381, 8545) == pytest.approx(brute, abs=0.2)


def test_tile_centre_far_from_edge():
    assert R.tile_edge_distance_arcsec(76.5, -44.99388015, 8545) > 2000.0


@pytest.mark.parametrize("k5", [-1, 12288, "abc", None])
def test_edge_distance_unknown_for_bad_tile(k5):
    assert R.tile_edge_distance_arcsec(10.0, 10.0, k5) is None


# --------------------------------------------------------------------------------------------- live (opt-in)
needs_net = pytest.mark.skipif(os.environ.get("SURVEY_NET") != "1", reason="set SURVEY_NET=1 to query ESA's Gaia TAP")


@needs_net
def test_real_gaia_kapteyns_star(tmp_path):
    m = mover_for(KAP, epoch=2019.2)
    R.crossmatch_gaia([m], tmp_path, timeout=90)
    assert m["gaia"]["checked"] is True, m["gaia"].get("error")
    assert m["gaia"]["match"] is True and m["gaia"]["source_id"] == str(KAPTEYN_ID)


@needs_net
def test_real_gaia_wise_0855_is_unexplained(tmp_path):
    m = blank_mover(133.7864, -7.2439, -8123.0, 673.0, epoch=2017.0, k5=10226, mid="10226-0001")
    R.crossmatch_gaia([m], tmp_path, timeout=90)
    assert m["gaia"]["checked"] is True, m["gaia"].get("error")
    assert m["gaia"]["match"] is False


# ------------------------------------------------------------------ ESA archive, then the ARI Heidelberg mirror
ARI = "https://gaia.ari.uni-heidelberg.de/tap/sync"


def test_default_services_are_esa_then_ari():
    assert R.TAP_URLS[0] == R.TAP_URL == "https://gea.esac.esa.int/tap-server/tap/sync"
    assert ARI in R.TAP_URLS and R.TAP_URLS.index(ARI) == 1
    import inspect
    assert inspect.signature(R.crossmatch_gaia).parameters["tap_url"].default == R.TAP_URLS


def _esa_down_ari_up(calls, stars):
    good = FakeGaia(stars)

    def f(tap_url, adql, timeout):
        calls.append(tap_url)
        if "esac" in tap_url:
            raise urllib.error.URLError("timed out")
        return good(tap_url, adql, timeout)
    return f


def test_falls_back_to_the_mirror_when_esa_is_down(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", _esa_down_ari_up(calls, [KAP]))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["checked"] is True and m["gaia"]["match"] is True
    assert calls[:R.ATTEMPTS] == [R.TAP_URL] * R.ATTEMPTS and calls[-1] == ARI


def test_a_failed_service_is_skipped_during_its_cooldown(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", _esa_down_ari_up(calls, [KAP]))
    for i in range(3):
        R.crossmatch_gaia([mover_for(KAP, k5=2000 + i, mid=f"c{i}")], tmp_path / str(i))
    assert calls.count(R.TAP_URL) == R.ATTEMPTS          # ESA only tried for the first tile
    assert calls.count(ARI) == 3


def test_service_tried_again_after_the_cooldown(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", _esa_down_ari_up(calls, [KAP]))
    R.crossmatch_gaia([mover_for(KAP, k5=3001, mid="a")], tmp_path / "a")
    R._down_until[R.TAP_URL] = 0.0                       # cool-down over
    R.crossmatch_gaia([mover_for(KAP, k5=3002, mid="b")], tmp_path / "b")
    assert calls.count(R.TAP_URL) == 2 * R.ATTEMPTS


def test_rejected_query_is_not_retried_on_the_mirror(monkeypatch, tmp_path):
    calls = []

    def reject(tap_url, adql, timeout):
        calls.append(tap_url)
        raise R.TapError("HTTP 400: syntax error", status=400)
    monkeypatch.setattr(R, "_tap_query", reject)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert calls == [R.TAP_URL]
    assert m["gaia"]["checked"] is False and "syntax" in m["gaia"]["error"]


def test_server_errors_move_on_to_the_mirror(monkeypatch, tmp_path):
    calls, good = [], FakeGaia([KAP])

    def f(tap_url, adql, timeout):
        calls.append(tap_url)
        if "esac" in tap_url:
            raise R.TapError("HTTP 502: Bad Gateway", status=502)
        return good(tap_url, adql, timeout)
    monkeypatch.setattr(R, "_tap_query", f)
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path)
    assert m["gaia"]["match"] is True and calls[-1] == ARI


def test_a_single_service_string_still_works(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", _esa_down_ari_up(calls, [KAP]))
    m = mover_for(KAP)
    R.crossmatch_gaia([m], tmp_path, tap_url=ARI)
    assert calls == [ARI] and m["gaia"]["match"] is True


def test_cache_records_the_service_that_answered(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(R, "_tap_query", _esa_down_ari_up(calls, [KAP]))
    R.crossmatch_gaia([mover_for(KAP)], tmp_path)
    blob = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert {a["tap_url"] for a in blob["answers"].values()} == {ARI}


def test_no_service_given_is_an_error():
    with pytest.raises(ValueError):
        R._Session([], 10)
