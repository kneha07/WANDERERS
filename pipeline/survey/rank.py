"""Catalogue check and ranking for the WANDERERS Sky Survey (see docs/survey-contract.md).

The core stage finds *movers* (sources whose NEOWISE positions drift along a straight line over 2014-2024).
Most of them are ordinary nearby stars that Gaia already measured. This module

1. checks every mover against Gaia DR3 (``crossmatch_gaia``), adding a ``gaia`` sub-object,
2. gives each mover a transparent interest ``score`` with plain-English ``reasons``,
3. puts it in a ``class`` (``classify``): "known (Gaia)", "likely artefact", "not checked" or "unexplained",
4. sorts them (``rank``) so people look at the most interesting ones first: unexplained, cold/red, fast and
   well measured.

Nothing here raises on a network problem: a mover whose Gaia check failed is marked ``gaia.checked = false``
("not checked") and the run carries on.

Matching rules (all positions on the sky as unit vectors, so RA 0/360 and the poles need no special cases):

* Each Gaia DR3 star (reference epoch 2016.0) is moved to the mover's epoch with its own proper motion.
* **Rule 1, same place:** the moved star lies within ``radius_arcsec`` of the mover, and the two motions are not
  wildly different (difference below 50 % of the mover's motion or 5 times its error). The motion check stops a
  fast mover that happens to pass within 3" of an unrelated background star at its mean epoch from being
  "explained" by it (a 3" circle holds a Gaia star ~10 % of the time in an average field, far more in the Milky Way).
* **Rule 2, same motion:** the motions agree within 20 % (or 3 times the mover's error) and the positions agree
  within ``radius_arcsec + 0.5"/yr x |epoch - 2016|`` (a looser circle that allows for small motion errors).
* **Rule 3, Gaia saw it without motion:** Gaia "2-parameter" sources have no proper motion (null pmra/pmdec).
  Such a source matches when its 2016 position is within ``radius_arcsec`` (plus the mover's own position error
  carried back to 2016) of where the mover was in 2016, worked out from the mover's own motion.

Full-astrometry matches (rules 1-2) win over 2-parameter ones; among several, the closest wins.

Querying: one ESA TAP query per tile (sync endpoint, ``REQUEST=doQuery&LANG=ADQL&FORMAT=json``) made of one
small circle per mover, centred on where the mover was in 2016 and wide enough to cover every star the rules
above could accept. Raw answers are cached as one JSON file per tile under ``cache_dir`` so reruns cost nothing.
A "results too large" answer is retried with ``phot_g_mean_mag < 21`` and then by splitting the tile's movers
into halves. After ``MAX_CONSECUTIVE_FAILURES`` network failures in a row the service is treated as down for the
rest of the call (cached tiles are still used).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------------------------
TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"          # ESA Gaia archive (the reference service)
TAP_MIRRORS = ("https://gaia.ari.uni-heidelberg.de/tap/sync",)  # ARI Heidelberg Gaia service: same gaiadr3 tables
TAP_URLS = (TAP_URL,) + TAP_MIRRORS     # tried in order; a service that fails is skipped for MIRROR_COOLDOWN_S
MIRROR_COOLDOWN_S = 6 * 3600.0       # an unreachable service costs ATTEMPTS x timeout each time it is retried
_down_until: dict = {}                  # tap_url -> time.monotonic() before which it is not tried again
GAIA_TABLE = "gaiadr3.gaia_source"
GAIA_COLUMNS = ["source_id", "ra", "dec", "pmra", "pmdec", "parallax", "phot_g_mean_mag", "ref_epoch"]
GAIA_EPOCH = 2016.0            # Gaia DR3 reference epoch (used when a row has no ref_epoch)
GAIA_MAG_LIMIT = 21.0          # G limit used when an answer is too large
MAX_ROWS = 50000               # MAXREC sent with each query; an answer this long is treated as truncated
MAX_CONES_PER_QUERY = 40       # movers per ADQL query (a tile with more is split into several queries)
MAX_CONSECUTIVE_FAILURES = 3   # network failures in a row before the service is treated as down
ATTEMPTS = 2                   # tries per query on a network error
RETRY_SLEEP_S = 2.0            # pause between tries
USER_AGENT = "wanderers-survey/1.0 (+https://github.com/kneha07/WANDERERS)"

POS_SLACK_ARCSEC_PER_YR = 0.5  # extra positional tolerance per year between 2016 and the mover epoch (rule 2)
TIGHT_PM_FRAC = 0.20           # rule 2: motions agree within 20 % ...
TIGHT_PM_SIGMA = 3.0           # ... or 3 x the mover's pm error
LOOSE_PM_FRAC = 0.50           # rule 1: motions differ by less than 50 % ...
LOOSE_PM_SIGMA = 5.0           # ... or 5 x the mover's pm error
SEARCH_MARGIN_ARCSEC = 2.0     # extra radius on every query circle
MAX_SEARCH_ARCSEC = 120.0      # cap on a query circle's radius

MAS_PER_RAD = 180.0 / math.pi * 3.6e6
ARCSEC_PER_RAD = 180.0 / math.pi * 3600.0

# Scoring thresholds (see score() for the table)
W1_SATURATION = 8.0            # WISE single exposures start to saturate brighter than about W1 8, W2 6.7
W2_SATURATION = 6.7
VERY_BRIGHT_MAG = 6.0          # W1 or W2 brighter than this: heavily saturated
MIN_VISITS = 6                 # fewer visits than this is a red flag
ARTEFACT_CHI2R = 30.0          # chi2r above this is a red flag ("chi2r >> 1")
ODD_CHI2R = 5.0                # for very bright sources: chi2r above this counts as odd motion
ODD_PM_SNR = 10.0              # for very bright sources: pm_snr below this counts as odd motion
MIN_PM_SNR = 3.0               # motion below 3 sigma is a red flag
MIN_SPAN_YR = 1.0              # a track spanning less than a year is a red flag
MAX_PLAUSIBLE_PM = 15000.0     # mas/yr; Barnard's Star, the fastest known, moves 10,400
NEARBY_PLX_MAS = 50.0          # parallax bonus: within 20 pc ...
NEARBY_PLX_SNR = 5.0           # ... measured at 5 sigma or better
SURVEY_START, SURVEY_END = 2013.95, 2024.6   # NEOWISE-R single-exposure coverage
EDGE_MARGIN_ARCSEC = 10.0
TILE_NSIDE = 32
ARTEFACT_FLAG_WORDS = ("artefact", "artifact", "ghost", "latent", "spike", "halo", "persist", "glint",
                       "scan", "satur", "bad", "spurious")

CLASSES = ("unexplained", "known (Gaia)", "likely artefact", "not checked")


class TapError(RuntimeError):
    """The TAP service answered with an error message (bad query, result too large, ...). ``status`` is the
    HTTP status when there was one; 5xx answers are retried."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _TooLarge(Exception):
    pass


class _ServiceDown(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------
# Small helpers: numbers and sphere geometry
# ---------------------------------------------------------------------------------------------------------------
def _num(x):
    """A finite float, or None for missing / NaN / non-numeric values."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _unit(ra_deg, dec_deg):
    """Unit vectors (..., 3) for RA/Dec in degrees."""
    a = np.radians(np.asarray(ra_deg, dtype=float))
    d = np.radians(np.asarray(dec_deg, dtype=float))
    cd = np.cos(d)
    return np.stack([cd * np.cos(a), cd * np.sin(a), np.sin(d)], axis=-1)


def _velocity(ra_deg, dec_deg, pmra, pmdec):
    """Proper motion (pmra includes cos dec, mas/yr) as a tangent vector in radians/yr, shape (..., 3)."""
    a = np.radians(np.asarray(ra_deg, dtype=float))
    d = np.radians(np.asarray(dec_deg, dtype=float))
    e_ra = np.stack([-np.sin(a), np.cos(a), np.zeros_like(a)], axis=-1)
    e_dec = np.stack([-np.sin(d) * np.cos(a), -np.sin(d) * np.sin(a), np.cos(d)], axis=-1)
    pmra = np.asarray(pmra, dtype=float)[..., None] / MAS_PER_RAD
    pmdec = np.asarray(pmdec, dtype=float)[..., None] / MAS_PER_RAD
    return pmra * e_ra + pmdec * e_dec


def _normalize(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _angle_arcsec(a, b):
    """Angle between unit vectors (robust at all separations), arcsec."""
    cross = np.linalg.norm(np.cross(a, b), axis=-1)
    dot = np.sum(a * b, axis=-1)
    return np.arctan2(cross, dot) * ARCSEC_PER_RAD


def _radec(v):
    v = np.asarray(v, dtype=float)
    dec = np.degrees(np.arcsin(np.clip(v[..., 2] / np.linalg.norm(v, axis=-1), -1.0, 1.0)))
    ra = np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360.0
    return ra, dec


def propagate(ra, dec, pmra, pmdec, dt_yr):
    """Move a position by its proper motion over ``dt_yr`` years (linear motion on the tangent plane, the same
    model as the core's motion fit). Returns (ra, dec) in degrees, RA in [0, 360). Works across RA 0/360 and
    near the poles."""
    p = _unit(ra, dec)
    v = _velocity(ra, dec, pmra, pmdec)
    out = _normalize(p + v * np.asarray(dt_yr, dtype=float)[..., None])
    r, d = _radec(out)
    return (float(r), float(d)) if np.ndim(r) == 0 else (r, d)


def separation_arcsec(ra1, dec1, ra2, dec2):
    """Angular separation in arcsec."""
    s = _angle_arcsec(_unit(ra1, dec1), _unit(ra2, dec2))
    return float(s) if np.ndim(s) == 0 else s


# ---------------------------------------------------------------------------------------------------------------
# Gaia DR3 cross-match
# ---------------------------------------------------------------------------------------------------------------
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # certifi missing: fall back to the system store
        return ssl.create_default_context()


def _tap_error_text(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    m = re.search(r'<INFO[^>]*name="QUERY_STATUS"[^>]*value="(?:ERROR|OVERFLOW)"[^>]*>(.*?)</INFO>', text, re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip() or "TAP error"
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:500] or "empty answer"


def _tap_query(tap_url: str, adql: str, timeout: float) -> dict:
    """Run one synchronous ADQL query and return the parsed JSON answer (``{"metadata": [...], "data": [...]}``).

    Raises ``TapError`` when the service reports an error (its message is kept, so "too large" can be detected)
    and the usual ``urllib``/``socket`` exceptions on network trouble. Tests replace this function.
    """
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "MAXREC": str(MAX_ROWS), "QUERY": adql}
    req = urllib.request.Request(tap_url, data=urllib.parse.urlencode(params).encode("utf-8"),
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        raise TapError(f"HTTP {e.code}: {_tap_error_text(body) if body else e.reason}", status=e.code) from None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TapError(_tap_error_text(body)) from None


_TOO_LARGE = re.compile(r"too (large|big|many)|overflow|maxrec"
                        r"|(rows|records|results?|size)\W(.*\W)?(exceed|limit)"
                        r"|(exceed\w*|limit\w*)\W(.*\W)?(rows|records|results?|size)", re.I)


def _is_too_large(message: str) -> bool:
    """Does a TAP error say the answer was too big? ("rate limit exceeded" does not count.)"""
    return bool(_TOO_LARGE.search(message))


def _gaia_unchecked(error=None):
    g = {"checked": False, "match": None, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}
    if error:
        g["error"] = str(error)[:300]
    return g


def _gaia_no_match():
    return {"checked": True, "match": False, "source_id": None, "sep_arcsec": None, "pm": None, "g": None}


def _source_id(x):
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return str(int(x)) if math.isfinite(x) and x == int(x) else None
    s = str(x).strip()
    return s if re.fullmatch(r"\d+", s) else None


def _parse_answer(answer) -> dict:
    """Turn a TAP JSON answer into column arrays. Raises ValueError when the structure is wrong; single rows with
    unusable values (no id, no position) are skipped."""
    if not isinstance(answer, dict):
        raise ValueError("Gaia answer is not a JSON object")
    meta, data = answer.get("metadata"), answer.get("data")
    if not isinstance(meta, list) or not isinstance(data, list):
        raise ValueError("Gaia answer lacks 'metadata' or 'data' lists")
    names = []
    for c in meta:
        name = c.get("name") if isinstance(c, dict) else c
        if not isinstance(name, str):
            raise ValueError("Gaia answer has a column without a name")
        names.append(name.strip().lower())
    missing = [c for c in ("source_id", "ra", "dec", "pmra", "pmdec") if c not in names]
    if missing:
        raise ValueError(f"Gaia answer lacks columns {missing}")
    out = {k: [] for k in ("source_id", "ra", "dec", "pmra", "pmdec", "parallax", "g", "ref_epoch")}
    nan = float("nan")
    for row in data:
        if isinstance(row, dict):
            vals = {str(k).strip().lower(): v for k, v in row.items()}
        elif isinstance(row, (list, tuple)) and len(row) == len(names):
            vals = dict(zip(names, row))
        else:
            raise ValueError("Gaia answer has a row of the wrong shape")
        s, r, d = _source_id(vals.get("source_id")), _num(vals.get("ra")), _num(vals.get("dec"))
        if s is None or r is None or d is None or not -90.0 <= d <= 90.0:
            continue
        a, b = _num(vals.get("pmra")), _num(vals.get("pmdec"))
        if a is None or b is None:                 # 2-parameter source: no proper motion
            a = b = nan
        plx, gmag, ep = _num(vals.get("parallax")), _num(vals.get("phot_g_mean_mag")), _num(vals.get("ref_epoch"))
        for k, v in (("source_id", s), ("ra", r % 360.0), ("dec", d), ("pmra", a), ("pmdec", b),
                     ("parallax", nan if plx is None else plx), ("g", nan if gmag is None else gmag),
                     ("ref_epoch", GAIA_EPOCH if ep is None else ep)):
            out[k].append(v)
    cols = {k: (v if k == "source_id" else np.asarray(v, dtype=float)) for k, v in out.items()}
    cols["n_raw"] = len(data)
    return cols


class _Prep:
    """What the matcher needs from one mover."""
    __slots__ = ("p", "v", "epoch", "pm", "pm_err", "tol_tight", "tol_loose", "center", "search_arcsec")

    def __init__(self, mover, radius):
        ra, dec, epoch = _num(mover.get("ra")), _num(mover.get("dec")), _num(mover.get("epoch"))
        pmra, pmdec = _num(mover.get("pmra")), _num(mover.get("pmdec"))
        if ra is None or dec is None or not -90.0 <= dec <= 90.0:
            raise ValueError("mover has no usable position")
        if epoch is None:
            raise ValueError("mover has no epoch")
        if pmra is None or pmdec is None:
            raise ValueError("mover has no proper motion")
        self.p = _unit(ra, dec)
        self.v = _velocity(ra, dec, pmra, pmdec)
        self.epoch = epoch
        self.pm = math.hypot(pmra, pmdec)
        self.pm_err = max(0.0, _num(mover.get("pm_err")) or 0.0)
        self.tol_tight = max(TIGHT_PM_FRAC * self.pm, TIGHT_PM_SIGMA * self.pm_err)
        self.tol_loose = max(LOOSE_PM_FRAC * self.pm, LOOSE_PM_SIGMA * self.pm_err)
        dt = abs(epoch - GAIA_EPOCH)
        p2016 = _normalize(self.p - self.v * (epoch - GAIA_EPOCH))
        cra, cdec = _radec(p2016)
        self.center = (float(cra) % 360.0, min(90.0, max(-90.0, float(cdec))))
        # Every star the rules can accept lies within this distance of the mover's 2016 position.
        r = radius + POS_SLACK_ARCSEC_PER_YR * dt + self.tol_loose * dt / 1000.0 + SEARCH_MARGIN_ARCSEC
        self.search_arcsec = min(r, MAX_SEARCH_ARCSEC)


def build_adql(preps, mag_limit=None) -> str:
    """ADQL for one batch: Gaia DR3 sources inside any of the movers' circles (centred where each mover was at
    2016.0), optionally limited to G < mag_limit."""
    cones = [f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {p.center[0] % 360.0:.7f}, {p.center[1]:.7f}, "
             f"{p.search_arcsec / 3600.0:.7f}))" for p in preps]
    where = "(" + "\n   OR ".join(cones) + ")"
    if mag_limit is not None:
        where += f"\n  AND phot_g_mean_mag < {mag_limit:g}"
    return f"SELECT {', '.join(GAIA_COLUMNS)}\nFROM {GAIA_TABLE}\nWHERE {where}"


def match_gaia(prep: _Prep, cols: dict, radius_arcsec: float) -> dict:
    """Apply the three matching rules (module docstring) to one mover and the Gaia rows near it."""
    if not cols["source_id"]:
        return _gaia_no_match()
    p_g = _unit(cols["ra"], cols["dec"])
    has_pm = np.isfinite(cols["pmra"]) & np.isfinite(cols["pmdec"])
    v_g = _velocity(cols["ra"], cols["dec"], np.where(has_pm, cols["pmra"], 0.0),
                    np.where(has_pm, cols["pmdec"], 0.0))
    dt = prep.epoch - cols["ref_epoch"]                                  # years from Gaia epoch to mover epoch
    sep_now = _angle_arcsec(_normalize(p_g + v_g * dt[:, None]), prep.p)  # Gaia star moved to the mover epoch
    sep_ref = _angle_arcsec(p_g, _normalize(prep.p - prep.v * dt[:, None]))  # mover moved back to Gaia epoch
    dpm = np.linalg.norm(v_g - prep.v, axis=-1) * MAS_PER_RAD
    rule1 = has_pm & (sep_now <= radius_arcsec) & (dpm <= prep.tol_loose)
    rule2 = has_pm & (dpm <= prep.tol_tight) & (sep_now <= radius_arcsec + POS_SLACK_ARCSEC_PER_YR * np.abs(dt))
    rule3 = ~has_pm & (sep_ref <= radius_arcsec + prep.pm_err * np.abs(dt) / 1000.0)
    full = rule1 | rule2
    if full.any():
        i = int(np.argmin(np.where(full, sep_now, np.inf)))
        sep, pm = float(sep_now[i]), round(math.hypot(cols["pmra"][i], cols["pmdec"][i]), 1)
    elif rule3.any():
        i = int(np.argmin(np.where(rule3, sep_ref, np.inf)))
        sep, pm = float(sep_ref[i]), None
    else:
        return _gaia_no_match()
    g = cols["g"][i]
    return {"checked": True, "match": True, "source_id": cols["source_id"][i], "sep_arcsec": round(sep, 3),
            "pm": pm, "g": None if not np.isfinite(g) else round(float(g), 3)}


class _TileCache:
    """Raw TAP answers for one tile, one JSON file: {"tile", "answers": {sha1(query): {...}}}."""

    def __init__(self, cache_dir, key):
        self.path = None if cache_dir is None else Path(cache_dir) / f"gaia_dr3_tile_{key}.json"
        self.key, self.answers, self.dirty = key, {}, False
        if self.path is not None and self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("answers"), dict):
                    self.answers = doc["answers"]
            except (OSError, ValueError) as e:
                log.warning("ignoring unreadable Gaia cache %s (%s)", self.path, e)

    @staticmethod
    def digest(adql):
        return hashlib.sha1(adql.encode("utf-8")).hexdigest()

    def get(self, adql):
        hit = self.answers.get(self.digest(adql))
        return hit.get("answer") if isinstance(hit, dict) and hit.get("query") == adql else None

    def put(self, adql, tap_url, answer):
        self.answers[self.digest(adql)] = {"query": adql, "tap_url": tap_url,
                                           "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                           "answer": answer}
        self.dirty = True

    def save(self):
        if self.path is None or not self.dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"tile": self.key, "source": f"Gaia DR3 ({GAIA_TABLE}) via TAP (ESA archive or the ARI Heidelberg mirror)",
                                       "answers": self.answers}), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError as e:
            log.warning("could not write Gaia cache %s (%s)", self.path, e)


class _Session:
    """Counts queries, cache hits and consecutive failures over one crossmatch_gaia call."""

    def __init__(self, tap_url, timeout):
        self.urls = [tap_url] if isinstance(tap_url, str) else [u for u in tap_url if u]
        if not self.urls:
            raise ValueError("no Gaia TAP service given")
        self.tap_url, self.timeout = self.urls[0], timeout
        self.failures = 0
        self.queries = self.cache_hits = 0

    def _services(self):
        """The services to try, in order: those not cooling down after a failure (all of them if every one is)."""
        if len(self.urls) == 1:
            return list(self.urls)
        now = time.monotonic()
        up = [u for u in self.urls if _down_until.get(u, 0.0) <= now]
        return up or list(self.urls)

    def answer(self, adql, cache: _TileCache):
        hit = cache.get(adql)
        if hit is not None:
            try:
                cols = _parse_answer(hit)
                self.cache_hits += 1
                return cols
            except ValueError:
                pass  # damaged cache entry: ask again
        if self.failures >= MAX_CONSECUTIVE_FAILURES:
            raise _ServiceDown("Gaia service unavailable (skipped after repeated failures)")
        err = None
        for url in self._services():
            down = False                              # this service is unreachable or broken: try the next one
            for k in range(ATTEMPTS):
                if k and RETRY_SLEEP_S > 0:
                    time.sleep(RETRY_SLEEP_S)
                self.queries += 1
                try:
                    answer = _tap_query(url, adql, self.timeout)
                except TapError as e:
                    if _is_too_large(str(e)):
                        raise _TooLarge(str(e)) from None
                    err = f"Gaia service error: {e}"
                    if (getattr(e, "status", None) or 0) >= 500:
                        down = True
                        continue                      # server trouble: try again
                    down = False
                    break                             # the service rejected the query: retrying won't help
                except Exception as e:                # network trouble of any kind: never raise
                    err = f"Gaia query failed: {type(e).__name__}: {e}"
                    down = True
                    continue
                try:
                    cols = _parse_answer(answer)
                except ValueError as e:
                    err = f"Gaia answer unusable: {e}"
                    down = True
                    break
                if cols["n_raw"] >= MAX_ROWS:
                    raise _TooLarge(f"{cols['n_raw']} rows (limit {MAX_ROWS})")
                self.failures = 0
                self.tap_url = url
                _down_until.pop(url, None)
                cache.put(adql, url, answer)
                return cols
            if not down:
                break                                 # a rejected query fails the same way everywhere
            if len(self.urls) > 1:
                _down_until[url] = time.monotonic() + MIRROR_COOLDOWN_S
                log.warning("Gaia service %s failing (%s); trying the next one", url, err)
        self.failures += 1
        raise RuntimeError(err)


def _resolve(items, session, cache, radius, mag_limit=None):
    """Query Gaia for a batch of (mover, prep) and set each mover's ``gaia``; never raises."""
    adql = build_adql([p for _, p in items], mag_limit)
    try:
        cols = session.answer(adql, cache)
    except _TooLarge as e:
        if mag_limit is None:
            log.info("Gaia answer too large for tile %s (%s); retrying with G < %g", cache.key, e, GAIA_MAG_LIMIT)
            return _resolve(items, session, cache, radius, GAIA_MAG_LIMIT)
        if len(items) > 1:
            half = len(items) // 2
            _resolve(items[:half], session, cache, radius, mag_limit)
            _resolve(items[half:], session, cache, radius, mag_limit)
            return
        items[0][0]["gaia"] = _gaia_unchecked(f"too many Gaia sources around this mover ({e})")
        return
    except Exception as e:  # _ServiceDown, network failure, bad answer
        for m, _ in items:
            m["gaia"] = _gaia_unchecked(e)
        return
    for m, p in items:
        try:
            m["gaia"] = match_gaia(p, cols, radius)
        except Exception as e:  # defensive: a numeric oddity must not stop the run
            m["gaia"] = _gaia_unchecked(f"matching failed: {e}")


def _tile_key(mover):
    k = mover.get("k5")
    if k is None or isinstance(k, bool):
        return "none"
    try:
        return str(int(k))
    except (TypeError, ValueError):
        return re.sub(r"[^0-9A-Za-z_-]", "_", str(k)) or "none"


def _id_key(mover):
    return str(mover.get("id", ""))


def crossmatch_gaia(movers, cache_dir, tap_url=TAP_URLS, radius_arcsec=3.0, timeout=60):
    """Check each mover against Gaia DR3 and add ``mover["gaia"]`` in place; returns ``movers``.

    ``gaia`` is ``{"checked", "match", "source_id", "sep_arcsec", "pm", "g"}``:

    * matched: ``checked=True, match=True``, Gaia ``source_id`` (string), separation at the mover's epoch
      (arcsec; for a 2-parameter source, at 2016), Gaia total proper motion ``pm`` (mas/yr, ``None`` for a
      2-parameter source) and G magnitude ``g``;
    * no counterpart: ``checked=True, match=False`` and the rest ``None``;
    * not checked (network error, timeout, unusable answer, mover without position/epoch/motion):
      ``checked=False, match=None`` plus an ``error`` text. Never raises for these.

    One query per tile (``k5``; movers without ``k5`` share one group), at most ``MAX_CONES_PER_QUERY`` movers per
    query; raw answers cached in ``cache_dir/gaia_dr3_tile_<k5>.json`` keyed by the exact query text, so a rerun
    with the same movers makes no network calls. See the module docstring for the matching rules.
    ``tap_url``: one TAP sync endpoint, or several tried in order (default: ESA, then the ARI Heidelberg mirror of
    the same gaiadr3 tables); a service that keeps failing is skipped for ``MIRROR_COOLDOWN_S``.
    """
    if movers is None:
        return movers
    if not isinstance(movers, list):
        movers = list(movers)
    session = _Session(tap_url, timeout)
    groups = {}
    for m in movers:
        try:
            prep = _Prep(m, radius_arcsec)
        except ValueError as e:
            m["gaia"] = _gaia_unchecked(e)
            continue
        groups.setdefault(_tile_key(m), []).append((m, prep))
    for key in sorted(groups):
        items = sorted(groups[key], key=lambda it: _id_key(it[0]))
        cache = _TileCache(cache_dir, key)
        for i in range(0, len(items), MAX_CONES_PER_QUERY):
            _resolve(items[i:i + MAX_CONES_PER_QUERY], session, cache, radius_arcsec)
        cache.save()
    n_match = sum(1 for m in movers if (m.get("gaia") or {}).get("match"))
    n_unchecked = sum(1 for m in movers if not (m.get("gaia") or {}).get("checked"))
    log.info("Gaia check: %d movers, %d matched, %d not checked; %d queries, %d cache hits",
             len(movers), n_match, n_unchecked, session.queries, session.cache_hits)
    return movers


# ---------------------------------------------------------------------------------------------------------------
# Tile edges (HEALPix order 5)
# ---------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def _tile_boundary(k5):
    try:
        from astropy_healpix import HEALPix
    except ImportError:
        return None
    if not 0 <= k5 < 12 * TILE_NSIDE ** 2:
        return None
    lon, lat = HEALPix(nside=TILE_NSIDE, order="nested").boundaries_lonlat([k5], step=16)
    return _unit(lon.deg[0], lat.deg[0])


def tile_edge_distance_arcsec(ra, dec, k5):
    """Distance from (ra, dec) to the nearest edge of HEALPix order-5 tile ``k5`` in arcsec, or None when it
    cannot be worked out (no ``astropy_healpix``, bad tile number)."""
    try:
        b = _tile_boundary(int(k5))
    except (TypeError, ValueError):
        return None
    if b is None or ra is None or dec is None:
        return None
    p = _unit(ra, dec)
    a, c = b, np.roll(b, -1, axis=0)
    n = np.cross(a, c)
    nn = np.linalg.norm(n, axis=-1)
    ok = nn > 1e-15
    n = n / np.where(ok, nn, 1.0)[:, None]
    s = p @ n.T                                        # sine of the distance to each great circle
    q = p - s[:, None] * n
    inside = ok & (np.sum(np.cross(a, q) * n, axis=-1) >= 0) & (np.sum(np.cross(q, c) * n, axis=-1) >= 0)
    d_arc = np.abs(np.arcsin(np.clip(s, -1, 1))) * ARCSEC_PER_RAD
    d_end = _angle_arcsec(a, p[None, :])
    return float(np.min(np.where(inside, d_arc, d_end)))


def near_tile_edge(mover) -> bool:
    """True when the mover's path over the whole survey (2014-2024) could reach its tile's edge, so detections
    on the far side (another tile) may be missing; also true when the core flagged it ('edge')."""
    if any("edge" in str(f).lower() for f in (mover.get("flags") or [])):
        return True
    ra, dec, k5 = _num(mover.get("ra")), _num(mover.get("dec")), mover.get("k5")
    if k5 is None or ra is None or dec is None:
        return False
    d = tile_edge_distance_arcsec(ra, dec, k5)
    if d is None:
        return False
    pm = _num(mover.get("pm"))
    if pm is None:
        a, b = _num(mover.get("pmra")), _num(mover.get("pmdec"))
        pm = math.hypot(a, b) if a is not None and b is not None else 0.0
    ep = _num(mover.get("epoch")) or (SURVEY_START + SURVEY_END) / 2
    reach = abs(pm) / 1000.0 * max(ep - SURVEY_START, SURVEY_END - ep, 0.0) + EDGE_MARGIN_ARCSEC
    return d < reach


# ---------------------------------------------------------------------------------------------------------------
# Scoring, classification, ranking
# ---------------------------------------------------------------------------------------------------------------
def _fmt_years(span):
    if span is None:
        return None
    if span >= 2:
        n = int(round(span))
        return f"{n} years"
    v = round(span, 1)
    return "1 year" if v == 1.0 else f"{v:.1f} years"


def _fmt_count(x):
    return f"{x:,.0f}" if x >= 10 else f"{x:.1f}"


def _is_saturated(w1, w2):
    return (w1 is not None and w1 < W1_SATURATION) or (w2 is not None and w2 < W2_SATURATION)


def red_flags(mover) -> list:
    """Short phrases for the signs that a mover is probably not real (empty list = none). Any of them makes
    ``classify`` say "likely artefact" (unless Gaia knows the object) and costs ``RED_FLAG_POINTS``."""
    flags = []
    ra, dec, pm = _num(mover.get("ra")), _num(mover.get("dec")), _num(mover.get("pm"))
    if pm is None:
        a, b = _num(mover.get("pmra")), _num(mover.get("pmdec"))
        pm = math.hypot(a, b) if a is not None and b is not None else None
    if ra is None or dec is None or pm is None:
        flags.append("missing measurements")
    n = _num(mover.get("n_visits"))
    if n is not None and n < MIN_VISITS:
        flags.append("seen in too few visits")
    chi2r = _num(mover.get("chi2r"))
    if chi2r is not None and chi2r > ARTEFACT_CHI2R:
        flags.append("positions far from a straight path")
    snr = _num(mover.get("pm_snr"))
    if snr is not None and snr < MIN_PM_SNR:
        flags.append("motion not clearly measured")
    span = _num(mover.get("span_yr"))
    if span is not None and span < MIN_SPAN_YR:
        flags.append("seen over less than a year")
    if pm is not None and pm > MAX_PLAUSIBLE_PM:
        flags.append("faster than any known star")
    w1, w2 = _num(mover.get("w1")), _num(mover.get("w2"))
    very_bright = (w1 is not None and w1 < VERY_BRIGHT_MAG) or (w2 is not None and w2 < VERY_BRIGHT_MAG)
    odd = (chi2r is not None and chi2r > ODD_CHI2R) or (snr is not None and snr < ODD_PM_SNR)
    if very_bright and odd:
        flags.append("very bright with an unsteady path")
    for f in mover.get("flags") or []:
        if any(w in str(f).lower() for w in ARTEFACT_FLAG_WORDS):
            flags.append(f"flagged as {str(f).strip().replace('_', ' ')}")
    return flags


# Weights (points); the score is the plain sum of the terms below.
WEIGHTS = {
    "catalogue_unexplained": 3.0,   # Gaia checked, nothing there
    "catalogue_known": -3.0,        # Gaia star with matching position and motion
    "catalogue_known_2p": -2.0,     # Gaia saw a source there in 2016 but without a motion
    "colour_per_mag": 1.0,          # per magnitude of W1-W2 above 0.2, up to 3 points
    "colour_w1_missing": 1.5,       # W2 measured but no W1: probably very red
    "colour_saturated_factor": 0.5, # colour counts half when saturated
    "motion_snr_max": 2.5,          # log10(pm_snr), 0 ... 2.5
    "speed_max": 1.0,               # 0.75 x log10(pm / 150 mas/yr), 0 ... 1
    "visits_min": -2.0,             # log2(n_visits / 6), -2 ... +1.5
    "visits_max": 1.5,
    "span_per_yr": 0.1,             # 0.1 per year, up to 1
    "fit_good": 0.5,                # 0.5 - log2(max(chi2r, 1.5) / 1.5), -4 ... +0.5
    "fit_min": -4.0,
    "parallax_nearby": 0.5,         # parallax >= 50 mas at >= 5 sigma
    "bright_per_mag": -0.5,         # per magnitude brighter than saturation, down to -2
    "bright_min": -2.0,
    "tile_edge": -0.5,              # path may reach the tile edge
    "flag_each": -0.5,              # each flag from the core, down to -1.5
    "flags_min": -1.5,
    "red_flag": -2.0,               # once, if red_flags(mover) is not empty
    "spherex_confirmed": 0.5,       # SPHEREx 2025-26 sees it where its motion predicts, gone from its 2014 spot
}
RED_FLAG_POINTS = WEIGHTS["red_flag"]


def score_terms(mover) -> list:
    """The individual score terms for a mover: ``[{"term", "points", "reason"}]`` (reason may be None).
    ``score`` is their sum; see its docstring for the table."""
    W = WEIGHTS
    terms = []

    def add(term, points, reason=None):
        terms.append({"term": term, "points": float(points), "reason": reason})

    # Catalogue (Gaia)
    g = mover.get("gaia") if isinstance(mover.get("gaia"), dict) else {}
    if g.get("checked") and g.get("match"):
        sid, sep = g.get("source_id"), _num(g.get("sep_arcsec"))
        where = f" ({sep:.1f}″ away)" if sep is not None else ""
        if _num(g.get("pm")) is None:
            add("catalogue", W["catalogue_known_2p"],
                f"Gaia saw a source at this spot in 2016 (Gaia DR3 {sid}){where} but did not measure its motion")
        else:
            gpm = _num(g.get("pm")) / 1000.0
            add("catalogue", W["catalogue_known"],
                f"Already known: Gaia DR3 {sid} is at the same spot{where} and moves "
                f"{gpm:.1f}″ a year" if gpm >= 1 else
                f"Already known: Gaia DR3 {sid} is at the same spot{where} and moves {gpm:.2f}″ a year")
    elif g.get("checked"):
        add("catalogue", W["catalogue_unexplained"], "No star in Gaia's billion-star catalogue explains it")
    else:
        add("catalogue", 0.0, "Not yet checked against the Gaia star catalogue")

    w1, w2 = _num(mover.get("w1")), _num(mover.get("w2"))
    sat = _is_saturated(w1, w2)
    factor = W["colour_saturated_factor"] if sat else 1.0

    # Colour
    c = _num(mover.get("w1w2"))
    if c is None and w1 is not None and w2 is not None:
        c = w1 - w2
    if c is not None:
        pts = W["colour_per_mag"] * min(max(c - 0.2, 0.0), 3.0) * factor
        cs = f"W1−W2 = {c:.1f}"
        if c >= 2.0:
            text = f"Very red ({cs}): typical of a cold brown dwarf"
        elif c >= 1.0:
            text = f"Red ({cs}): typical of a brown dwarf"
        elif c >= 0.5:
            text = f"Reddish ({cs}): could be a brown dwarf"
        else:
            text = f"Ordinary colour ({cs}), like most stars"
        add("colour", pts, text)
    elif w2 is not None and w1 is None:
        add("colour", W["colour_w1_missing"] * factor,
            "Not seen in the shorter-wavelength W1 band, so it may be extremely red and cold")

    # Motion: significance and speed
    snr = _num(mover.get("pm_snr"))
    if snr is not None:
        pts = min(max(math.log10(snr), 0.0), W["motion_snr_max"]) if snr > 0 else 0.0
        if snr >= 5:
            add("motion_snr", pts, f"Its motion is {_fmt_count(snr)} times bigger than the measurement error")
        else:
            add("motion_snr", pts, f"Its motion is only {snr:.1f} times the measurement error")
    pm = _num(mover.get("pm"))
    if pm is None:
        a, b = _num(mover.get("pmra")), _num(mover.get("pmdec"))
        pm = math.hypot(a, b) if a is not None and b is not None else None
    if pm is not None:
        pts = min(max(0.75 * math.log10(pm / 150.0), 0.0), W["speed_max"]) if pm > 0 else 0.0
        x = pm / 1000.0
        if x >= 3:
            text = f"Moves {x:.1f}″ a year, faster than almost every star in the sky"
        elif x >= 1:
            text = f"Moves {x:.1f}″ a year, fast for a star"
        else:
            text = f"Moves {x:.2f}″ a year"
        add("speed", pts, text)

    # Visits and time span (one sentence)
    n, span = _num(mover.get("n_visits")), _num(mover.get("span_yr"))
    yrs = _fmt_years(span) if span is not None and span > 0 else None
    if n is not None:
        pts = min(max(math.log2(max(n, 1e-9) / MIN_VISITS), W["visits_min"]), W["visits_max"])
        nv = int(round(n))
        if n < MIN_VISITS:
            text = f"Seen in only {nv} visit{'s' if nv != 1 else ''}, too few to trust its path"
        else:
            text = f"Measured in {nv} visits" + (f" over {yrs}" if yrs else "")
        add("visits", pts, text)
    if span is not None:
        add("span", min(max(W["span_per_yr"] * span, 0.0), 1.0),
            None if n is not None else (f"Followed for {yrs}" if yrs else None))

    # Fit quality
    chi2r = _num(mover.get("chi2r"))
    if chi2r is not None:
        pts = min(max(W["fit_good"] - math.log2(max(chi2r, 1.5) / 1.5), W["fit_min"]), W["fit_good"])
        scatter = math.sqrt(max(chi2r, 0.0))
        if chi2r <= 2.0:
            text = "Its positions line up neatly along a straight path"
        elif chi2r <= ARTEFACT_CHI2R:
            text = f"Its positions scatter {scatter:.1f} times more than expected around a straight path"
        else:
            text = (f"Its positions do not follow a straight path (scatter {scatter:.0f} times the expected), "
                    f"a sign of a false match")
        add("fit", pts, text)

    # Parallax (only when the core fitted it and it is clearly measured)
    plx, plx_err = _num(mover.get("plx")), _num(mover.get("plx_err"))
    if plx is not None and plx_err is not None and plx_err > 0 and plx >= NEARBY_PLX_MAS \
            and plx / plx_err >= NEARBY_PLX_SNR:
        add("parallax", W["parallax_nearby"],
            f"Its parallax ({plx:.0f} mas) puts it about {3261.56 / plx:.0f} light-years away")

    # Brightness (saturation)
    over = max([W1_SATURATION - w1 if w1 is not None else 0.0, W2_SATURATION - w2 if w2 is not None else 0.0])
    if over > 0:
        band, mag = ("W1", w1) if w1 is not None and W1_SATURATION - w1 >= over else ("W2", w2)
        add("brightness", max(W["bright_per_mag"] * over, W["bright_min"]),
            f"Very bright ({band} = {mag:.1f}), so the detector saturates and its positions are less precise")

    # Tile edge
    if near_tile_edge(mover):
        add("tile_edge", W["tile_edge"], "Close to the edge of its survey tile, so part of its path may be cut off")

    # Flags from the core
    flags = [str(f).strip() for f in (mover.get("flags") or []) if str(f).strip()]
    max_charged = int(round(W["flags_min"] / W["flag_each"]))     # only the first 3 flags cost points
    for i, f in enumerate(flags):
        add("flag", W["flag_each"] if i < max_charged else 0.0,
            f"Flagged by the detection step: {f.replace('_', ' ')}")

    # SPHEREx 2025-26 (survey.spherex): a second instrument, years later, at the predicted spot
    sx = mover.get("spherex") if isinstance(mover.get("spherex"), dict) else {}
    if sx.get("checked"):
        off, err = _num(sx.get("offset_arcsec")), _num(sx.get("offset_err"))
        where = f" ({off:.0f}″ ± {err:.0f}″ from the predicted spot)" if off is not None and err is not None else ""
        if sx.get("confirmed"):
            add("spherex", W["spherex_confirmed"],
                f"SPHEREx sees it in 2025–26 where its NEOWISE motion predicts{where}, and gone from its 2014 spot")
        elif sx.get("at_predicted") is True:
            add("spherex", 0.0, f"SPHEREx sees a source where predicted in 2025–26{where}; it moves too little "
                                "for SPHEREx's 13″ pixels to see the motion")
        elif sx.get("at_predicted") is False:
            add("spherex", 0.0, "SPHEREx does not see it where its motion predicts in 2025–26 (a neighbour's "
                                "light in the same pixels, or a wrong motion)")
        elif sx.get("detected") is False:
            add("spherex", 0.0, "Too faint for SPHEREx to see in 2025–26")
        ix = sx.get("indices") if isinstance(sx.get("indices"), dict) else {}
        if ix.get("methane"):
            add("spherex_methane", 0.0, "SPHEREx spectrum: a dip at 3.3 µm like the methane of cold brown dwarfs "
                                        "(a hint, not a classification)")

    # Red flags
    rf = red_flags(mover)
    if rf:
        add("red_flags", W["red_flag"], "Looks like a false detection: " + "; ".join(rf))
    return terms


def score(mover):
    """Interest score (higher = look first) and plain-English reasons, strongest first.

    The score is the sum of these terms (weights in ``WEIGHTS``; c = W1-W2, n = n_visits):

    ============  =============================================  ==========================================
    term          input                                          points
    ============  =============================================  ==========================================
    catalogue     Gaia checked, no counterpart ("unexplained")   +3.0
                  Gaia counterpart with motion                   -3.0
                  Gaia 2-parameter counterpart (no motion)       -2.0
                  not checked                                     0.0
    colour        W1-W2 = c                                      +1.0 x clip(c - 0.2, 0, 3)     (0 ... +3)
                  W2 measured, no W1                             +1.5
                  (either one when W1 < 8.0 or W2 < 6.7)         x 0.5 (saturated colours are unreliable)
    motion_snr    pm_snr                                         clip(log10(pm_snr), 0, 2.5)
    speed         pm (mas/yr)                                    clip(0.75 x log10(pm / 150), 0, 1)
    visits        n_visits                                       clip(log2(n / 6), -2, +1.5)
    span          span_yr                                        clip(0.1 x span_yr, 0, 1)
    fit           chi2r                                          clip(0.5 - log2(max(chi2r, 1.5) / 1.5), -4, 0.5)
    parallax      plx >= 50 mas and plx / plx_err >= 5           +0.5
    brightness    magnitudes brighter than W1 8.0 / W2 6.7       -0.5 per mag, down to -2
    tile_edge     path over 2014-2024 could reach the tile edge  -0.5
    flag          each flag set by the core                      -0.5, down to -1.5 in all
    red_flags     any of red_flags(mover)                        -2.0 (once)
    spherex       SPHEREx 2025-26 confirms the motion             +0.5 (at the predicted spot, motion seen,
                  (spherex.confirmed)                                   gone from the 2014 spot)
                  seen where predicted but too slow to confirm,    0.0 (reason only)
                  not where predicted, or too faint
    spherex_methane  SPHEREx 3.3 um methane hint                   0.0 (reason only)
    ============  =============================================  ==========================================

    SPHEREx never costs points: with ~13" pixels a neighbour's light can hide or shift a faint mover, so "not
    seen where predicted" is reported but not held against it.

    Monotonic by construction: more visits, a longer span, a redder colour and a higher pm_snr never lower the
    score; a Gaia match, a higher chi2r, more saturation and more flags never raise it. A faster motion never
    lowers it either, except that above 15"/yr (faster than any known star) the red flag applies, and a faster
    mover can reach its tile's edge (-0.5). A missing value adds nothing. Ranges: about -15 to +13.
    Returns ``(score rounded to 3 decimals, reasons)``.
    """
    terms = score_terms(mover)
    total = round(sum(t["points"] for t in terms), 3) + 0.0
    ordered = sorted((t for t in terms if t["reason"]), key=lambda t: -abs(t["points"]))  # stable sort
    return total, [t["reason"] for t in ordered]


def classify(mover) -> str:
    """"known (Gaia)" when Gaia has it; else "likely artefact" when ``red_flags`` finds any (very poor straight-
    line fit, fewer than 6 visits, very bright with an unsteady path, motion not significant, less than a year,
    faster than any known star, or an artefact flag from the core); else "not checked" when Gaia could not be
    queried; else "unexplained"."""
    g = mover.get("gaia") if isinstance(mover.get("gaia"), dict) else {}
    if g.get("checked") and g.get("match"):
        return "known (Gaia)"
    if red_flags(mover):
        return "likely artefact"
    if not g.get("checked"):
        return "not checked"
    return "unexplained"


def _rank_key(row):
    snr = _num(row.get("pm_snr"))
    return (-row["score"], -snr if snr is not None else math.inf, _id_key(row))


def rank(movers, top=1000) -> list:
    """Score and classify movers and return the best ``top`` (all when ``top`` is None) as new dicts sorted by
    score (desc), then pm_snr (desc), then id, each with ``score``, ``reasons``, ``class`` and ``rank`` (1 = first)
    added, and ``gaia`` filled in as not checked when it was missing. The input movers are not modified."""
    rows = []
    for m in movers or []:
        r = dict(m)
        if not isinstance(r.get("gaia"), dict):
            r["gaia"] = _gaia_unchecked()
        r["score"], r["reasons"] = score(r)
        r["class"] = classify(r)
        rows.append(r)
    rows.sort(key=_rank_key)
    if top is not None:
        rows = rows[:max(0, int(top))]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
