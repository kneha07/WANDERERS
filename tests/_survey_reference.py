"""A small, naive mover search with the interface of survey.link.process_tile, used ONLY by the validation
tests (tests/test_survey_validate*.py) so the harness can be exercised before the real core is merged.
It is not part of the survey and is not tuned: per-visit friends-of-friends clustering, cross-visit
friends-of-friends linking, a brute-force velocity search for fast movers among the leftovers, and a weighted
linear (+ parallax) fit. See docs/survey-contract.md for the real thing."""
import math
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from survey import validate as V  # noqa: E402

CLUSTER_R = 2.5   # arcsec, same source within a visit
LINK_R = 2.5      # arcsec, stationary / slow linking between visits
LINE_TOL = 1.5    # arcsec, velocity search: distance from the line
MAX_PM = 12.0     # arcsec/yr
MIN_LINE_VISITS = 5


def _read_all(k5, reader, years):
    tabs = []
    for y in years:
        t = reader(k5, y)
        if t is not None and t.num_rows:
            tabs.append(t.cast(pa.schema([f.with_nullable(True) for f in t.schema])))
    return pa.concat_tables(tabs) if tabs else None


def _components(points, r):
    n = len(points)
    if n == 0:
        return np.zeros(0, dtype=int)
    pairs = cKDTree(points).query_pairs(r, output_type="ndarray")
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return connected_components(g, directed=False)[1]


def visit_sources(x, y, mjd, w1, w2, sig, visit):
    """One row per (visit, source) with >= 2 detections within CLUSTER_R."""
    out = {k: [] for k in ("x", "y", "mjd", "w1", "w2", "n", "sig", "visit")}
    for v in np.unique(visit):
        idx = np.nonzero(visit == v)[0]
        lab = _components(np.c_[x[idx], y[idx]], CLUSTER_R)
        cnt = np.bincount(lab)
        w = 1.0 / sig[idx] ** 2
        sw = np.bincount(lab, w)
        xm = np.bincount(lab, w * x[idx]) / sw
        ym = np.bincount(lab, w * y[idx]) / sw
        # empirical scatter about the mean (catches saturated stars whose formal errors are far too small)
        rx = np.bincount(lab, (x[idx] - xm[lab]) ** 2 + (y[idx] - ym[lab]) ** 2) / np.maximum(2 * cnt - 2, 1)
        sig_emp = np.sqrt(rx / np.maximum(cnt, 1))
        sig_formal = np.hypot(1.2 / np.sqrt(sw), 0.02)
        keep = cnt >= 2
        out["x"].append(xm[keep])
        out["y"].append(ym[keep])
        out["mjd"].append((np.bincount(lab, mjd[idx]) / cnt)[keep])
        for band, arr in (("w1", w1), ("w2", w2)):
            a = np.where(np.isfinite(arr[idx]), arr[idx], 0.0)
            ok = np.bincount(lab, np.isfinite(arr[idx]).astype(float))
            out[band].append((np.bincount(lab, a) / np.maximum(ok, 1))[keep])
        out["n"].append(cnt[keep])
        out["sig"].append(np.maximum(sig_formal, sig_emp)[keep])
        out["visit"].append(np.full(keep.sum(), v))
    return {k: np.concatenate(v) if v else np.zeros(0) for k, v in out.items()}


def fit_motion(mjd, ra, dec, sig, parallax=True):
    """Weighted linear (+ parallax) fit on the tangent plane about the mean position."""
    epoch = V.mjd_to_year(mjd)
    x, y = V.tangent_offset(ra[0], dec[0], ra, dec)
    ra_c, dec_c = V.offset_radec(ra[0], dec[0], np.mean(x), np.mean(y))
    x, y = V.tangent_offset(ra_c, dec_c, ra, dec)
    t0 = float(np.mean(epoch))
    dt = epoch - t0
    n = len(x)
    use_plx = parallax and n >= 8
    p = 5 if use_plx else 4
    A = np.zeros((2 * n, p))
    A[:n, 0], A[n:, 1], A[:n, 2], A[n:, 3] = 1, 1, dt, dt
    if use_plx:
        fe, fn = V.parallax_factors(ra_c, dec_c, mjd)
        A[:n, 4], A[n:, 4] = fe, fn
    b = np.r_[x, y]
    w = np.r_[1 / sig ** 2, 1 / sig ** 2]
    AtW = A.T * w
    cov = np.linalg.inv(AtW @ A)
    par = cov @ (AtW @ b)
    res = b - A @ par
    dof = 2 * n - p
    chi2r = float(np.sum(w * res ** 2) / dof) if dof > 0 else float("nan")
    cov = cov * max(chi2r, 1.0) if np.isfinite(chi2r) else cov
    pmx, pmy = par[2] * 1000, par[3] * 1000
    pm = math.hypot(pmx, pmy)
    var = (pmx ** 2 * cov[2, 2] + pmy ** 2 * cov[3, 3] + 2 * pmx * pmy * cov[2, 3]) * 1e6 / max(pm ** 2, 1e-12)
    pm_err = math.sqrt(max(var, 1e-12))
    ra0, dec0 = V.offset_radec(ra_c, dec_c, par[0], par[1])
    out = {"ra": float(ra0), "dec": float(dec0), "epoch0": t0, "pmra": float(pmx), "pmdec": float(pmy),
           "pm": pm, "pm_err": pm_err, "pm_snr": pm / pm_err, "chi2r": chi2r, "n_visits": n,
           "span_yr": float(epoch.max() - epoch.min()), "plx": None, "plx_err": None}
    if use_plx:
        out["plx"], out["plx_err"] = float(par[4] * 1000), float(math.sqrt(cov[4, 4]) * 1000)
    return out


def link_tracks(vs, min_visits, plx_factors=None):
    P = np.c_[vs["x"], vs["y"]]
    n = len(P)
    tracks, leftover = [], []
    lab = _components(P, LINK_R)
    order = np.argsort(lab, kind="stable")
    bounds = np.r_[0, np.nonzero(np.diff(lab[order]))[0] + 1, n]
    for a, b in zip(bounds[:-1], bounds[1:]):
        rows = order[a:b]
        if len(rows) == 0:
            continue
        med = np.median(P[rows], axis=0)
        keep = []
        for v in np.unique(vs["visit"][rows]):
            r = rows[vs["visit"][rows] == v]
            k = r[np.argmin(np.hypot(*(P[r] - med).T))]
            keep.append(k)
            leftover.extend(int(i) for i in r if i != k)
        if len(keep) >= min_visits:
            tracks.append(np.array(sorted(keep)))
        else:
            leftover.extend(keep)
    tracks.extend(_velocity_search(vs, np.array(sorted(leftover), dtype=int), plx_factors))
    return tracks


def _refine(P, t, vis, fe, fn, used, members):
    """Refit a velocity-search track (linear + parallax) and re-collect, per visit, the closest unused row
    within LINE_TOL of the fitted path. Two passes."""
    free = np.nonzero(~used)[0]
    for _ in range(2):
        tt = t[members] - t[members].mean()
        n = len(members)
        p = 5 if n >= 8 else 4
        A = np.zeros((2 * n, p))
        A[:n, 0], A[n:, 1], A[:n, 2], A[n:, 3] = 1, 1, tt, tt
        if p == 5:
            A[:n, 4], A[n:, 4] = fe[members], fn[members]
        par = np.linalg.lstsq(A, np.r_[P[members, 0], P[members, 1]], rcond=None)[0]
        dt = t[free] - t[members].mean()
        mx = par[0] + par[2] * dt + (par[4] * fe[free] if p == 5 else 0)
        my = par[1] + par[3] * dt + (par[4] * fn[free] if p == 5 else 0)
        r = np.hypot(P[free, 0] - mx, P[free, 1] - my)
        best = {}
        for k, rk in zip(free[r < LINE_TOL], r[r < LINE_TOL]):
            if vis[k] not in best or rk < best[vis[k]][1]:
                best[vis[k]] = (k, rk)
        if len(best) < MIN_LINE_VISITS:
            break
        members = np.array(sorted(b[0] for b in best.values()))
    return members


def _velocity_search(vs, L, plx_factors=None):
    if len(L) < MIN_LINE_VISITS:
        return []
    fe, fn = (plx_factors[0][L], plx_factors[1][L]) if plx_factors is not None else (np.zeros(len(L)),) * 2
    P = np.c_[vs["x"], vs["y"]][L]
    t = V.mjd_to_year(vs["mjd"][L])
    vis = vs["visit"][L]
    w2 = vs["w2"][L]
    uv = np.unique(vis)
    te = np.array([t[vis == v].mean() for v in uv])
    tree = cKDTree(P)
    used = np.zeros(len(L), bool)
    out = []
    by_visit = {v: np.nonzero(vis == v)[0] for v in uv}
    trees = {v: cKDTree(P[by_visit[v]]) for v in uv}
    for ia, va in enumerate(uv):
        for ib in range(ia + 1, len(uv)):
            vb = uv[ib]
            dtv = te[ib] - te[ia]
            if not (0.75 <= dtv <= 1.3 or 1.75 <= dtv <= 2.3):
                continue
            ra_ = by_visit[va][~used[by_visit[va]]]
            if not len(ra_):
                continue
            neigh = trees[vb].query_ball_point(P[ra_], r=MAX_PM * dtv + 2.0)
            for i, lst in zip(ra_, neigh):
                if used[i]:
                    continue
                for jb in lst:
                    j = by_visit[vb][jb]
                    if used[j] or abs(w2[i] - w2[j]) > 1.5:
                        continue
                    v = (P[j] - P[i]) / (t[j] - t[i])
                    if math.hypot(*v) < 0.1:
                        continue
                    pred = P[i] + np.outer(te - t[i], v)
                    hits = {}
                    for c, lst2 in enumerate(tree.query_ball_point(pred, r=LINE_TOL)):
                        for k in lst2:
                            if vis[k] == uv[c] and not used[k]:
                                dk = np.hypot(*(P[k] - pred[c]))
                                if c not in hits or dk < hits[c][1]:
                                    hits[c] = (k, dk)
                    if len(hits) >= MIN_LINE_VISITS:
                        members = np.array([h[0] for h in hits.values()])
                        members = _refine(P, t, vis, fe, fn, used, members)
                        used[members] = True
                        out.append(L[members])
                        break
    return out


def process_tile(k5, reader=None, years=V.YEAR_LABELS, min_visits=6, min_pm=150.0, min_pm_snr=5.0):
    t_start = time.time()
    tab = _read_all(k5, reader, years)
    center = V.tile_center(k5)
    res = {"k5": int(k5), "center": [round(center[0], 4), round(center[1], 4)], "years": list(years),
           "n_detections": 0, "n_good": 0, "n_visits": 0, "n_visit_sources": 0, "n_tracks": 0, "n_movers": 0,
           "seconds": 0.0, "movers": []}
    if tab is None:
        return res
    cols = {c: tab.column(c).to_numpy(zero_copy_only=False) for c in tab.column_names}
    good = V.good_detection_mask(cols)
    sra = np.asarray(cols["sigra"], float)
    sde = np.asarray(cols["sigdec"], float)
    good &= np.isfinite(sra) & np.isfinite(sde)
    res["n_detections"], res["n_good"] = int(tab.num_rows), int(good.sum())
    if good.sum() < 2:
        return res
    ra, dec = np.asarray(cols["ra"], float)[good], np.asarray(cols["dec"], float)[good]
    mjd = np.asarray(cols["mjd"], float)[good]
    w1 = np.asarray(cols["w1mpro"], float)[good]
    w2 = np.asarray(cols["w2mpro"], float)[good]
    sig = np.hypot(sra[good], sde[good]) / math.sqrt(2)
    ref_ra, ref_dec = float(np.median(ra)), float(np.median(dec))
    if np.ptp(ra) > 180:  # field across RA = 0
        ref_ra = float(np.median((ra + 180) % 360) - 180) % 360
    x, y = V.tangent_offset(ref_ra, ref_dec, ra, dec)
    visit = V.split_visits(mjd)
    vs = visit_sources(x, y, mjd, w1, w2, sig, visit)
    res["n_visits"], res["n_visit_sources"] = int(visit.max() + 1), int(len(vs["x"]))
    tracks = link_tracks(vs, min_visits, V.parallax_factors(ref_ra, ref_dec, vs["mjd"]) if len(vs["x"]) else None)
    res["n_tracks"] = len(tracks)
    vra, vdec = V.offset_radec(ref_ra, ref_dec, vs["x"], vs["y"])
    movers = []
    for tr in tracks:
        if len(tr) < min_visits:
            continue
        fit = fit_motion(vs["mjd"][tr], vra[tr], vdec[tr], vs["sig"][tr])
        if fit["pm"] < min_pm or fit["pm_snr"] < min_pm_snr or not fit["chi2r"] < 30:
            continue
        ep = V.mjd_to_year(vs["mjd"][tr])
        w1m, w2m = float(np.median(vs["w1"][tr])), float(np.median(vs["w2"][tr]))
        movers.append({"id": f"{k5}-{len(movers) + 1:04d}", "k5": int(k5), "ra": fit["ra"], "dec": fit["dec"],
                       "epoch": round(fit["epoch0"], 4), "pmra": fit["pmra"], "pmdec": fit["pmdec"],
                       "pm": fit["pm"], "pm_err": fit["pm_err"], "pm_snr": fit["pm_snr"], "chi2r": fit["chi2r"],
                       "n_visits": fit["n_visits"], "span_yr": fit["span_yr"], "w1": w1m, "w2": w2m,
                       "w1w2": w1m - w2m, "plx": fit["plx"], "plx_err": fit["plx_err"],
                       "track": [[float(e), float(a), float(d)] for e, a, d in zip(ep, vra[tr], vdec[tr])][:30],
                       "flags": []})
    res["movers"] = movers
    res["n_movers"] = len(movers)
    res["seconds"] = round(time.time() - t_start, 3)
    return res
