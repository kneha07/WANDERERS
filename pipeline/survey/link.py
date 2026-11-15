"""Core of the WANDERERS sky survey: NEOWISE detections -> visits -> per-visit sources -> tracks -> motions -> movers.

Pipeline for one HEALPix order-5 tile (`process_tile`), year by year so memory stays low:

1. Quality cuts (`tiles.good_mask`) and a split of the detections into visits (`split_visits`): NEOWISE sees a
   field for ~1-2 days every ~6 months, so a gap of > 20 days starts a new visit; near the ecliptic poles,
   where coverage is continuous, a long stretch is cut into windows of <= 12 days.
2. Within each visit, detections of the same source are clustered (friends-of-friends, 2.5") and averaged into
   one per-visit source with a position error from both the formal errors and the measured scatter
   (`visit_sources`). Sources seen only once in a visit (asteroids, cosmic rays, most artefacts) are dropped.
3. Per-visit sources are linked into tracks across the 10-year span (`link_tracks`): friends-of-friends with a
   2.5" linking length (stationary and slow sources, up to ~5"/yr at a 6-month cadence), with chains that take
   two rows from one visit split apart, then a velocity search for fast movers (up to 12"/yr) among the rows
   left in short tracks.
4. Each track is fitted with a straight line on the tangent plane, optionally with parallax (`fit_motion`);
   tracks with enough visits, a large and significant proper motion and a sane fit are the movers.

All positions in the heavy steps are float64 tangent-plane offsets in arcsec (precision << 0.01").
Units: degrees for ra/dec, decimal (Julian) years for epochs, arcsec for errors, mas/yr for proper motions.
"""
from __future__ import annotations

import functools
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

try:  # imported as `survey.link` (pipeline/ on sys.path) or as `pipeline.survey.link`
    from . import tiles as _tiles
except ImportError:  # pragma: no cover - run as a script
    import tiles as _tiles  # type: ignore

YEARS = _tiles.YEARS
read_tile_year = _tiles.read_tile_year
good_mask = _tiles.good_mask

RAD2AS = 180.0 / math.pi * 3600.0      # radians -> arcsec
MJD_J2000 = 51544.5
DAYS_PER_YEAR = 365.25

LINK_RADIUS = 2.5        # arcsec, within-visit clustering and cross-visit friends-of-friends
DET_FLOOR = 0.1          # arcsec added in quadrature to each detection's error when weighting a visit mean
VISIT_SYS = 0.05         # arcsec, systematic error per visit position (frame-to-frame astrometry), see process_tile
FAST_VMAX = 12.0         # arcsec/yr, fastest motion searched for
FAST_TOL = 1.5           # arcsec, max distance of a row from the fitted straight line in the velocity search
FAST_MIN_VISITS = 5      # distinct visits needed to accept a velocity-search track
MAG_TOL = 1.0            # mag, rows of one velocity-search track must agree in brightness to this level
FAST_SIG = 3.0           # extra -log10 probability margin for a velocity-search track to count as significant
DENSITY_RADIUS = 60.0    # arcsec, radius for the local density of pool rows in that significance test
SATURATION = {"w1": 8.0, "w2": 6.7}   # NEOWISE single-exposure saturation (Vega mag)
ECL_POLE = (270.0, 66.560708)          # north ecliptic pole (ICRS ra, dec): NEOWISE scans along ecliptic meridians


def mjd_to_year(mjd):
    """Decimal (Julian) year of an MJD."""
    return 2000.0 + (np.asarray(mjd, float) - MJD_J2000) / DAYS_PER_YEAR


# ------------------------------------------------------------------------------------------------ tangent plane
def _basis(ra0, dec0):
    a, d = np.radians(ra0), np.radians(dec0)
    ca, sa, cd, sd = np.cos(a), np.sin(a), np.cos(d), np.sin(d)
    u0 = np.stack([cd * ca, cd * sa, sd], -1)
    ea = np.stack([-sa, ca, np.zeros_like(ca)], -1)
    ed = np.stack([-sd * ca, -sd * sa, cd], -1)
    return u0, ea, ed


def _unit(ra, dec):
    a, d = np.radians(ra), np.radians(dec)
    cd = np.cos(d)
    return np.stack([cd * np.cos(a), cd * np.sin(a), np.sin(d)], -1)


def tangent_point(ra, dec):
    """(ra0, dec0) of the mean direction of a set of positions (safe across RA = 0/360 and at the poles)."""
    v = _unit(np.asarray(ra, float), np.asarray(dec, float)).reshape(-1, 3).sum(0)
    nrm = np.linalg.norm(v)
    if not np.isfinite(nrm) or nrm == 0:
        return 0.0, 0.0
    v /= nrm
    return float(np.degrees(np.arctan2(v[1], v[0])) % 360.0), float(np.degrees(np.arctan2(v[2], np.hypot(v[0], v[1]))))


def to_tangent(ra, dec, ra0, dec0):
    """Gnomonic projection about (ra0, dec0): (xi, eta) in arcsec, xi towards +RA (east), eta towards +Dec.
    ra0/dec0 may be scalars or arrays matching ra/dec."""
    p = _unit(np.asarray(ra, float), np.asarray(dec, float))
    u0, ea, ed = _basis(np.asarray(ra0, float), np.asarray(dec0, float))
    c = np.sum(p * u0, -1)
    return np.sum(p * ea, -1) / c * RAD2AS, np.sum(p * ed, -1) / c * RAD2AS


def from_tangent(xi, eta, ra0, dec0):
    """Inverse of to_tangent: (ra, dec) in degrees."""
    u0, ea, ed = _basis(np.asarray(ra0, float), np.asarray(dec0, float))
    x = np.asarray(xi, float)[..., None] / RAD2AS
    y = np.asarray(eta, float)[..., None] / RAD2AS
    v = u0 + x * ea + y * ed
    ra = np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360.0
    dec = np.degrees(np.arctan2(v[..., 2], np.hypot(v[..., 0], v[..., 1])))
    return ra, dec


# ------------------------------------------------------------------------------------------------ visits
def split_visits(mjd, gap_days: float = 20.0, max_len_days: float = 12.0) -> np.ndarray:
    """Visit index (0, 1, ... in time order) for each detection.

    A new visit starts after a gap of more than `gap_days` with no detections. A continuous stretch longer than
    `max_len_days` (ecliptic-pole tiles are observed on every orbit) is cut into equal windows no longer than
    `max_len_days`. Non-finite MJDs get -1."""
    mjd = np.asarray(mjd, float)
    out = np.full(mjd.shape, -1, dtype=np.int64)
    ok = np.isfinite(mjd)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(mjd[idx], kind="stable")]
    s = mjd[order]
    new = np.r_[True, np.diff(s) > gap_days]
    seg = np.cumsum(new) - 1
    starts = s[new]
    ends = np.r_[s[np.flatnonzero(new)[1:] - 1], s[-1]]
    length = ends - starts
    nwin = np.maximum(1, np.ceil(length / max_len_days - 1e-9)).astype(np.int64)
    width = np.where(nwin > 1, length / nwin, np.inf)
    w = np.floor((s - starts[seg]) / width[seg]).astype(np.int64)
    w = np.minimum(np.maximum(w, 0), nwin[seg] - 1)
    first = np.r_[0, np.cumsum(nwin)[:-1]]
    vid = first[seg] + w
    _, dense = np.unique(vid, return_inverse=True)     # drop empty windows
    out[order] = dense
    return out


def _edges(xy, r, k, group=None):
    """Symmetric neighbour edges (i, j) with |xy_i - xy_j| <= r, using at most k nearest neighbours per point
    (bounded work even where a source has hundreds of rows), optionally only between different groups."""
    n = len(xy)
    kk = min(k + 1, n)
    if n < 2:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    tree = cKDTree(xy)
    d, j = tree.query(xy, k=kk, distance_upper_bound=r)
    if kk == 1:
        j = j[:, None]
    i = np.broadcast_to(np.arange(n)[:, None], j.shape)
    ok = j < n
    ok &= j != i
    if group is not None:
        jj = np.where(ok, j, 0)
        ok &= group[jj] != group[i]
    return i[ok].astype(np.int64), j[ok].astype(np.int64)


def _components(n, i, j):
    if n == 0:
        return np.zeros(0, np.int64)
    if len(i) == 0:
        return np.arange(n, dtype=np.int64)
    g = coo_matrix((np.ones(len(i), np.int8), (i, j)), shape=(n, n)).tocsr()
    return connected_components(g, directed=False)[1].astype(np.int64)


def _dup_labels(labels, key):
    """Labels that contain two members with the same key (e.g. two detections from one exposure)."""
    if len(labels) < 2:
        return np.zeros(0, labels.dtype)
    o = np.lexsort((key, labels))
    lab, kk = labels[o], key[o]
    dup = (lab[1:] == lab[:-1]) & (kk[1:] == kk[:-1])
    return np.unique(lab[1:][dup])


def _kmeans_split(x, y, t, iters=6):
    """Split one cluster that holds k detections in a single exposure into k sources: seeds are that exposure's
    detections, then a few Lloyd iterations. Returns sub-labels 0..k-1."""
    _, inv, cnt = np.unique(t, return_inverse=True, return_counts=True)
    seed_exp = int(np.argmax(cnt))
    seeds = np.flatnonzero(inv == seed_exp)
    cx, cy = x[seeds].astype(float), y[seeds].astype(float)
    lab = np.zeros(len(x), np.int64)
    for _ in range(iters):
        d = (x[:, None] - cx[None, :]) ** 2 + (y[:, None] - cy[None, :]) ** 2
        new = np.argmin(d, 1)
        if _ > 0 and (new == lab).all():
            break
        lab = new
        for j in range(len(cx)):
            m = lab == j
            if m.any():
                cx[j], cy[j] = x[m].mean(), y[m].mean()
    return lab


def _cluster_visit(x, y, t, r=LINK_RADIUS, k=16):
    """Friends-of-friends clusters of one visit's detections (x, y arcsec; t = exposure MJD). A source is seen at
    most once per exposure, so a cluster holding two detections with the same MJD is two blended sources: it is
    re-clustered with half the linking length, then (if still doubled) split by k-means seeded with the doubled
    exposure's detections; any exposure still doubled keeps only its detection nearest the centre (others -1)."""
    n = len(x)
    xy = np.column_stack([x, y])
    lab = _components(n, *_edges(xy, r, k))
    bad = _dup_labels(lab, t)
    if len(bad):
        sel = np.flatnonzero(np.isin(lab, bad))
        sub = _components(len(sel), *_edges(xy[sel], r / 2, k))
        lab[sel] = lab.max() + 1 + sub
        bad = _dup_labels(lab[sel], t[sel])
        if len(bad):
            nxt = int(lab.max()) + 1
            s1 = sel[np.isin(lab[sel], bad)]
            o = s1[np.argsort(lab[s1], kind="stable")]
            for comp in np.split(o, np.flatnonzero(np.diff(lab[o])) + 1):
                sub = _kmeans_split(x[comp], y[comp], t[comp])
                lab[comp] = nxt + sub
                nxt += int(sub.max()) + 1
            bad = _dup_labels(lab[sel], t[sel])
        if len(bad):
            s2 = sel[np.isin(lab[sel], bad)]
            l2 = lab[s2]
            cnt = np.bincount(l2 - l2.min())
            cx = np.bincount(l2 - l2.min(), x[s2]) / np.maximum(cnt, 1)
            cy = np.bincount(l2 - l2.min(), y[s2]) / np.maximum(cnt, 1)
            dist = np.hypot(x[s2] - cx[l2 - l2.min()], y[s2] - cy[l2 - l2.min()])
            o = np.lexsort((dist, t[s2], l2))
            first = np.r_[True, (l2[o][1:] != l2[o][:-1]) | (t[s2][o][1:] != t[s2][o][:-1])]
            drop = s2[o][~first]
            lab[drop] = -1
    return lab


def visit_sources(ra, dec, mjd, w1, w2, w1err, w2err, sigra, sigdec, visit, radius: float = LINK_RADIUS,
                  min_det: int = 2) -> dict:
    """One row per (visit, source): detections of a visit within `radius` arcsec of each other are clustered
    (friends-of-friends, at most one detection per exposure) and clusters with >= `min_det` detections are
    averaged.

    Returns a dict of arrays: `ra, dec` (deg, weighted mean), `epoch` (decimal year, mean of the detections),
    `w1, w2` (mean of measured magnitudes; if a band has only upper limits, their median and `w1lim/w2lim` True),
    `n` (detections), `sig` (arcsec, error of the mean position per axis: the larger of the formal error and the
    measured scatter / sqrt(n)), `visit`."""
    ra = np.asarray(ra, float)
    dec = np.asarray(dec, float)
    mjd = np.asarray(mjd, float)
    visit = np.asarray(visit, np.int64)
    n_all = len(ra)
    sra = np.asarray(sigra, float)
    sde = np.asarray(sigdec, float)
    empty = {"ra": np.zeros(0), "dec": np.zeros(0), "epoch": np.zeros(0), "w1": np.zeros(0, np.float32),
             "w2": np.zeros(0, np.float32), "n": np.zeros(0, np.int32), "sig": np.zeros(0), "visit": np.zeros(0, np.int64),
             "w1lim": np.zeros(0, bool), "w2lim": np.zeros(0, bool)}
    if n_all == 0:
        return empty
    ok = np.isfinite(ra) & np.isfinite(dec) & np.isfinite(mjd) & (visit >= 0)
    order = np.flatnonzero(ok)
    order = order[np.argsort(visit[order], kind="stable")]
    v_sorted = visit[order]
    cuts = np.flatnonzero(np.diff(v_sorted)) + 1
    groups = np.split(order, cuts)
    x = np.zeros(n_all)
    y = np.zeros(n_all)
    lab = np.full(n_all, -1, np.int64)
    tp_ra, tp_dec = [], []
    next_lab = 0
    for gi, g in enumerate(groups):
        if len(g) == 0:
            continue
        r0, d0 = tangent_point(ra[g], dec[g])
        tp_ra.append(r0)
        tp_dec.append(d0)
        gx, gy = to_tangent(ra[g], dec[g], r0, d0)
        x[g], y[g] = gx, gy
        lg = _cluster_visit(gx, gy, mjd[g], radius)
        keep = lg >= 0
        lab[g[keep]] = lg[keep] + next_lab
        next_lab += int(lg.max()) + 1 if keep.any() else 0
    sel = np.flatnonzero(lab >= 0)
    if len(sel) == 0:
        return empty
    lab_s = lab[sel]
    cnt = np.bincount(lab_s, minlength=next_lab)
    good_cl = cnt >= min_det
    sel = sel[good_cl[lab_s]]
    if len(sel) == 0:
        return empty
    _, cl = np.unique(lab[sel], return_inverse=True)
    m = int(cl.max()) + 1
    n = np.bincount(cl, minlength=m).astype(np.float64)

    def s(v):
        return np.bincount(cl, v, minlength=m)
    wx = 1.0 / (np.where(np.isfinite(sra[sel]), sra[sel], 1.0) ** 2 + DET_FLOOR ** 2)
    wy = 1.0 / (np.where(np.isfinite(sde[sel]), sde[sel], 1.0) ** 2 + DET_FLOOR ** 2)
    xs, ys = x[sel], y[sel]
    W_x, W_y = s(wx), s(wy)
    mx, my = s(wx * xs) / W_x, s(wy * ys) / W_y
    rx, ry = xs - mx[cl], ys - my[cl]
    corr = n / np.maximum(n - 1.0, 1.0)
    emp_x = s(wx * rx * rx) / W_x * corr / n
    emp_y = s(wy * ry * ry) / W_y * corr / n
    ex2 = np.maximum(1.0 / W_x, emp_x)
    ey2 = np.maximum(1.0 / W_y, emp_y)
    sig = np.sqrt(0.5 * (ex2 + ey2))
    vis_cl = np.zeros(m, np.int64)
    vis_cl[cl] = visit[sel]
    # tangent point of each cluster = that of its visit
    first_idx = np.zeros(m, np.int64)
    first_idx[cl[::-1]] = sel[::-1]
    gid_of_visit = {int(visit[g[0]]): i for i, g in enumerate(groups) if len(g)}
    gi = np.array([gid_of_visit[int(v)] for v in visit[first_idx]], np.int64) if m else np.zeros(0, np.int64)
    ra_c, dec_c = from_tangent(mx, my, np.asarray(tp_ra)[gi], np.asarray(tp_dec)[gi])
    epoch = mjd_to_year(s(mjd[sel]) / n)

    def mag(vals, errs):
        v = np.asarray(vals, float)[sel]
        e = np.asarray(errs, float)[sel] if errs is not None else np.zeros_like(v)
        meas = np.isfinite(v) & np.isfinite(e)
        nm = s(meas.astype(float))
        mean_meas = s(np.where(meas, v, 0.0)) / np.maximum(nm, 1)
        fin = np.isfinite(v)
        nf = s(fin.astype(float))
        mean_lim = s(np.where(fin, v, 0.0)) / np.maximum(nf, 1)
        out = np.where(nm > 0, mean_meas, np.where(nf > 0, mean_lim, np.nan))
        return out.astype(np.float32), (nm == 0) & (nf > 0)
    m1, l1 = mag(w1, w1err)
    m2, l2 = mag(w2, w2err)
    o = np.lexsort((epoch, vis_cl))
    return {"ra": ra_c[o], "dec": dec_c[o], "epoch": epoch[o], "w1": m1[o], "w2": m2[o], "n": n[o].astype(np.int32),
            "sig": sig[o], "visit": vis_cl[o], "w1lim": l1[o], "w2lim": l2[o]}


def concat_sources(parts) -> dict:
    """Concatenate visit_sources dicts (e.g. one per data year)."""
    parts = [p for p in parts if p is not None and len(p["ra"])]
    if not parts:
        return visit_sources([], [], [], [], [], [], [], [], [], [])
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


# ------------------------------------------------------------------------------------------------ linking
def _project_sources(vs):
    ra0, dec0 = tangent_point(vs["ra"], vs["dec"])
    x, y = to_tangent(vs["ra"], vs["dec"], ra0, dec0)
    return x, y, (ra0, dec0)


def _split_sequential(x, y, t, vis, r):
    """Split one friends-of-friends component that holds two rows from the same visit: walk through the visits in
    time order and give each row to the track whose predicted position (last position plus the recent motion) is
    nearest within r, mutual nearest pairs first; rows left over start new tracks. Returns a label per row."""
    n = len(x)
    lab = np.full(n, -1, np.int64)
    ev = np.lexsort((t, vis))
    vs_sorted = vis[ev]
    cuts = np.flatnonzero(np.diff(vs_sorted)) + 1
    groups = np.split(ev, cuts)
    groups.sort(key=lambda g: float(np.mean(t[g])))
    hist = []  # per track: list of row indices (time order)
    for g in groups:
        tg = float(np.mean(t[g]))
        m = len(hist)
        free_rows = np.ones(len(g), bool)
        if m:
            ax = np.empty(m)
            ay = np.empty(m)
            for k, h in enumerate(hist):
                last = h[-1]
                ax[k], ay[k] = x[last], y[last]
                if len(h) >= 3:
                    # extrapolate only an established motion (>= 1.5" over >= 0.9 yr), so that the walk does not
                    # lock on to the jitter of a blend
                    first = h[max(0, len(h) - 4)]
                    dt = t[last] - t[first]
                    if dt >= 0.9 and math.hypot(x[last] - x[first], y[last] - y[first]) >= 1.5:
                        step = tg - t[last]
                        px = (x[last] - x[first]) / dt * step
                        py = (y[last] - y[first]) / dt * step
                        lim = r / max(math.hypot(px, py), 1e-12)
                        f = min(1.0, lim)
                        ax[k] += px * f
                        ay[k] += py * f
            d = np.hypot(x[g][:, None] - ax[None, :], y[g][:, None] - ay[None, :])
            d[d > r] = np.inf
            free_tr = np.ones(m, bool)
            for _ in range(8):
                dd = np.where(free_rows[:, None] & free_tr[None, :], d, np.inf)
                if not np.isfinite(dd).any():
                    break
                rb = np.argmin(dd, 1)
                cb = np.argmin(dd, 0)
                rows = np.flatnonzero(np.isfinite(dd[np.arange(len(g)), rb]) & (cb[rb] == np.arange(len(g))))
                if len(rows) == 0:
                    break
                for i in rows:
                    hist[rb[i]].append(int(g[i]))
                    lab[g[i]] = rb[i]
                free_rows[rows] = False
                free_tr[rb[rows]] = False
        for i in np.flatnonzero(free_rows):
            hist.append([int(g[i])])
            lab[g[i]] = len(hist) - 1
    return lab


def _fof_tracks(x, y, t, vis, r=LINK_RADIUS, k=12):
    """Friends-of-friends across visits (never linking two rows of one visit directly), then components that
    still hold two rows from one visit are split by sequential nearest-neighbour linking. Returns labels."""
    n = len(x)
    xy = np.column_stack([x, y])
    lab = _components(n, *_edges(xy, r, k, group=vis))
    bad = _dup_labels(lab, vis)
    if len(bad):
        nxt = int(lab.max()) + 1
        sel = np.flatnonzero(np.isin(lab, bad))
        o = sel[np.argsort(lab[sel], kind="stable")]
        cuts = np.flatnonzero(np.diff(lab[o])) + 1
        for comp in np.split(o, cuts):
            sub = _split_sequential(x[comp], y[comp], t[comp], vis[comp], r)
            lab[comp] = nxt + sub
            nxt += int(sub.max()) + 1
    return lab


def _wfit(member, x, y, t, w):
    """Weighted straight-line fits for many hypotheses at once. member: (H, V) row indices or -1.
    Returns tref, x0, y0, vx, vy, S (sum of weights), D (sum w (t - tref)^2), count."""
    ok = member >= 0
    mi = np.where(ok, member, 0)
    W = np.where(ok, w[mi], 0.0)
    T = t[mi]
    S = W.sum(1)
    Sv = np.maximum(S, 1e-300)
    tref = (W * T).sum(1) / Sv
    dt = np.where(ok, T - tref[:, None], 0.0)
    D = (W * dt * dt).sum(1)
    Dv = np.maximum(D, 1e-300)
    X = x[mi]
    Y = y[mi]
    x0 = (W * X).sum(1) / Sv
    y0 = (W * Y).sum(1) / Sv
    vx = (W * dt * X).sum(1) / Dv
    vy = (W * dt * Y).sum(1) / Dv
    return tref, x0, y0, vx, vy, S, D, ok.sum(1)


def _nanmean2(a, b):
    """Element-wise mean of two arrays ignoring NaN (NaN where both are NaN), without warnings."""
    fa, fb = np.isfinite(a), np.isfinite(b)
    s = np.where(fa, a, 0.0) + np.where(fb, b, 0.0)
    n = fa.astype(int) + fb.astype(int)
    return np.where(n > 0, s / np.maximum(n, 1), np.nan)


def _velocity_search(x, y, t, vis, sig, m1, m2, pool, vmax=FAST_VMAX, tol=FAST_TOL, min_visits=FAST_MIN_VISITS,
                     dt_range=(0.25, 1.3), max_gate=3.0, rounds=8, chunk_cells=4_000_000, sig_margin=FAST_SIG):
    """Fast movers among the `pool` rows (x, y arcsec on one tangent plane; t epochs; vis visit ids).

    Seeds: every pair of rows in two visits 0.25-1.3 yr apart (the visits nearest 0.5 and 1 yr after each visit)
    that moved at most vmax*dt and agree in brightness (MAG_TOL) is a straight-line hypothesis. Growth: in rounds,
    each hypothesis takes the nearest pool row at every visit where its predicted position is known well enough
    (gate = tol + 2.5 sigma of the prediction <= max_gate), is refitted, and loses rows more than tol off the line.
    Acceptance: >= min_visits distinct visits, every row within tol of the line, span >= 0.5 yr, and the alignment
    must be significant given the local density of pool rows: the sum over members of -log10(chance of a pool
    row that close to the line), leaving out the two best (the seed), must exceed log10(number of hypotheses) +
    log10(ways to pick the extra visits) + sig_margin. Best hypotheses (most visits, then smallest scatter) are
    taken first and each row is used once. Returns a list of arrays of row indices (into x/y/...)."""
    pool = np.asarray(pool, np.int64)
    if len(pool) < min_visits:
        return []
    px, py, pt, psig = x[pool], y[pool], t[pool], sig[pool]
    pm1, pm2 = m1[pool], m2[pool]
    uv, pv = np.unique(vis[pool], return_inverse=True)
    V = len(uv)
    if V < min_visits:
        return []
    Tv = np.bincount(pv, pt, minlength=V) / np.maximum(np.bincount(pv, minlength=V), 1)
    vorder = np.argsort(Tv)
    rank = np.empty(V, np.int64)
    rank[vorder] = np.arange(V)
    pv = rank[pv]          # visits renumbered in time order
    Tv = Tv[vorder]
    w = 1.0 / (psig ** 2 + 0.1 ** 2)
    by_visit = [np.flatnonzero(pv == v) for v in range(V)]
    trees = [cKDTree(np.column_stack([px[b], py[b]])) if len(b) else None for b in by_visit]
    claimed = np.zeros(len(pool), bool)
    local = np.full(len(pool), -1.0)        # pool rows within DENSITY_RADIUS in the same visit (lazy)
    accepted = []

    def mag_ok(a, ref1, ref2):
        return ~(np.abs(pm1[a] - ref1) > MAG_TOL) & ~(np.abs(pm2[a] - ref2) > MAG_TOL)

    def density(rows):
        need = rows[local[rows] < 0]
        for v in np.unique(pv[need]):
            r = need[pv[need] == v]
            local[r] = trees[v].query_ball_point(np.column_stack([px[r], py[r]]), DENSITY_RADIUS,
                                                 return_length=True) - 1
        return np.maximum(local[rows], 1.0) / (math.pi * DENSITY_RADIUS ** 2)

    # ---- seeds
    seeds = []
    for a in range(V):
        if trees[a] is None:
            continue
        dts = Tv - Tv[a]
        partners = set()
        cand = np.flatnonzero((dts >= dt_range[0]) & (dts <= dt_range[1]))
        for target in (0.5, 1.0):
            if len(cand):
                partners.add(int(cand[np.argmin(np.abs(dts[cand] - target))]))
        for b in sorted(partners):
            if trees[b] is None:
                continue
            pairs = trees[a].sparse_distance_matrix(trees[b], vmax * dts[b] + 2.0, output_type="ndarray")
            if len(pairs) == 0:
                continue
            ii = by_visit[a][pairs["i"]]
            jj = by_visit[b][pairs["j"]]
            keep = mag_ok(ii, pm1[jj], pm2[jj])
            if keep.any():
                seeds.append((ii[keep], jj[keep]))
    if not seeds:
        return []
    n_hyp = sum(len(s[0]) for s in seeds)
    log_trials = math.log10(n_hyp + 1.0)

    # ---- grow and accept, chunk by chunk
    step = max(1, chunk_cells // V)
    for si_all, sj_all in seeds:
        for c0 in range(0, len(si_all), step):
            ci, cj = si_all[c0:c0 + step], sj_all[c0:c0 + step]
            keep = ~claimed[ci] & ~claimed[cj]
            ci, cj = ci[keep], cj[keep]
            H = len(ci)
            if H == 0:
                continue
            mem = np.full((H, V), -1, np.int64)
            mem[np.arange(H), pv[ci]] = ci
            mem[np.arange(H), pv[cj]] = cj
            ref1 = _nanmean2(pm1[ci], pm1[cj])
            ref2 = _nanmean2(pm2[ci], pm2[cj])
            alive = np.ones(H, bool)
            for rnd in range(rounds):
                idx = np.flatnonzero(alive)
                if len(idx) == 0:
                    break
                tref, x0, y0, vx, vy, S, D, cnt = _wfit(mem[idx], px, py, pt, w)
                # prediction error at each visit (formal, plus 0.15" for unmodelled parallax)
                dT = Tv[None, :] - tref[:, None]
                sp = np.sqrt(1.0 / S[:, None] + dT ** 2 / np.maximum(D[:, None], 1e-300) + 0.15 ** 2)
                gate = tol + 2.5 * sp
                elig = (mem[idx] < 0) & (gate <= max_gate)
                added = 0
                for v in np.flatnonzero(elig.any(0)):
                    if trees[v] is None:
                        continue
                    hs = np.flatnonzero(elig[:, v])
                    qx = x0[hs] + vx[hs] * dT[hs, v]
                    qy = y0[hs] + vy[hs] * dT[hs, v]
                    dd, jj = trees[v].query(np.column_stack([qx, qy]), k=1, distance_upper_bound=max_gate)
                    hit = np.isfinite(dd)
                    hit[hit] &= dd[hit] <= gate[hs[hit], v]
                    rows = np.where(hit, by_visit[v][np.minimum(jj, len(by_visit[v]) - 1)], -1)
                    hit &= rows >= 0
                    hit[hit] &= ~claimed[rows[hit]]
                    hit[hit] &= mag_ok(rows[hit], ref1[idx[hs[hit]]], ref2[idx[hs[hit]]])
                    mem[idx[hs[hit]], v] = rows[hit]
                    added += int(hit.sum())
                # refit and drop the worst row that is far from the line (keep >= 2)
                tref, x0, y0, vx, vy, S, D, cnt = _wfit(mem[idx], px, py, pt, w)
                mi = mem[idx]
                okm = mi >= 0
                mm = np.where(okm, mi, 0)
                res = np.hypot(px[mm] - (x0[:, None] + vx[:, None] * (pt[mm] - tref[:, None])),
                               py[mm] - (y0[:, None] + vy[:, None] * (pt[mm] - tref[:, None])))
                lim = np.maximum(tol, 3.0 * psig[mm])
                bad = okm & (res > lim)
                if bad.any():
                    nb = bad.sum(1)
                    worst = np.argmax(np.where(bad, res / lim, -1), 1)
                    hs = np.flatnonzero(((cnt - nb) >= 2) & (nb > 0))
                    mi[hs, worst[hs]] = -1
                    mem[idx] = mi
                cnt = (mem[idx] >= 0).sum(1)
                if rnd == 0:
                    alive[idx[cnt < 3]] = False
                if added == 0 and not bad.any():
                    break
            idx = np.flatnonzero(alive)
            if len(idx) == 0:
                continue
            idx = idx[(mem[idx] >= 0).sum(1) >= min_visits]
            if len(idx) == 0:
                continue
            tref, x0, y0, vx, vy, S, D, cnt = _wfit(mem[idx], px, py, pt, w)
            mi = mem[idx]
            okm = mi >= 0
            mm = np.where(okm, mi, 0)
            res = np.hypot(px[mm] - (x0[:, None] + vx[:, None] * (pt[mm] - tref[:, None])),
                           py[mm] - (y0[:, None] + vy[:, None] * (pt[mm] - tref[:, None])))
            rms = np.sqrt(np.where(okm, res ** 2, 0).sum(1) / np.maximum(cnt, 1))
            span = np.where(okm, pt[mm], -np.inf).max(1) - np.where(okm, pt[mm], np.inf).min(1)
            good = (np.where(okm, res, 0).max(1) <= tol + 1e-9) & (span >= 0.5) & (np.hypot(vx, vy) <= vmax * 1.1)
            order = np.argsort(-cnt * 10.0 + rms)
            for h in order[good[order]]:
                sel = okm[h]
                rows = mi[h][sel]
                if claimed[rows].any() or len(np.unique(pv[rows])) < min_visits:
                    continue
                # significance of the alignment given the local density of pool rows
                r_eff = np.maximum(np.maximum(res[h][sel], 2.0 * psig[rows]), 0.3)
                p = -np.expm1(-density(rows) * math.pi * r_eff ** 2)
                score = np.sort(-np.log10(np.maximum(p, 1e-300)))[:-2].sum()
                k = len(rows)
                need = log_trials + math.log10(max(math.comb(V - 2, k - 2), 1)) + sig_margin
                if score < need:
                    continue
                claimed[rows] = True
                accepted.append(pool[rows[np.argsort(pt[rows])]])
    return accepted


def link_tracks(vs, radius: float = LINK_RADIUS, vmax: float = FAST_VMAX, tol: float = FAST_TOL,
                min_fast_visits: int = FAST_MIN_VISITS, fast_pool_max_visits: int = 3) -> list:
    """Link per-visit sources (a visit_sources dict) into tracks: a list of arrays of row indices into vs, each
    sorted by epoch, each with at most one row per visit and at least 2 rows.

    (a) Stationary and slow sources: friends-of-friends with a `radius` linking length between rows of different
        visits; a chain that takes two rows from one visit is split by sequential nearest-neighbour linking.
    (b) Fast movers (up to `vmax` arcsec/yr): a velocity search among rows whose track from (a) has fewer than
        `fast_pool_max_visits` visits (straight line within `tol` arcsec through >= `min_fast_visits` visits)."""
    n = len(vs["ra"])
    if n == 0:
        return []
    x, y, _ = _project_sources(vs)
    t = np.asarray(vs["epoch"], float)
    vis = np.asarray(vs["visit"], np.int64)
    lab = _fof_tracks(x, y, t, vis, radius)
    cnt = np.bincount(lab)
    short = cnt[lab] < fast_pool_max_visits
    pool = np.flatnonzero(short)
    sig = np.asarray(vs.get("sig", np.full(n, 0.3)), float)
    m1 = np.asarray(vs.get("w1", np.full(n, np.nan)), float).copy()
    m2 = np.asarray(vs.get("w2", np.full(n, np.nan)), float).copy()
    if "w1lim" in vs:
        m1[np.asarray(vs["w1lim"], bool)] = np.nan
    if "w2lim" in vs:
        m2[np.asarray(vs["w2lim"], bool)] = np.nan
    fast = _velocity_search(x, y, t, vis, sig, m1, m2, pool, vmax=vmax, tol=tol, min_visits=min_fast_visits)
    used = np.zeros(n, bool)
    for f in fast:
        used[f] = True
    keep = ~used
    o = np.flatnonzero(keep)
    o = o[np.lexsort((t[o], lab[o]))]
    cuts = np.flatnonzero(np.diff(lab[o])) + 1
    tracks = [g for g in np.split(o, cuts) if len(g) >= 2]
    return tracks + fast


# ------------------------------------------------------------------------------------------------ motion fit
@functools.lru_cache(maxsize=1)
def _earth_table():
    """Barycentric Earth position (AU, ICRS) every 0.5 day over 2009-2030 from astropy's built-in (offline)
    ephemeris; interpolated by earth_position."""
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time
    grid = np.arange(2009.0, 2030.0, 0.5 / DAYS_PER_YEAR)
    p = get_body_barycentric("earth", Time(grid, format="jyear", scale="tdb"), ephemeris="builtin")
    xyz = np.vstack([p.x.to_value("AU"), p.y.to_value("AU"), p.z.to_value("AU")])
    return grid, xyz


def earth_position(epoch):
    """Barycentric (x, y, z) of the Earth in AU at decimal years (WISE orbits ~1e-4 AU from Earth's centre)."""
    grid, xyz = _earth_table()
    e = np.asarray(epoch, float)
    if np.any((e < grid[0]) | (e > grid[-1])):
        from astropy.coordinates import get_body_barycentric
        from astropy.time import Time
        p = get_body_barycentric("earth", Time(np.atleast_1d(e), format="jyear", scale="tdb"), ephemeris="builtin")
        out = np.vstack([p.x.to_value("AU"), p.y.to_value("AU"), p.z.to_value("AU")])
        return out.reshape((3,) + e.shape)
    return np.stack([np.interp(e, grid, xyz[i]) for i in range(3)])


def parallax_factors(epoch, ra0, dec0):
    """(Px, Py): displacement in (xi, eta) per unit parallax at (ra0, dec0) and the given epochs, i.e.
    xi = ... + plx * Px, eta = ... + plx * Py (standard annual-parallax formula with the barycentric Earth)."""
    X, Y, Z = earth_position(epoch)
    a, d = math.radians(ra0), math.radians(dec0)
    px = X * math.sin(a) - Y * math.cos(a)
    py = X * math.cos(a) * math.sin(d) + Y * math.sin(a) * math.sin(d) - Z * math.cos(d)
    return px, py


def _solve_motion(dt, x, y, w, plx=None):
    """Weighted least squares for x = x0 + vx dt (+ plx Px), y = y0 + vy dt (+ plx Py), shared parallax.
    Returns parameters [x0, y0, vx, vy(, plx)], their covariance and the residuals [rx..., ry...]."""
    n = len(dt)
    z = np.zeros(n)
    o = np.ones(n)
    cols_x = [o, z, dt, z]
    cols_y = [z, o, z, dt]
    if plx is not None:
        cols_x.append(plx[0])
        cols_y.append(plx[1])
    A = np.vstack([np.column_stack(cols_x), np.column_stack(cols_y)])
    b = np.r_[x, y]
    ww = np.sqrt(np.r_[w, w])
    Aw = A * ww[:, None]
    p, *_ = np.linalg.lstsq(Aw, b * ww, rcond=None)
    cov = np.linalg.pinv(Aw.T @ Aw)
    return p, cov, b - A @ p


def fit_motion(epoch, ra, dec, sig, parallax=False, sig_floor: float = 0.0, min_parallax_visits: int = 8,
               jackknife: bool = False) -> dict:
    """Weighted straight-line fit on the tangent plane about the mean position.

    epoch: decimal years; ra, dec: degrees; sig: per-point position error (arcsec, per axis); sig_floor is added
    in quadrature. parallax: False, True, or "auto" (fit it when there are >= min_parallax_visits points and the
    parallax is constrained to better than 0.5"). jackknife: also estimate the proper-motion error by leaving
    out one point at a time, and use it when larger than the formal error (robust to a few bad visits).

    Returns ra, dec (deg) at epoch0 (= epoch, the weighted mean epoch), pmra (mas/yr, includes cos dec), pmdec,
    pm, pm_err (mas/yr, scaled up by sqrt(chi2r) when chi2r > 1), pm_snr, chi2r, n_visits, span_yr, plx and
    plx_err (mas, None when not fitted), plus pmra_err, pmdec_err, rms (arcsec) and residuals (arcsec, per point)."""
    t = np.asarray(epoch, float)
    ra = np.asarray(ra, float)
    dec = np.asarray(dec, float)
    s = np.sqrt(np.asarray(sig, float) ** 2 + sig_floor ** 2) * np.ones_like(t)
    n = len(t)
    out = {"ra": None, "dec": None, "epoch0": None, "epoch": None, "pmra": float("nan"), "pmdec": float("nan"),
           "pm": float("nan"), "pm_err": float("nan"), "pm_snr": 0.0, "chi2r": float("nan"), "n_visits": int(n),
           "span_yr": float(t.max() - t.min()) if n else 0.0, "plx": None, "plx_err": None,
           "pmra_err": float("nan"), "pmdec_err": float("nan"), "rms": float("nan"), "residuals": np.zeros((n, 2))}
    if n == 0:
        return out
    ra0, dec0 = tangent_point(ra, dec)
    x, y = to_tangent(ra, dec, ra0, dec0)
    w = 1.0 / np.maximum(s, 1e-6) ** 2
    t0 = float(np.sum(w * t) / np.sum(w))
    out["epoch0"] = out["epoch"] = t0
    if n < 2 or out["span_yr"] <= 0:
        r, d = from_tangent(np.sum(w * x) / w.sum(), np.sum(w * y) / w.sum(), ra0, dec0)
        out["ra"], out["dec"] = float(r), float(d)
        return out
    dt = t - t0
    use_plx = parallax is True or (parallax == "auto" and n >= min_parallax_visits)
    pf = parallax_factors(t, ra0, dec0) if use_plx else None
    p, cov, res = _solve_motion(dt, x, y, w, pf)
    if use_plx and parallax == "auto" and not (np.sqrt(cov[4, 4]) <= 0.5):
        use_plx = False
        pf = None
        p, cov, res = _solve_motion(dt, x, y, w)
    npar = 5 if use_plx else 4
    chi2 = float(np.sum(np.r_[w, w] * res ** 2))
    dof = 2 * n - npar
    chi2r = chi2 / dof if dof > 0 else float("nan")
    scale = max(1.0, chi2r) if np.isfinite(chi2r) else 1.0
    cov = cov * scale
    r0, d0 = from_tangent(p[0], p[1], ra0, dec0)
    pmx, pmy = p[2] * 1000.0, p[3] * 1000.0
    vx, vy, cxy = cov[2, 2] * 1e6, cov[3, 3] * 1e6, cov[2, 3] * 1e6
    pm = math.hypot(pmx, pmy)
    if pm > 0:
        pm_err = math.sqrt(max((pmx * pmx * vx + pmy * pmy * vy + 2 * pmx * pmy * cxy) / (pm * pm), 0.0))
    else:
        pm_err = math.sqrt(0.5 * (vx + vy))
    if jackknife and n >= 5:
        jk = np.empty((n, 2))
        idx = np.arange(n)
        for i in range(n):
            k = idx != i
            pk, _, _ = _solve_motion(dt[k], x[k], y[k], w[k], None if pf is None else (pf[0][k], pf[1][k]))
            jk[i] = pk[2:4] * 1000.0
        d = jk - jk.mean(0)
        cj = (n - 1) / n * (d.T @ d)
        e_jk = math.sqrt(float(np.array([pmx, pmy]) @ cj @ np.array([pmx, pmy])) / (pm * pm)) if pm > 0 \
            else math.sqrt(0.5 * float(np.trace(cj)))
        out["pm_err_jackknife"] = e_jk
        pm_err = max(pm_err, e_jk)
        vx, vy = max(vx, float(cj[0, 0])), max(vy, float(cj[1, 1]))
    out.update({"ra": float(r0), "dec": float(d0), "pmra": float(pmx), "pmdec": float(pmy), "pm": float(pm),
                "pm_err": float(pm_err), "pm_snr": float(pm / pm_err) if pm_err > 0 else float("inf"),
                "chi2r": float(chi2r), "pmra_err": float(math.sqrt(vx)), "pmdec_err": float(math.sqrt(vy)),
                "rms": float(np.sqrt(np.mean(res[:n] ** 2 + res[n:] ** 2))),
                "residuals": np.column_stack([res[:n], res[n:]])})
    if use_plx:
        out["plx"] = float(p[4] * 1000.0)
        out["plx_err"] = float(math.sqrt(cov[4, 4]) * 1000.0)
    return out


def _quick_fits(tracks, x, y, t, w, full=False):
    """Vectorised weighted straight-line fits (no parallax) of many tracks on a common tangent plane.
    Returns pm (mas/yr), pm_err (mas/yr, scaled by sqrt(chi2r) when > 1), chi2r, n; with full=True also
    x0, y0 (arcsec, at the weighted mean epoch) and span (yr)."""
    if not tracks:
        z = np.zeros(0)
        return (z, z, z, z.astype(int), z, z, z) if full else (z, z, z, z.astype(int))
    lens = np.fromiter((len(a) for a in tracks), np.int64, len(tracks))
    rows = np.concatenate(tracks)
    tid = np.repeat(np.arange(len(tracks)), lens)
    m = len(tracks)

    def s(v):
        return np.bincount(tid, v, minlength=m)
    W = w[rows]
    T = t[rows]
    S = s(W)
    tref = s(W * T) / S
    dt = T - tref[tid]
    D = np.maximum(s(W * dt * dt), 1e-300)
    X, Y = x[rows], y[rows]
    x0, y0 = s(W * X) / S, s(W * Y) / S
    vx, vy = s(W * dt * X) / D, s(W * dt * Y) / D
    rx = X - x0[tid] - vx[tid] * dt
    ry = Y - y0[tid] - vy[tid] * dt
    chi2 = s(W * (rx * rx + ry * ry))
    dof = np.maximum(2 * lens - 4, 1)
    chi2r = chi2 / dof
    perr = np.sqrt(1.0 / D * np.maximum(chi2r, 1.0)) * 1000.0
    if full:
        tmax = np.full(m, -np.inf)
        tmin = np.full(m, np.inf)
        np.maximum.at(tmax, tid, T)
        np.minimum.at(tmin, tid, T)
        return np.hypot(vx, vy) * 1000.0, perr, chi2r, lens, x0, y0, tmax - tmin
    return np.hypot(vx, vy) * 1000.0, perr, chi2r, lens


def scan_angle(ra, dec, pmra, pmdec):
    """Angle (deg, 0-90) between a motion and the local NEOWISE scan direction (the great circle through the
    ecliptic poles): spurious motion from scan-aligned artefacts would sit near 0."""
    a, d = math.radians(ra), math.radians(dec)
    ap, dp = math.radians(ECL_POLE[0]), math.radians(ECL_POLE[1])
    pa_scan = math.atan2(math.sin(ap - a) * math.cos(dp),
                         math.cos(d) * math.sin(dp) - math.sin(d) * math.cos(dp) * math.cos(ap - a))
    pa_pm = math.atan2(pmra, pmdec)
    diff = abs((math.degrees(pa_pm - pa_scan) + 90.0) % 180.0 - 90.0)
    return diff


# ------------------------------------------------------------------------------------------------ one tile
_REDUCE_COLS = [("ra", np.float64), ("dec", np.float64), ("mjd", np.float64), ("sigra", np.float32),
                ("sigdec", np.float32), ("w1mpro", np.float32), ("w2mpro", np.float32), ("w1sigmpro", np.float32),
                ("w2sigmpro", np.float32)]


def _reduce(table):
    """Good detections of a raw table as compact numpy arrays (the raw table can then be freed)."""
    m = good_mask(table)
    out = {}
    for name, dt in _REDUCE_COLS:
        if name in table.column_names:
            a = table[name].to_numpy(zero_copy_only=False)
            out[name] = np.asarray(a[m], dtype=dt)
        else:
            out[name] = np.full(int(m.sum()), np.nan, dt)
    return out, int(m.sum())


def _subset(d, sel):
    return {k: v[sel] for k, v in d.items()}


def _cat(a, b):
    if a is None:
        return b
    return {k: np.concatenate([a[k], b[k]]) for k in a}


def _sources_of(red, visit):
    return visit_sources(red["ra"], red["dec"], red["mjd"], red["w1mpro"], red["w2mpro"], red["w1sigmpro"],
                         red["w2sigmpro"], red["sigra"], red["sigdec"], visit)


def _jsonable(v, nd=None):
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def tile_sources(k5, reader=read_tile_year, years=YEARS, prefetch: bool = True, log=None):
    """Read a tile year by year and reduce it to per-visit sources. Returns (vs, stats): vs is a visit_sources
    dict over the whole tile (visit numbers global and in time order); stats has years, missing_years,
    n_detections, n_good, n_visits, notes, seconds_io_wait.

    `reader(k5, year)` returns a pyarrow Table (or None for a missing year). The years are read one at a time
    (the next one downloads in a background thread while this one is processed) and each raw table is reduced at
    once to the good detections' positions and photometry, then freed; only per-visit source lists are kept. A
    visit cut by the boundary between two data years is carried over and finished with the next year."""
    t_start = time.perf_counter()
    k5 = int(k5)
    years = list(years)
    multipart = {}

    def fetch(year):
        """(reduced good detections or None if the year is missing, number of raw rows). Runs in the prefetch
        thread, so the raw table never outlives its reduction; the default S3 reader goes row group by row
        group to bound memory on the huge ecliptic-pole files."""
        if reader is read_tile_year:
            reds, n_rows = [], 0
            for tab in _tiles.iter_tile_year(k5, year, columns=_tiles.CORE_COLUMNS):
                n_rows += tab.num_rows
                reds.append(_reduce(tab)[0])
                del tab
            if not reds:
                return None, 0
            try:
                multipart[year] = _tiles.tile_year_parts(k5, year)
            except Exception:  # noqa: BLE001 - informational only
                pass
            red = reds[0]
            for r in reds[1:]:
                red = _cat(red, r)
            return red, n_rows
        tab = reader(k5, year)
        if tab is None:
            return None, 0
        return _reduce(tab)[0], tab.num_rows

    n_det = 0
    n_good = 0
    years_read, years_missing = [], []
    parts = []
    carry = None
    vis_offset = 0
    ex = ThreadPoolExecutor(1) if prefetch else None
    fut = None
    t_io = 0.0
    try:
        if ex and years:
            fut = ex.submit(fetch, years[0])
        for i, year in enumerate(years):
            t0 = time.perf_counter()
            red, n_rows = fut.result() if ex else fetch(year)
            t_io += time.perf_counter() - t0
            if red is None:
                years_missing.append(year)
            else:
                years_read.append(year)
                n_det += n_rows
                n_good += len(red["mjd"])
            if ex and i + 1 < len(years):
                fut = ex.submit(fetch, years[i + 1])
            if red is not None:
                carry = _cat(carry, red)
            last_year = i == len(years) - 1
            if carry is None or len(carry["mjd"]) == 0:
                continue
            vis = split_visits(carry["mjd"])
            nv = int(vis.max()) + 1
            if last_year:
                done, carry_next = np.ones(len(vis), bool), None
            else:
                done = vis < nv - 1
                carry_next = _subset(carry, ~done) if (~done).any() else None
            if done.any():
                parts.append(_sources_of(_subset(carry, done), vis[done] + vis_offset))
                vis_offset += int(vis[done].max()) + 1
            carry = carry_next
            if log:
                log(f"{k5} {year}: {n_det:,} detections, {n_good:,} good, {vis_offset} visits, "
                    f"{sum(len(p['ra']) for p in parts):,} visit sources, {time.perf_counter() - t_start:.1f}s")
        if carry is not None and len(carry["mjd"]):
            vis = split_visits(carry["mjd"])
            parts.append(_sources_of(carry, vis + vis_offset))
            vis_offset += int(vis.max()) + 1
            carry = None
    finally:
        if ex:
            ex.shutdown(wait=True)
    vs = concat_sources(parts)
    notes = [f"{y}: read part0 of {n} parquet parts (ecliptic-pole tile)" for y, n in sorted(multipart.items()) if n > 1]
    stats = {"years": years_read, "missing_years": years_missing, "n_detections": int(n_det), "n_good": int(n_good),
             "n_visits": int(vis_offset), "notes": notes, "seconds_io_wait": round(t_io, 2)}
    return vs, stats


def process_tile(k5, reader=read_tile_year, years=YEARS, min_visits=6, min_pm=150.0, min_pm_snr=5.0, *,
                 max_chi2r: float = 25.0, visit_sys: float = VISIT_SYS, prefetch: bool = True, log=None) -> dict:
    """Find the movers in one HEALPix order-5 tile. Returns the TileResult dict of docs/survey-contract.md
    (plus `missing_years`, `notes` and timing details).

    Steps: tile_sources (read + reduce year by year) -> link_tracks -> fit -> select_movers. Movers are tracks
    with >= min_visits visits, pm >= min_pm mas/yr and pm_snr >= min_pm_snr, after rejecting fits with
    chi2r > max_chi2r. Every mover gets `flags` for the ranking step: "saturated" (W1 < 8 or W2 < 6.7, positions
    less reliable), "high_chi2r" (> 5), "along_scan" (motion within 10 deg of the scan direction), "tile_edge"
    (would cross the tile boundary during 2014-2024, track may be truncated), "fast_search" (moves more than the
    2.5" linking length between visits, so only the velocity search can link it), "w1_limit"/"w2_limit" (band
    undetected; value is a faint limit), "crowded" (another source within 8" in >= 30% of the visits), "clipped"
    (outlying visits dropped from the fit). Candidates explained by stationary sources, with inconsistent halves,
    marginal detections, poor coverage or a blend are rejected (see select_movers)."""
    t_start = time.perf_counter()
    k5 = int(k5)
    vs, stats = tile_sources(k5, reader, years, prefetch=prefetch, log=log)
    t_link0 = time.perf_counter()
    tracks = link_tracks(vs)
    t_link = time.perf_counter() - t_link0
    movers = select_movers(k5, vs, tracks, min_visits, min_pm, min_pm_snr, max_chi2r, visit_sys)
    ra_c, dec_c = _tiles.tile_center(k5)
    return {"k5": k5, "center": [round(ra_c, 5), round(dec_c, 5)], "years": stats["years"],
            "missing_years": stats["missing_years"], "n_detections": stats["n_detections"], "n_good": stats["n_good"],
            "n_visits": stats["n_visits"], "n_visit_sources": int(len(vs["ra"])), "n_tracks": int(len(tracks)),
            "n_movers": len(movers), "seconds": round(time.perf_counter() - t_start, 2),
            "seconds_io_wait": stats["seconds_io_wait"], "seconds_link": round(t_link, 2), "notes": stats["notes"],
            "movers": movers}


STAT_RADIUS = 1.5      # arcsec: a candidate's row this close to a stationary source is "explained" by it
MAX_STAT_FRAC = 0.25   # reject candidates with more of their rows explained by stationary sources
CROWD_RADIUS = 8.0     # arcsec (~1.3 x the W1/W2 PSF FWHM): another source this close in a visit blends with it
CROWD_FRAC = 0.3       # a track is "crowded" when that happens in >= 30% of its visits
CLIP_SIGMA = 4.0       # rows further than this (in units of their error) from the fitted line are clipped
HALVES_SIGMA = 4.0     # the two halves of a track must agree in proper motion to this level
MIN_COVERAGE = 0.6     # detected in >= 60% of the visits that observed its (moving) position
COVER_RADIUS = 60.0    # arcsec: a visit "observed" a position if it has any source this close to it
MIN_NDET = 3           # median detections per visit (a source seen in 2 exposures of ~12 is marginal)


def _fit_clipped(t, ra, dec, sig, max_frac=0.2):
    """fit_motion with parallax="auto", then drop the worst row while it is > CLIP_SIGMA off (at most max_frac
    of the rows). Returns (fit, kept boolean mask)."""
    keep = np.ones(len(t), bool)
    f = fit_motion(t, ra, dec, sig, parallax="auto")
    for _ in range(int(max_frac * len(t))):
        r = np.hypot(f["residuals"][:, 0], f["residuals"][:, 1]) / sig[keep]
        j = int(np.argmax(r))
        if r[j] <= CLIP_SIGMA:
            break
        keep[np.flatnonzero(keep)[j]] = False
        f = fit_motion(t[keep], ra[keep], dec[keep], sig[keep], parallax="auto")
    return f, keep


def _halves_agree(t, ra, dec, sig):
    """True unless the first and second half of the track (in time) give clearly different proper motions:
    a chimera of blended stationary sources fakes motion over part of its span only."""
    n = len(t)
    if n < 8:
        return True
    o = np.argsort(t)
    a, b = o[: n // 2], o[n // 2:]
    fa = fit_motion(t[a], ra[a], dec[a], sig[a])
    fb = fit_motion(t[b], ra[b], dec[b], sig[b])
    if fa["span_yr"] < 1.0 or fb["span_yr"] < 1.0:
        return True
    d = math.hypot(fa["pmra"] - fb["pmra"], fa["pmdec"] - fb["pmdec"])
    s = math.sqrt(fa["pmra_err"] ** 2 + fb["pmra_err"] ** 2 + fa["pmdec_err"] ** 2 + fb["pmdec_err"] ** 2) / math.sqrt(2)
    pm = math.hypot(fa["pmra"] + fb["pmra"], fa["pmdec"] + fb["pmdec"]) / 2
    return not (d > HALVES_SIGMA * s and d > 0.3 * pm)


def select_movers(k5, vs, tracks, min_visits=6, min_pm=150.0, min_pm_snr=5.0, max_chi2r=25.0, visit_sys=VISIT_SYS,
                  rejected=None):
    """Fit the tracks and keep the movers (criteria and flags: see process_tile). Mover dicts by pm_snr.

    Vetting of each candidate (real NEOWISE fields are full of faint blended pairs whose per-visit centroid
    jumps between the two stars and their blend, which linking can turn into a fake straight-line motion):
      - rows > 4 sigma off the line are clipped (at most 20%) before the final fit;
      - rejected if >= 25% of its rows sit within 1.5" of a stationary source (a track with >= 4 visits over
        >= 1.5 yr and pm < 100 mas/yr): the "motion" is made of other sources' detections;
      - rejected if the first and second half of the track disagree in proper motion (> 4 sigma and > 30%);
      - rejected if chi2r > max_chi2r;
      - rejected if seen in a median of < 3 exposures per visit (marginal detections);
      - rejected if detected in < 60% of the visits that observed its predicted position (a real source does
        not vanish for years; a chimera only exists while its parts line up);
      - rejected as a blend if another source lies within 8" in >= 30% of its visits and its total motion over
        the span is < 16", i.e. it never moved clear of its neighbour.
    `rejected`, if a list, receives (reason, summary dict) for each rejected candidate (diagnostics)."""
    if not tracks:
        return []
    x, y, tp = _project_sources(vs)
    t = np.asarray(vs["epoch"], float)
    ra_all = np.asarray(vs["ra"], float)
    dec_all = np.asarray(vs["dec"], float)
    vis = np.asarray(vs["visit"], np.int64)
    nd = np.asarray(vs["n"], float) if "n" in vs else np.full(len(t), 99.0)
    n_vis = int(vis.max()) + 1
    v_epoch = np.bincount(vis, t, minlength=n_vis) / np.maximum(np.bincount(vis, minlength=n_vis), 1)
    sig = np.sqrt(np.asarray(vs["sig"], float) ** 2 + visit_sys ** 2)
    w = 1.0 / sig ** 2
    pm, perr, chi2r, nvis, x0, y0, span = _quick_fits(tracks, x, y, t, w, full=True)
    # loose preselection with the quick (no parallax, common tangent plane) fits
    cand = np.flatnonzero((nvis >= min_visits) & (pm >= 0.7 * min_pm) & (pm >= 0.6 * min_pm_snr * perr))
    if len(cand) == 0:
        return []
    stat = np.flatnonzero((nvis >= 4) & (span >= 1.5) & (pm < 100.0))
    stree = cKDTree(np.column_stack([x0[stat], y0[stat]])) if len(stat) else None
    atree = cKDTree(np.column_stack([x, y, vis * 1.0e7]))   # same-visit neighbours only (visits 1e7" apart)

    def reject(reason, c, f=None):
        if rejected is not None:
            d = {"track": int(c), "n_visits": int(nvis[c]), "pm_quick": float(pm[c])}
            if f is not None:
                d.update({k: f[k] for k in ("ra", "dec", "pm", "pm_snr", "chi2r")})
            rejected.append((reason, d))

    movers = []
    for c in cand:
        rows = tracks[c]
        if stree is not None:
            d, j = stree.query(np.column_stack([x[rows], y[rows]]), k=2, distance_upper_bound=STAT_RADIUS)
            ids = stat[np.minimum(j, len(stat) - 1)]
            hit = (np.isfinite(d) & (ids != c)).any(1)
            frac_stat = float(hit.mean())
        else:
            frac_stat = 0.0
        f, keep = _fit_clipped(t[rows], ra_all[rows], dec_all[rows], sig[rows])
        if not (f["n_visits"] >= min_visits and f["pm"] >= min_pm and f["pm_snr"] >= min_pm_snr):
            reject("criteria", c, f)
            continue
        if not (f["chi2r"] <= max_chi2r):
            reject("chi2r", c, f)
            continue
        if frac_stat >= MAX_STAT_FRAC:
            reject("stationary_rows", c, f)
            continue
        kr = rows[keep]
        if not _halves_agree(t[kr], ra_all[kr], dec_all[kr], sig[kr]):
            reject("halves", c, f)
            continue
        if np.median(nd[kr]) < MIN_NDET:
            reject("few_detections", c, f)
            continue
        # coverage: visits that observed the predicted position (any source within COVER_RADIUS of it)
        dtv = v_epoch - f["epoch0"]
        pra, pdec = from_tangent(f["pmra"] / 1000.0 * dtv, f["pmdec"] / 1000.0 * dtv, f["ra"], f["dec"])
        qx, qy = to_tangent(pra, pdec, tp[0], tp[1])
        seen = atree.query_ball_point(np.column_stack([qx, qy, np.arange(n_vis) * 1.0e7]), COVER_RADIUS,
                                      return_length=True) > 0
        coverage = len(np.unique(vis[kr])) / max(int(seen.sum()), 1)
        if coverage < MIN_COVERAGE:
            reject("coverage", c, f)
            continue
        nb = atree.query_ball_point(np.column_stack([x[kr], y[kr], vis[kr] * 1.0e7]), CROWD_RADIUS,
                                    return_length=True)
        frac_crowd = float(np.mean(nb > 1))
        if frac_crowd >= CROWD_FRAC and f["pm"] / 1000.0 * f["span_yr"] < 2 * CROWD_RADIUS:
            reject("blend", c, f)   # never moved clear of its neighbour: centroid shifts of a blend
            continue
        # final fit with the leave-one-visit-out (jackknife) error: robust to a few bad visits
        f = fit_motion(t[kr], ra_all[kr], dec_all[kr], sig[kr], parallax="auto", jackknife=True)
        if not (f["pm"] >= min_pm and f["pm_snr"] >= min_pm_snr):
            reject("jackknife", c, f)
            continue
        rows = kr
        flags = []
        if frac_crowd >= CROWD_FRAC:
            flags.append("crowded")
        if (~keep).any():
            flags.append("clipped")
        w1 = np.asarray(vs["w1"][rows], float)
        w2 = np.asarray(vs["w2"][rows], float)
        l1 = np.asarray(vs["w1lim"][rows], bool) if "w1lim" in vs else np.zeros(len(rows), bool)
        l2 = np.asarray(vs["w2lim"][rows], bool) if "w2lim" in vs else np.zeros(len(rows), bool)

        def band(m, lim):
            good = np.isfinite(m) & ~lim
            if good.sum() >= max(1, len(m) // 4):
                return float(np.median(m[good])), False
            fin = np.isfinite(m)
            return (float(np.median(m[fin])), True) if fin.any() else (None, False)
        m1, lim1 = band(w1, l1)
        m2, lim2 = band(w2, l2)
        if (m1 is not None and not lim1 and m1 < SATURATION["w1"]) or \
                (m2 is not None and not lim2 and m2 < SATURATION["w2"]):
            flags.append("saturated")
        if f["chi2r"] > 5:
            flags.append("high_chi2r")
        if scan_angle(f["ra"], f["dec"], f["pmra"], f["pmdec"]) < 10:
            flags.append("along_scan")
        if _leaves_tile(k5, f):
            flags.append("tile_edge")
        if _is_fast(rows, vs, x, y):
            flags.append("fast_search")
        if lim1:
            flags.append("w1_limit")
        if lim2:
            flags.append("w2_limit")
        order = np.argsort(t[rows])
        rr = rows[order]
        if len(rr) > 30:
            rr = rr[np.unique(np.round(np.linspace(0, len(rr) - 1, 30)).astype(int))]
        track = [[round(float(t[j]), 4), round(float(vs["ra"][j]), 7), round(float(vs["dec"][j]), 7)] for j in rr]
        movers.append({"k5": int(k5), "ra": round(f["ra"], 7), "dec": round(f["dec"], 7), "epoch": round(f["epoch0"], 3),
                       "pmra": round(f["pmra"], 1), "pmdec": round(f["pmdec"], 1), "pm": round(f["pm"], 1),
                       "pm_err": round(f["pm_err"], 2), "pm_snr": round(f["pm_snr"], 1),
                       "chi2r": _jsonable(f["chi2r"], 3), "n_visits": int(f["n_visits"]),
                       "span_yr": round(f["span_yr"], 3), "w1": _jsonable(m1, 3), "w2": _jsonable(m2, 3),
                       "w1w2": _jsonable(m1 - m2, 3) if (m1 is not None and m2 is not None) else None,
                       "plx": _jsonable(f["plx"], 1), "plx_err": _jsonable(f["plx_err"], 1),
                       "track": track, "flags": flags})
    movers.sort(key=lambda m: -m["pm_snr"])
    for i, m in enumerate(movers):
        m["id"] = f"{k5}-{i + 1:04d}"
    return [{"id": m.pop("id"), **m} for m in movers]


def _leaves_tile(k5, f):
    """True if the fitted motion would carry the source across the tile boundary between 2014.0 and 2024.7."""
    try:
        ras, decs = [], []
        for ep in (2014.0, 2024.7):
            dt = ep - f["epoch0"]
            r, d = from_tangent(f["pmra"] / 1000.0 * dt, f["pmdec"] / 1000.0 * dt, f["ra"], f["dec"])
            ras.append(float(r))
            decs.append(float(d))
        k = _tiles.tile_of(np.array(ras), np.array(decs))
        return bool(np.any(np.asarray(k) != k5))
    except Exception:  # noqa: BLE001
        return False


def _is_fast(rows, vs, x, y):
    """A velocity-search kind of track: consecutive rows (median) further apart than the FoF linking length."""
    if len(rows) < 2:
        return False
    o = np.argsort(vs["epoch"][rows])
    rr = rows[o]
    step = np.hypot(np.diff(x[rr]), np.diff(y[rr]))
    return bool(np.median(step) > LINK_RADIUS)
