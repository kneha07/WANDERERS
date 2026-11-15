"""Which SPHEREx releases NASA IRSA serves, and how fresh the prepared targets in app/data/ are.

    python pipeline/spherex_releases.py                    # check IRSA, write app/data/spherex_release.json
    python pipeline/spherex_releases.py check --github-output "$GITHUB_OUTPUT"
    python pipeline/spherex_releases.py targets --write-defs   # prepared target ids, one per line
    python pipeline/spherex_releases.py synced --since 2026-11-15T06:00:00Z   # after fetch.py + analyze.py

`check` asks IRSA for its SPHEREx image collections (astroquery's Irsa.list_collections(servicetype="SIA",
filter="spherex"); if astroquery fails, the same question straight to IRSA TAP) and writes
app/data/spherex_release.json:

  releases          the SPHEREx releases IRSA serves, oldest data first (name, label, description when known).
                    pipeline/fetch.py searches them in this order and keeps the first copy of an exposure.
  current           the newest release (the last one).
  checked           when IRSA last answered this check (UTC). null if it never has.
  synced            when the prepared targets were last rebuilt (`synced` command; at first from git).
  data_through      the newest SPHEREx observation date in app/data/<target>/target.json (metadata and frames;
                    nothing is downloaded for this).
  new_release_available / new_releases / targets_behind
                    a release newer than the ones a prepared target was built from is available at IRSA.
  last_attempt, error
                    the latest try and, when it failed, why.

IRSA is often down or answers 502. Then (from the command line) the check lists NASA IRSA's public SPHEREx bucket
instead (s3://nasa-irsa-spherex, anonymous): its top-level release folders (dr1/, qr2/, qr3/, ...) and the newest
level2 half-week folder of each (pipeline/spherex_s3.py). Releases another one replaced are left out (SUPERSEDED_BY:
qr2 is the Quick Release that DR1 reprocessed); any other folder, such as a future dr2/ or qr4/, is a release. The
file then says `checked_via: "S3 bucket"`, `checked` is the time of that listing, and each release entry gets its
newest week (`newest_week`, e.g. 2026W40_2A, "2026 week 40"); `error` still says why IRSA could not be asked.

When IRSA and the bucket both fail (network, timeout, an answer that is not a collection list) the last known file is
kept and only `last_attempt` and `error` change; the script still exits 0. With no usable file yet, it writes one
from what is known locally (fetch.py's built-in release list, dates from the target data) and says that the online
check failed. Good data is never replaced by an empty or broken answer.

Only the standard library is imported at module level, so pipeline/fetch.py can use load_release_names()
cheaply; astroquery and astropy are imported when IRSA is asked.
"""
import argparse
import ast
import csv
import io
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"
CACHE = ROOT / "data" / "cache"
STATUS_FILE = DATA / "spherex_release.json"
FETCH_PY = Path(__file__).resolve().parent / "fetch.py"

# A Level-2 image release: spherex_dr1, spherex_qr3, ... The deep-field and cube collections (spherex_dr1_deep,
# spherex_qr3_deep, spherex_dr1_cube) are other products: listed under other_collections, not searched by fetch.py.
RELEASE_RE = re.compile(r"^spherex_(dr|qr)(\d{1,3})\Z")     # \Z, not $: "spherex_qr3\n" is not a release name
KINDS = {"dr": "Data Release", "qr": "Quick Release"}
# Used only when neither app/data/spherex_release.json nor pipeline/fetch.py gives a list.
LAST_RESORT_RELEASES = ["spherex_dr1", "spherex_qr3"]

# What we know about releases from our own research notes (they cite the IRSA SPHEREx pages and our SIA queries).
# IRSA's collection list gives names only, so these are the only descriptions; a release not listed here has none.
NOTES_SOURCE = "docs/research/spherex-data-access.md (IRSA SPHEREx pages and SIA queries, 2026-11-14)"
NOTES = {
    "spherex_dr1": "Data Release 1 (Nov 2026): the reprocessed Quick Release 2 images. On 2026-11-14 its images "
                   "spanned 2025-04-24 to 2026-05-14.",
    "spherex_qr3": "Quick Release 3 (Sep 2026): images from 2026-05-16 on. IRSA adds new images every week.",
}

SOURCE_ASTROQUERY = "IRSA SIA collection list (astroquery Irsa.list_collections, servicetype SIA, filter spherex)"
SOURCE_TAP = "IRSA TAP (caom.observation: image collections whose name starts with spherex)"
SOURCE_LOCAL = "pipeline/fetch.py built-in list (the online check failed: IRSA gave no usable answer)"
SOURCE_S3 = ("NASA IRSA's SPHEREx S3 bucket (s3://nasa-irsa-spherex): top-level release folders and their newest "
             "level2 week, listed because IRSA's SIA and TAP services did not answer")
VIA_IRSA, VIA_S3 = "IRSA", "S3 bucket"
SYNCED_FROM_GIT = "git: the last commit that changed app/data/<target>/target.json"
SEARCHED_SOURCE = ("data/cache/<target>/<release>_sia.xml: the IRSA answers fetch.py saved for each target, or "
                   "<release>_s3.json when fetch.py searched the S3 bucket's image index instead (IRSA down)")

# Bucket folders of releases that another release reprocessed and replaced. They are not searched and never count as
# new data. IRSA: "DR1 = reprocessed QR2", and QR2 "is not searchable after DR1" (docs/research/spherex-data-access.md;
# QR1 was retired in Feb 2026). A release is left out only when the release that replaced it is in the bucket too.
SUPERSEDED_BY = {"spherex_qr1": "spherex_dr1", "spherex_qr2": "spherex_dr1"}

TAP_SYNC = "https://irsa.ipac.caltech.edu/TAP/sync"
# The query astroquery's list_collections(servicetype="SIA") runs, narrowed to SPHEREx so it stays small.
TAP_QUERY = ("SELECT DISTINCT o.collection FROM caom.observation o JOIN caom.plane p ON o.obsid = p.obsid "
             "WHERE (p.dataproducttype = 'image' OR p.dataproducttype = 'cube') "
             "AND o.collection LIKE 'spherex%' ORDER BY o.collection")
TIMEOUT_S = 120

# Fields whose change is worth a pull request. Timestamps of a routine check are not.
CHANGE_KEYS = ("current", "releases", "other_collections", "used_releases", "new_release_available",
               "new_releases", "targets_behind", "data_through")


class IrsaAnswerError(ValueError):
    """IRSA answered, but not with a usable list of SPHEREx collections."""


class IrsaUnavailable(RuntimeError):
    """IRSA could not be asked: network error, HTTP error, timeout or an unusable answer."""


# ---------------------------------------------------------------- release names ----------------------------------

def is_release(name):
    return isinstance(name, str) and RELEASE_RE.match(name) is not None


def release_key(name):
    """Sort key, oldest data first: data releases (reprocessed earlier quick-release data) before quick releases,
    each by number. This is the order fetch.py has always used (spherex_dr1, then spherex_qr3)."""
    m = RELEASE_RE.match(name)
    return (0 if m.group(1) == "dr" else 1, int(m.group(2)))


def order_releases(names):
    """Unique release names, oldest first. Anything that is not a release name is dropped."""
    return sorted({n for n in names if is_release(n)}, key=release_key)


def release_label(name):
    m = RELEASE_RE.match(name)
    return f"SPHEREx {KINDS[m.group(1)]} {int(m.group(2))}"


def release_entry(name):
    e = {"name": name, "label": release_label(name)}
    if name in NOTES:
        e["description"] = NOTES[name]
        e["description_source"] = NOTES_SOURCE
    return e


def sia_cache_name(release):
    """File name fetch.py caches a release's SIA answer under, in data/cache/<target>/. spherex_dr1 keeps the
    name it had before more releases were searched, so existing caches are still found."""
    return "spherex_sia.xml" if release == "spherex_dr1" else f"{release}_sia.xml"


def s3_answer_name(release):
    """File name of the search answer fetch.py writes in data/cache/<target>/ when it found a release's images in the
    S3 bucket's image index instead of IRSA SIA (pipeline/spherex_s3.py)."""
    return f"{release}_s3.json"


def release_of_cache_file(name):
    """The release a cached search answer belongs to (inverse of sia_cache_name and s3_answer_name), or None."""
    if name == "spherex_sia.xml":
        return "spherex_dr1"
    for end in ("_sia.xml", "_s3.json"):
        if name.endswith(end):
            rel = name[: -len(end)]
            return rel if is_release(rel) else None
    return None


# ---------------------------------------------------------------- IRSA answers -----------------------------------

def _clean(v):
    """A collection name from a table cell (str, bytes, numpy scalar or masked), lower-case, or None."""
    if v is None:
        return None
    if "numpy" in sys.modules and sys.modules["numpy"].ma.is_masked(v):
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    s = str(v).strip().strip('"').lower()
    return s or None


def _names_from_votable(text):
    if re.search(r'name\s*=\s*"QUERY_STATUS"\s+value\s*=\s*"ERROR"', text, re.I):
        msg = re.search(r'name\s*=\s*"QUERY_STATUS"[^>]*>([^<]*)<', text, re.I)
        raise IrsaAnswerError("IRSA TAP reported an error" + (f": {msg.group(1).strip()[:160]}" if msg else ""))
    import warnings
    from astropy.io.votable import parse_single_table
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = parse_single_table(io.BytesIO(text.encode("utf-8"))).to_table()
    except Exception as e:  # noqa: BLE001 - any parser failure means the answer is unusable
        raise IrsaAnswerError(f"unreadable VOTable ({type(e).__name__})") from None
    return _names_from_table(table)


def _names_from_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "collection" not in [c.strip().lower() for c in rows[0]]:
        raise IrsaAnswerError("the answer has no 'collection' column")
    k = [c.strip().lower() for c in rows[0]].index("collection")
    return [r[k] for r in rows[1:] if len(r) > k]


def _names_from_table(table):
    cols = [c.lower() for c in getattr(table, "colnames", [])]
    if "collection" not in cols:
        raise IrsaAnswerError("the answer has no 'collection' column")
    col = table.colnames[cols.index("collection")]
    return list(table[col])


def parse_collections(answer):
    """Turn an IRSA answer into (releases, other_collections).

    `answer` is what astroquery's list_collections returns (an astropy Table with a `collection` column), a plain
    list of names, or the raw bytes/text of an IRSA TAP answer (VOTable or CSV). releases is a list of release
    entries, oldest first; other_collections are the other SPHEREx collections (deep fields, cubes). Raises
    IrsaAnswerError for an answer that holds no SPHEREx release (an error page, an empty table, ...)."""
    if isinstance(answer, (bytes, bytearray)):
        answer = bytes(answer).decode("utf-8", "replace")
    if isinstance(answer, str):
        text = answer.lstrip("﻿ \t\r\n")
        if not text:
            raise IrsaAnswerError("empty answer")
        if text.startswith("<"):
            if "<votable" not in text[:2000].lower():
                raise IrsaAnswerError("not a VOTable (an error page?)")
            raw = _names_from_votable(text)
        else:
            raw = _names_from_csv(text)
    elif isinstance(answer, (list, tuple)):
        raw = list(answer)
    elif answer is not None and hasattr(answer, "colnames"):
        raw = _names_from_table(answer)
    else:
        raise IrsaAnswerError(f"unexpected answer type {type(answer).__name__}")
    names = [n for n in (_clean(v) for v in raw) if n and n.startswith("spherex")]
    releases = order_releases(names)
    if not releases:
        raise IrsaAnswerError("IRSA listed no SPHEREx image release")
    other = sorted({n for n in names if not is_release(n) and re.fullmatch(r"[a-z0-9_]{1,64}", n)})
    return [release_entry(n) for n in releases], other


def _short(e):
    s = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    s = re.sub(r"https?://\S+", "<IRSA>", s)
    return s[:200]


def _with_timeout(fn, timeout):
    """Run fn() in a daemon thread; give up after `timeout` seconds (astroquery has no timeout of its own)."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - handed back to the caller
            box["error"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise IrsaUnavailable(f"no answer within {timeout:.0f} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _astroquery_list():
    from astroquery.ipac.irsa import Irsa
    return Irsa.list_collections(servicetype="SIA", filter="spherex")


def _tap_get(timeout):
    import requests
    r = requests.get(TAP_SYNC, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": TAP_QUERY},
                     timeout=timeout, headers={"User-Agent": "wanderers-spaceapps/0.1"})
    if r.status_code != 200:
        raise IrsaUnavailable(f"IRSA TAP answered HTTP {r.status_code}")
    return r.content


def discover(list_collections=_astroquery_list, tap_get=_tap_get, timeout=TIMEOUT_S):
    """Ask IRSA which SPHEREx collections it serves. Returns (releases, other_collections, source).
    Tries astroquery first, then IRSA TAP directly. Raises IrsaUnavailable when neither gives a usable list."""
    errors = []
    if list_collections is not None:
        try:
            rel, other = parse_collections(_with_timeout(list_collections, timeout))
            return rel, other, SOURCE_ASTROQUERY
        except Exception as e:  # noqa: BLE001 - every failure falls through to TAP
            errors.append(f"astroquery: {_short(e)}")
    if tap_get is not None:
        try:
            rel, other = parse_collections(_with_timeout(lambda: tap_get(timeout), timeout + 5))
            return rel, other, SOURCE_TAP
        except Exception as e:  # noqa: BLE001
            errors.append(f"TAP: {_short(e)}")
    raise IrsaUnavailable("; ".join(errors) or "no way to ask IRSA")


# ---------------------------------------------------------------- the S3 bucket ----------------------------------

def releases_from_bucket(folders, newest=None):
    """What the bucket's release folders say: (release entries oldest first, {superseded: replaced by}).

    folders: top-level folder names ('dr1', 'qr2', 'qr3', ...; others are ignored). newest: {folder: newest level2
    week folder}. A folder in SUPERSEDED_BY is left out when the release that replaced it is there too; every other
    release folder counts, including ones we have never seen (a new dr2/ or qr4/ is new data). Raises IrsaAnswerError
    when no release folder is left."""
    newest = newest or {}
    names = order_releases(f"spherex_{f}" for f in folders if isinstance(f, str))
    superseded = {n: SUPERSEDED_BY[n] for n in names if n in SUPERSEDED_BY and SUPERSEDED_BY[n] in names}
    keep = [n for n in names if n not in superseded]
    if not keep:
        raise IrsaAnswerError("the S3 bucket has no SPHEREx release folder")
    entries = []
    for n in keep:
        e = release_entry(n)
        week = newest.get(n[len("spherex_"):])
        if week:
            spherex_s3 = _s3_module()
            e["newest_week"] = week
            e["newest_week_label"] = spherex_s3.week_label(week)
            e["newest_week_ends"] = spherex_s3.week_end(week)
        entries.append(e)
    return entries, superseded


def _s3_module():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import spherex_s3
    return spherex_s3


def discover_s3(reader=None, now=None):
    """List NASA IRSA's SPHEREx bucket (anonymous S3). Returns a dict: releases (entries with newest weeks),
    superseded, folders, newest_weeks, listed (UTC time the listing finished). Raises on any failure."""
    spherex_s3 = _s3_module()
    reader = reader or spherex_s3.S3Reader(tries=3, timeout=30)
    folders = spherex_s3.release_folders(reader)
    newest = spherex_s3.newest_weeks(reader, folders)
    entries, superseded = releases_from_bucket(folders, newest)
    return {"releases": entries, "superseded": superseded, "folders": folders, "newest_weeks": newest,
            "listed": now() if callable(now) else (now or now_utc())}


def bucket_summary(info):
    """The `s3_listing` part of the status file."""
    return {"bucket": "s3://nasa-irsa-spherex (us-east-1, anonymous)", "listed": info.get("listed"),
            "folders": list(info.get("folders") or []), "superseded": dict(info.get("superseded") or {}),
            "newest_weeks": dict(info.get("newest_weeks") or {})}


# ---------------------------------------------------------------- local facts ------------------------------------

def year_to_date(year):
    """Decimal (Julian) year, as analyze.py stores frame epochs, to a UTC date."""
    return (datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=(float(year) - 2000.0) * 365.25)).date()


def _parse_day(s):
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def newest_observation(t):
    """Newest SPHEREx observation date in one target.json: the image dates in `metadata` (every SPHEREx image
    used) and the epochs of SPHEREx frames and stacks. None if it has neither."""
    days = [d for d in (_parse_day(m.get("date")) for m in t.get("metadata") or [] if isinstance(m, dict)) if d]
    for group in ("frames", "stacks"):
        for frames in (t.get(group) or {}).values():
            for f in frames if isinstance(frames, list) else []:
                if not isinstance(f, dict) or f.get("mission") != "SPHEREx":
                    continue
                y = f.get("year")
                if isinstance(y, (int, float)) and 2000 < y < 2200:
                    days.append(year_to_date(y))
    return max(days) if days else None


def prepared_targets(data_dir=DATA):
    """Ids of the prepared targets: every app/data/<id>/ with a target.json."""
    return sorted(p.parent.name for p in Path(data_dir).glob("*/target.json"))


def data_through(data_dir=DATA):
    """(newest SPHEREx observation date over all prepared targets, {target: date}), dates as YYYY-MM-DD.
    A target.json that cannot be read is skipped."""
    by_target = {}
    for tid in prepared_targets(data_dir):
        try:
            t = json.loads((Path(data_dir) / tid / "target.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        d = newest_observation(t) if isinstance(t, dict) else None
        if d:
            by_target[tid] = d.isoformat()
    return (max(by_target.values()) if by_target else None), by_target


def s3_answer_complete(path):
    """True when an S3 search answer (<release>_s3.json) says the image index covered every week folder of the
    release in the bucket. A search of a partial index does not count as having searched the release."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(d, dict) and d.get("index_complete") is True


def searched_releases(cache_dir, targets):
    """{target: [releases fetch.py searched]} from the search answers cached in data/cache/<target>/: IRSA SIA answers
    (<release>_sia.xml) and complete S3-index answers (<release>_s3.json). Targets with no cache folder are left out
    (nothing is known about them here)."""
    out = {}
    for tid in targets:
        d = Path(cache_dir) / tid
        if not d.is_dir():
            continue
        files = list(d.glob("*_sia.xml")) + [p for p in d.glob("*_s3.json") if s3_answer_complete(p)]
        out[tid] = order_releases(r for r in (release_of_cache_file(p.name) for p in files) if r)
    return out


def releases_behind(known, searched, used, targets):
    """{target: [known releases newer than the newest one its data came from]}. A target with no record of its
    own uses `used` (the releases of the last rebuild). A data release numbered above the newest data release the
    target was built from is new too (DR2 after DR1), although data releases sort before the quick releases."""
    rank = {n: i for i, n in enumerate(known)}
    behind = {}
    for tid in targets:
        mine = [r for r in (searched.get(tid) or used or []) if r in rank]
        top = max((rank[r] for r in mine), default=-1)
        top_dr = max((release_key(r)[1] for r in mine if release_key(r)[0] == 0), default=None)
        newer = [n for n in known if rank[n] > top
                 or (top_dr is not None and release_key(n)[0] == 0 and release_key(n)[1] > top_dr)]
        if newer:
            behind[tid] = newer
    return behind


def git_last_commit(root=ROOT, run=subprocess.run):
    """UTC time of the last commit that changed a prepared target's target.json, or None (no git, no history)."""
    try:
        r = run(["git", "log", "-1", "--format=%cI", "--", "app/data/*/target.json"], cwd=str(root),
                capture_output=True, text=True, timeout=30)
        s = (r.stdout or "").strip()
        if r.returncode != 0 or not s:
            return None
        return iso(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def fetch_fallback_releases(fetch_py=FETCH_PY):
    """FALLBACK_RELEASES as written in pipeline/fetch.py, read without importing it (fetch.py imports astropy,
    pyvo and numpy). Falls back to LAST_RESORT_RELEASES when the file or the assignment is missing."""
    try:
        tree = ast.parse(Path(fetch_py).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FALLBACK_RELEASES" for t in node.targets):
                names = [n for n in ast.literal_eval(node.value) if is_release(n)]
                if names:
                    return names
    except (OSError, SyntaxError, ValueError):
        pass
    return list(LAST_RESORT_RELEASES)


# ---------------------------------------------------------------- the status file --------------------------------

def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc():
    return iso(datetime.now(timezone.utc))


def read_status(path=None):
    """The status file as a dict, or None when it is missing, unreadable or has no release list."""
    try:
        d = json.loads(Path(path or STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("releases"), list):
        return None
    if not [r for r in d["releases"] if is_release(r.get("name") if isinstance(r, dict) else r)]:
        return None
    return d


def load_release_names(path=None, fallback=None):
    """Release names for fetch.py, in the file's order (the first listed wins for a duplicate exposure). Uses
    `fallback` (fetch.py's built-in list) when the file is missing, broken or lists no valid release."""
    d = read_status(path)
    names = []
    for r in (d or {}).get("releases", []):
        n = r.get("name") if isinstance(r, dict) else r
        if is_release(n) and n not in names:
            names.append(n)
    return names or list(fallback if fallback is not None else LAST_RESORT_RELEASES)


def write_status(status, path=None):
    """Write atomically: a killed run never leaves a half-written file."""
    path = Path(path or STATUS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def build_status(release_names, *, releases=None, releases_source, other=(), previous=None, checked=None,
                 now=None, error=None, data_dir=DATA, cache_dir=None, synced=None, synced_source=None,
                 git=git_last_commit, checked_via=None, s3_listing=None):
    """The status dict. `previous` (the last file) supplies what this run cannot see: the sync time, and which
    releases each target was built from when there is no cache here (as on a fresh CI runner). checked_via says what
    answered the check ("IRSA" or "S3 bucket"); s3_listing what the bucket listing found (S3 checks only)."""
    prev = previous or {}
    now = now or now_utc()
    names = order_releases(release_names)
    by_name = {r["name"]: r for r in (releases or [])}
    entries = [by_name.get(n) or release_entry(n) for n in names]
    through, by_target = data_through(data_dir)
    targets = prepared_targets(data_dir)

    searched = {t: v for t, v in (prev.get("searched_releases") or {}).items() if t in targets and isinstance(v, list)}
    if cache_dir is not None and Path(cache_dir).is_dir():
        searched.update(searched_releases(cache_dir, targets))
    if searched:
        used = order_releases(r for v in searched.values() for r in v)
    else:
        used = [r for r in (prev.get("used_releases") or []) if is_release(r)] or fetch_fallback_releases()
    behind = releases_behind(names, searched, used, targets)
    new = [n for n in names if any(n in v for v in behind.values())]

    if synced is None:
        synced, synced_source = prev.get("synced"), prev.get("synced_source")
        if not synced:
            synced, synced_source = git(), SYNCED_FROM_GIT
            if not synced:
                synced_source = None
    status = {
        "about": "SPHEREx releases at NASA IRSA and how recent WANDERERS' prepared targets are. Written by "
                 "pipeline/spherex_releases.py; read by app/release.js and pipeline/fetch.py.",
        "current": names[-1],
        "current_label": release_label(names[-1]),
        "releases": entries,
        "releases_source": releases_source,
        "other_collections": sorted(set(other)),
        "new_release_available": bool(new),
        "new_releases": [{"name": n, "label": release_label(n)} for n in new],
        "targets_behind": behind,
        "targets": len(targets),
        "data_through": through,
        "data_through_by_target": by_target,
        "synced": synced,
        "synced_source": synced_source,
        "checked": checked if checked is not None else prev.get("checked"),
        "checked_via": checked_via if checked is not None else prev.get("checked_via"),
        "last_attempt": now,
        "error": error,
        "used_releases": used,
        "searched_releases": searched,
        "searched_source": SEARCHED_SOURCE,
    }
    listing = s3_listing if checked is not None else prev.get("s3_listing")
    if listing and status["checked_via"] == VIA_S3:
        status["s3_listing"] = listing
    if "rebuilt_targets" in prev:
        status["rebuilt_targets"] = prev["rebuilt_targets"]
    if "not_rebuilt" in prev:
        status["not_rebuilt"] = prev["not_rebuilt"]
    return status


def meaningful_change(old, new):
    """True when `new` says something `old` did not: another release list, a new release, other data dates, or the
    first successful check after failed ones. A routine check (only `checked` and `last_attempt` moved) is not."""
    if old is None:
        return True
    if any(old.get(k) != new.get(k) for k in CHANGE_KEYS):
        return True
    return bool(old.get("error")) and not new.get("error")


def check(path=None, *, data_dir=DATA, cache_dir=None, now=None, ask=None, s3=None, git=git_last_commit,
          report=None):
    """One release check. Returns (status, changed, online); online means IRSA answered. Never raises for an IRSA
    failure. s3 (optional): a callable that lists the S3 bucket (discover_s3), tried when IRSA fails; the command
    line passes it. report (optional dict) gets "via": "IRSA", "S3 bucket" or None (both failed)."""
    now = now or now_utc()
    report = report if report is not None else {}
    previous = read_status(path)
    try:
        releases, other, source = (ask or discover)()
    except Exception as e:  # noqa: BLE001 - any failure: keep what we have
        err = f"IRSA release check failed on {now[:10]}: {_short(e)}"
        if s3 is not None:
            try:
                info = s3()
                prev = previous or {}
                status = build_status([r["name"] for r in info["releases"]], releases=info["releases"],
                                      releases_source=SOURCE_S3, other=prev.get("other_collections") or (),
                                      previous=previous, checked=info.get("listed") or now, now=now, error=err,
                                      data_dir=data_dir, cache_dir=cache_dir, git=git, checked_via=VIA_S3,
                                      s3_listing=bucket_summary(info))
                changed = meaningful_change(previous, status)
                write_status(status, path)
                report["via"] = VIA_S3
                return status, changed, False
            except Exception as e2:  # noqa: BLE001 - the bucket failed too: as before, keep what we have
                err += f"; S3 bucket listing failed too: {_short(e2)}"
        report["via"] = None
        if previous is not None:
            previous["last_attempt"], previous["error"] = now, err
            write_status(previous, path)
            return previous, False, False
        status = build_status(fetch_fallback_releases(), releases_source=SOURCE_LOCAL, previous=None, checked=None,
                              now=now, error=err, data_dir=data_dir, cache_dir=cache_dir, git=git)
        write_status(status, path)
        return status, True, False
    status = build_status([r["name"] for r in releases], releases=releases, releases_source=source, other=other,
                          previous=previous, checked=now, now=now, error=None, data_dir=data_dir,
                          cache_dir=cache_dir, git=git, checked_via=VIA_IRSA)
    changed = meaningful_change(previous, status)
    write_status(status, path)
    report["via"] = VIA_IRSA
    return status, changed, True


def mark_synced(path=None, *, since=None, data_dir=DATA, cache_dir=CACHE, now=None, git=git_last_commit):
    """After fetch.py and analyze.py rebuilt the prepared targets: record the sync time, which releases each target
    was searched in (from the fresh cache) and the new data dates. A target counts as rebuilt when its target.json
    was written at or after `since` (ISO time); `synced` moves only if at least one was. Returns (status, rebuilt)."""
    now = now or now_utc()
    previous = read_status(path) or {}
    targets = prepared_targets(data_dir)
    if since:
        t0 = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
        rebuilt = [t for t in targets if (Path(data_dir) / t / "target.json").stat().st_mtime >= t0 - 1]
    else:
        rebuilt = list(targets)
    names = load_release_names(path, fallback=fetch_fallback_releases())
    kw = {}
    if rebuilt:
        kw = {"synced": now, "synced_source": f"pipeline/spherex_releases.py synced: fetch.py and analyze.py "
                                              f"rebuilt {len(rebuilt)} of {len(targets)} prepared targets"}
    status = build_status(names, releases=[r for r in previous.get("releases") or [] if isinstance(r, dict)],
                          releases_source=previous.get("releases_source") or SOURCE_LOCAL,
                          other=previous.get("other_collections") or (), previous=previous,
                          checked=previous.get("checked"), now=previous.get("last_attempt") or now,
                          error=previous.get("error"), data_dir=data_dir, cache_dir=cache_dir, git=git,
                          checked_via=previous.get("checked_via"), s3_listing=previous.get("s3_listing"), **kw)
    if rebuilt:
        status["rebuilt_targets"] = rebuilt
        status["not_rebuilt"] = [t for t in targets if t not in rebuilt]
    write_status(status, path)
    return status, rebuilt


def target_definition(t):
    """A data/cache/<id>/target_def.json for a prepared user-position target, rebuilt from its target.json, so
    fetch.py and analyze.py can redo it on a machine without the original cache (a CI runner). A Gaia DR3
    reference becomes its Gaia source id; any other reference is kept as literature values."""
    ref = t.get("reference") or {}
    d = {"name": t["name"], "kind": t.get("kind") or t["name"], "story": t.get("story") or "explore"}
    if t.get("teaser"):
        d["teaser"] = t["teaser"]
    if t.get("fov_arcsec"):
        d["fov_arcsec"] = int(round(float(t["fov_arcsec"])))
    if ref.get("source") == "Gaia DR3" and ref.get("source_id"):
        d["gaia_source_id"] = int(ref["source_id"])
    else:
        d["literature"] = {k: ref.get(k) for k in ("ra", "dec", "epoch", "pmra", "pmdec", "parallax")}
        for k in ("pmra", "pmdec"):
            d["literature"][k] = d["literature"][k] or 0.0
        d["literature"]["epoch"] = d["literature"]["epoch"] or 2016.0
        d["literature"]["ref"] = ref.get("source") or "WANDERERS target.json reference"
    return d


def write_target_defs(data_dir=DATA, cache_dir=CACHE, builtin=None):
    """Write target_def.json for prepared targets that are not built into targets.py and have none yet.
    Existing definitions are never overwritten. Returns the ids written."""
    if builtin is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from targets import TARGETS
        builtin = set(TARGETS)
    written = []
    for tid in prepared_targets(data_dir):
        f = Path(cache_dir) / tid / "target_def.json"
        if tid in builtin or f.exists():
            continue
        try:
            t = json.loads((Path(data_dir) / tid / "target.json").read_text(encoding="utf-8"))
            d = target_definition(t)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=1), encoding="utf-8")
        written.append(tid)
    return written


# ---------------------------------------------------------------- command line -----------------------------------

def _github_output(path, **kv):
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in kv.items():
            fh.write(f"{k}={str(v).lower() if isinstance(v, bool) else v}\n")


def summary(status):
    names = [r.get("name") if isinstance(r, dict) else r for r in status.get("releases") or []]
    lines = [f"current release: {status.get('current_label')} ({status.get('current')})",
             f"known releases:  {', '.join(map(str, names))}  [{status.get('releases_source')}]",
             f"data through:    {status.get('data_through')}  ({status.get('targets')} prepared targets)",
             f"last synced:     {status.get('synced')}",
             f"checked:         {status.get('checked')}"
             + (f"  (via {status['checked_via']})" if status.get("checked_via") else "")]
    for r in status.get("releases") or []:
        if isinstance(r, dict) and r.get("newest_week_label"):
            lines.append(f"{str(r.get('label') or r.get('name')).replace('SPHEREx ', '')} at IRSA has images "
                         f"through {r['newest_week_label']} (S3 folder {r['newest_week']})")
    if status.get("new_release_available"):
        lines.append(f"NEW DATA: {', '.join(r.get('name', '?') for r in status.get('new_releases') or [])} not yet in "
                     f"{len(status.get('targets_behind') or {})} of {status.get('targets')} targets")
    if status.get("error"):
        lines.append(f"note: {status['error']}")
    return "\n".join(lines)


def title(status):
    """One line for a commit or pull request title."""
    t = f"SPHEREx data: {status.get('current_label') or status.get('current')}"
    if status.get("data_through"):
        t += f", data through {status['data_through']}"
    return t


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", nargs="?", default="check", choices=("check", "synced", "targets", "show"))
    p.add_argument("--file", default=str(STATUS_FILE), help="status file (default app/data/spherex_release.json)")
    p.add_argument("--data", default=str(DATA), help="prepared targets folder (default app/data)")
    p.add_argument("--cache", default=None, help="fetch.py cache folder, to see which releases each target was "
                                                  "searched in (default data/cache when it exists)")
    p.add_argument("--github-output", default=None, help="append key=value lines for GitHub Actions")
    p.add_argument("--require-online", action="store_true", help="check: exit 1 when IRSA could not be asked "
                                                                    "(an S3 bucket listing does not count)")
    p.add_argument("--no-s3", action="store_true", help="check: do not list the S3 bucket when IRSA is down")
    p.add_argument("--since", default=None, help="synced: count targets whose target.json was written after this")
    p.add_argument("--write-defs", action="store_true", help="targets: restore missing target_def.json files")
    p.add_argument("--title", action="store_true", help="show: print a one-line title instead of the summary")
    a = p.parse_args(argv)
    cache = Path(a.cache) if a.cache else (CACHE if CACHE.is_dir() else None)

    if a.command == "show":
        status = read_status(a.file)
        if status is None:
            print("no usable status file", file=sys.stderr)
            return 1
        print(title(status) if a.title else summary(status))
        return 0
    if a.command == "targets":
        if a.write_defs:
            for tid in write_target_defs(a.data, cache or CACHE):
                print(f"restored data/cache/{tid}/target_def.json", file=sys.stderr)
        print("\n".join(prepared_targets(a.data)))
        return 0
    if a.command == "synced":
        status, rebuilt = mark_synced(a.file, since=a.since, data_dir=a.data, cache_dir=cache or CACHE)
        print(summary(status))
        print(f"rebuilt: {', '.join(rebuilt) or 'none (synced time not changed)'}")
        if a.github_output:
            _github_output(a.github_output, rebuilt=len(rebuilt))
        return 0
    report = {}
    status, changed, online = check(a.file, data_dir=a.data, cache_dir=cache, s3=None if a.no_s3 else discover_s3,
                                    report=report)
    print(summary(status))
    print(f"changed: {changed}  online: {online}  answered by: {report.get('via') or 'nobody (IRSA and S3 failed)'}")
    if a.github_output:
        _github_output(a.github_output, new_release=bool(status.get("new_release_available")) and online,
                       changed=changed and online,
                       online="ok" if online else ("s3" if report.get("via") == VIA_S3 else "failed"),
                       current=status["current"])
    return 1 if a.require_online and not online else 0


if __name__ == "__main__":
    sys.exit(main())
