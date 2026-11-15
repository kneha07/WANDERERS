"""Learn a star's past and future path from its measured positions with a classical ML model.

    python pipeline/star_ml.py hip87937                    # a key from app/data/stars/index.json
    python pipeline/star_ml.py "Barnard's Star" Proxima    # or a name / alias (first match)
    python pipeline/star_ml.py --showcase                  # the precomputed set the static page ships with

Writes app/data/stars/pred/<key>.json for the page's star search.

Data. Every position the star has in public astrometric catalogues, each at the date it was observed:
plates (GSC 2.3, ~1950-2000), Hipparcos-2 (1991.25), Tycho-2 / UCAC4 / PPMXL (mean epochs), 2MASS (single
night, ~1998-2001), AllWISE, Pan-STARRS1, URAT1, CatWISE2020, Gaia DR1/DR2/DR3 (2015.0/2015.5/2016.0),
plus WANDERERS' own WISE/SPHEREx centroids for the repo's targets. All are queried from the ESA Gaia archive
TAP service (which hosts the external catalogues), by cone search around where the star should be, and
cached in data/cache/stars/. Catalogues that give J2000 positions with their own proper motion (Tycho-2,
UCAC4, PPMXL) are moved back to their mean observing epoch, where the position does not depend on that motion.

Model. scikit-learn HuberRegressor (robust linear regression, Huber 1964), trained per star on
tangent-plane offsets (xi = RA*cos(Dec), eta = Dec, in mas). Each measured coordinate is one training row;
rows are whitened by their uncertainty. Three feature sets are compared:
    linear            offset_0 + mu * (t - 2000)
    linear+parallax   ... + parallax * (Earth-orbit parallax factor), for single-epoch catalogues
    accel+parallax    ... + acceleration * (t - 2000)^2 / 2
Leave-one-catalogue-out cross-validation picks the feature set (the simpler one wins unless the richer one
is clearly better). A bootstrap over catalogues gives the 68% uncertainty band. The page is told plainly
that the model is fitted per star and was not pretrained elsewhere.

Validation, written into the output:
  * Gaia hold-out: retrain without any Gaia data, predict where Gaia DR3 saw the star in 2016.0, report the miss.
  * Learnt proper motion and parallax are compared with Gaia DR3's own values.
  * The learnt path is compared with straight propagation of the Gaia DR3 solution (pipeline/star_trajectory.py)
    in 1900 and 2100.
"""
import argparse, csv, hashlib, io, json, sys, time, urllib.parse, urllib.request, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.model_selection import LeaveOneGroupOut

sys.path.insert(0, str(Path(__file__).resolve().parent))
import star_trajectory as physics                       # parallax factors + Gaia-propagation baseline

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "stars"
DATA = ROOT / "app" / "data"
OUT = DATA / "stars" / "pred"
TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
T0 = 2000.0                                             # time origin of the features
MAS_PER_DEG = 3.6e6
SHOWCASE = ["Barnard's Star", "Proxima Centauri", "Sirius", "Rigil Kentaurus", "Kapteyn's Star", "Groombridge 1830",
            "Lacaille 9352", "Arcturus", "61 Cygni", "Lalande 21185", "Epsilon Indi B", "WISE 0855-0714",
            "RW Aurigae", "R Draconis", "Polaris", "Vega", "Tau Ceti", "Luyten's Star"]


def jy_jd(jd):
    return 2000.0 + (np.asarray(jd, float) - 2451545.0) / 365.25


def jy_mjd(mjd):
    return jy_jd(np.asarray(mjd, float) + 2400000.5)


# ---- catalogues -------------------------------------------------------------------------------------------
# name: table, columns, (lo, hi) epoch range for the cone, row -> list of (axis, epoch, value_deg, sigma_mas),
# error floor (mas) for frame/systematic errors, and what kind of position the catalogue gives:
#   "bary"   barycentric position from a full astrometric solution (Hipparcos, Gaia): no parallax shift
#   "single" one night / one plate (2MASS, GSC): shifted by the parallax at that date -> parallax feature
#   "mean"   average of several dates (AllWISE, URAT1, ...): partly averaged parallax shift, which the
#            catalogue's own error does not include -> error widened by half the expected parallax
def _ax(r, ra, de, ep_ra, ep_de, e_ra, e_de):
    return [(0, ep_ra, float(r[ra]), e_ra), (1, ep_de, float(r[de]), e_de)]


def _f(r, k, scale=1.0, default=None):
    try:
        v = float(r[k]); return v * scale if np.isfinite(v) else default
    except (KeyError, TypeError, ValueError):
        return default


def _back(r, ra, de, pmra, pmde, ep_ra, ep_de):
    """J2000 position + the catalogue's own proper motion -> position at the mean epoch of each axis."""
    d2000 = float(r[de]); er, ed = float(r[ep_ra]), float(r[ep_de])
    dec = d2000 + _f(r, pmde, default=0) * (ed - 2000) / MAS_PER_DEG
    ra_ = float(r[ra]) + _f(r, pmra, default=0) * (er - 2000) / MAS_PER_DEG / np.cos(np.radians(d2000))
    return ra_, dec, er, ed


def _tycho(r):
    ra_, dec, er, ed = _back(r, "ra_mdeg", "de_mdeg", "pm_ra", "pm_de", "ep_ra_m", "ep_de_m")
    return [(0, er, ra_, _f(r, "e_ra_mdeg", default=100)), (1, ed, dec, _f(r, "e_de_mdeg", default=100))]


def _ucac4(r):
    ra_, dec, er, ed = _back(r, "ra", "dec", "pmra", "pmde", "mean_epoch_ra", "mean_epoch_dec")
    return [(0, er, ra_, _f(r, "ra_error_mean_epoch", default=100)), (1, ed, dec, _f(r, "dec_error_mean_epoch", default=100))]


def _ppmxl(r):
    ra_, dec, er, ed = _back(r, "ra", "dec", "pmra", "pmde", "epra", "epde")
    return [(0, er, ra_, _f(r, "ra_error_epra", default=200)), (1, ed, dec, _f(r, "dec_error_epde", default=200))]


CATALOGUES = {
    "GSC 2.3 (plates)": dict(table="gaiadr1.gsc23_original_valid", cols="ra,dec,ra_error,dec_error,position_epoch,v_mag",
                             span=(1950, 2000), plx="single", floor=150,
                             obs=lambda r: _ax(r, "ra", "dec", float(r["position_epoch"]), float(r["position_epoch"]),
                                               _f(r, "ra_error", 1000, 300), _f(r, "dec_error", 1000, 300))),
    "Hipparcos-2": dict(table="public.hipparcos_newreduction", cols="hip,ra,dec,e_ra_rad,e_de_rad,hp_mag", span=(1991.25, 1991.25),
                        plx="bary", floor=1.0,
                        obs=lambda r: _ax(r, "ra", "dec", 1991.25, 1991.25, _f(r, "e_ra_rad", default=5), _f(r, "e_de_rad", default=5))),
    "Tycho-2": dict(table="public.tycho2", cols="ra_mdeg,de_mdeg,e_ra_mdeg,e_de_mdeg,ep_ra_m,ep_de_m,pm_ra,pm_de,vt_mag",
                    span=(2000, 2000), racol="ra_mdeg", deccol="de_mdeg", plx="mean", floor=20, obs=_tycho),
    "UCAC4": dict(table="gaiadr1.ucac4_original_valid",
                  cols="ra,dec,ra_error_mean_epoch,dec_error_mean_epoch,mean_epoch_ra,mean_epoch_dec,pmra,pmde,maga",
                  span=(2000, 2000), plx="mean", floor=20, obs=_ucac4),
    "PPMXL": dict(table="gaiadr1.ppmxl_original_valid", cols="ra,dec,ra_error_epra,dec_error_epde,epra,epde,pmra,pmde",
                  span=(2000, 2000), plx="mean", floor=100, obs=_ppmxl),
    "2MASS": dict(table="gaiadr1.tmass_original_valid", cols="ra,dec,err_maj,j_date,j_m", span=(1997, 2001.2), plx="single", floor=60,
                  obs=lambda r: _ax(r, "ra", "dec", float(jy_jd(float(r["j_date"]))), float(jy_jd(float(r["j_date"]))),
                                    _f(r, "err_maj", 1000, 100), _f(r, "err_maj", 1000, 100))),
    "AllWISE": dict(table="gaiadr1.allwise_original_valid", cols="ra,dec,ra_error,dec_error,w1mjd_mean,w1mpro", span=(2010, 2011),
                    plx="mean", floor=50,
                    obs=lambda r: _ax(r, "ra", "dec", float(jy_mjd(float(r["w1mjd_mean"]))), float(jy_mjd(float(r["w1mjd_mean"]))),
                                      _f(r, "ra_error", 1000, 300), _f(r, "dec_error", 1000, 300))),
    "Pan-STARRS1": dict(table="gaiadr2.panstarrs1_original_valid", cols="ra,dec,ra_error,dec_error,epoch_mean,r_mean_psf_mag",
                        span=(2010, 2014.5), plx="mean", floor=20, max_rows=400,
                        obs=lambda r: _ax(r, "ra", "dec", float(jy_mjd(float(r["epoch_mean"]))), float(jy_mjd(float(r["epoch_mean"]))),
                                          _f(r, "ra_error", 1000, 100), _f(r, "dec_error", 1000, 100))),
    "URAT1": dict(table="gaiadr1.urat1_original_valid", cols="ra,dec,ra_error,dec_error,epoch,f_mag", span=(2012.3, 2015.3),
                  plx="mean", floor=10,
                  obs=lambda r: _ax(r, "ra", "dec", float(r["epoch"]), float(r["epoch"]), _f(r, "ra_error", 1000, 50), _f(r, "dec_error", 1000, 50))),
    "CatWISE2020": dict(table="external.catwise2020", cols="ra_icrs,de_icrs,e_ra_icrs,e_de_icrs,mjd,w1mpro_pm", span=(2013, 2018),
                        racol="ra_icrs", deccol="de_icrs", plx="mean", floor=50,
                        obs=lambda r: _ax(r, "ra_icrs", "de_icrs", float(jy_mjd(float(r["mjd"]))), float(jy_mjd(float(r["mjd"]))),
                                          _f(r, "e_ra_icrs", 1000, 300), _f(r, "e_de_icrs", 1000, 300))),
    "Gaia DR1": dict(table="gaiadr1.gaia_source", cols="source_id,ra,dec,ra_error,dec_error,phot_g_mean_mag", span=(2015.0, 2015.0),
                     plx="bary", floor=2.0, gaia=True,
                     obs=lambda r: _ax(r, "ra", "dec", 2015.0, 2015.0, _f(r, "ra_error", default=5), _f(r, "dec_error", default=5))),
    "Gaia DR2": dict(table="gaiadr2.gaia_source", cols="source_id,ra,dec,ra_error,dec_error,phot_g_mean_mag", span=(2015.5, 2015.5),
                     plx="bary", floor=2.0, gaia=True,
                     obs=lambda r: _ax(r, "ra", "dec", 2015.5, 2015.5, _f(r, "ra_error", default=5), _f(r, "dec_error", default=5))),
    "Gaia DR3": dict(table="gaiadr3.gaia_source",
                     cols="source_id,ra,dec,ra_error,dec_error,phot_g_mean_mag,pmra,pmdec,pmra_error,pmdec_error,parallax,parallax_error,radial_velocity",
                     span=(2016.0, 2016.0), plx="bary", floor=2.0, gaia=True,
                     obs=lambda r: _ax(r, "ra", "dec", 2016.0, 2016.0, _f(r, "ra_error", default=5), _f(r, "dec_error", default=5))),
}


def tap(adql, timeout=120, tries=3):
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}).encode()
    for k in range(tries):
        try:
            txt = urllib.request.urlopen(TAP, data, timeout=timeout).read().decode()
            if txt.lstrip().startswith("<"):
                raise RuntimeError(txt[:300])
            return list(csv.DictReader(io.StringIO(txt)))
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


def cone(key, cat, ra, dec, radius_deg):
    """Cached cone search of one catalogue."""
    spec = CATALOGUES[cat]
    rc, dc = spec.get("racol", "ra"), spec.get("deccol", "dec")
    q = (f"SELECT TOP {spec.get('max_rows', 200)} {spec['cols']} FROM {spec['table']} WHERE "
         f"1=CONTAINS(POINT('ICRS',{rc},{dc}),CIRCLE('ICRS',{ra:.7f},{dec:.7f},{radius_deg:.6f}))")
    f = CACHE / key / f"{hashlib.sha1(q.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())
    rows = tap(q)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"query": q, "catalogue": cat, "rows": rows}))
    return {"query": q, "catalogue": cat, "rows": rows}


# ---- tangent plane -------------------------------------------------------------------------------------------
def to_plane(ra, dec, ra0, dec0):
    """Gnomonic projection -> (xi, eta) in mas about (ra0, dec0)."""
    a, d, a0, d0 = map(np.radians, (ra, dec, ra0, dec0))
    D = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / D
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / D
    return np.degrees(xi) * MAS_PER_DEG, np.degrees(eta) * MAS_PER_DEG


def from_plane(xi, eta, ra0, dec0):
    x, y = np.radians(np.asarray(xi) / MAS_PER_DEG), np.radians(np.asarray(eta) / MAS_PER_DEG)
    a0, d0 = np.radians(ra0), np.radians(dec0)
    den = np.cos(d0) - y * np.sin(d0)
    a = a0 + np.arctan2(x, den)
    d = np.arctan2(np.sin(d0) + y * np.cos(d0), np.hypot(x, den))
    return np.degrees(a) % 360, np.degrees(d)


def plx_factors(ra0, dec0, t):
    """Parallax factors (shift per 1 mas of parallax) along xi and eta."""
    return physics.parallax_offsets(ra0, dec0, np.atleast_1d(t), 1.0)


# ---- the model ------------------------------------------------------------------------------------------------
MODELS = {"linear": [0, 1, 2, 3], "linear+parallax": [0, 1, 2, 3, 4],
          "accel": [0, 1, 2, 3, 5, 6], "accel+parallax": [0, 1, 2, 3, 4, 5, 6]}
PARAMS = ["xi0", "eta0", "pm_xi", "pm_eta", "parallax", "acc_xi", "acc_eta"]


def features(axis, t, plx_on, ra0, dec0):
    """Design matrix: one row per measured coordinate. axis 0 = xi (RA*), 1 = eta (Dec)."""
    axis, t, plx_on = np.asarray(axis), np.asarray(t, float), np.asarray(plx_on, bool)
    dt = t - T0
    fx, fy = plx_factors(ra0, dec0, t)
    X = np.zeros((len(t), 7))
    X[:, 0] = axis == 0
    X[:, 1] = axis == 1
    X[:, 2] = (axis == 0) * dt
    X[:, 3] = (axis == 1) * dt
    X[:, 4] = np.where(plx_on, np.where(axis == 0, fx, fy), 0.0)
    X[:, 5] = (axis == 0) * dt ** 2 / 2
    X[:, 6] = (axis == 1) * dt ** 2 / 2
    return X


class StarPathModel:
    """HuberRegressor on whitened, column-scaled rows; predicts (xi, eta) at any time."""

    def __init__(self, model="linear", epsilon=1.35):
        self.model, self.cols, self.epsilon = model, MODELS[model], epsilon

    def fit(self, X, y, sigma):
        Xw = X[:, self.cols] / sigma[:, None]
        yw = y / sigma
        self.scale_ = np.where(np.abs(Xw).max(0) > 0, np.abs(Xw).max(0), 1.0)
        self.yscale_ = max(np.abs(yw).max(), 1.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            self.reg_ = HuberRegressor(epsilon=self.epsilon, alpha=0.0, fit_intercept=False, max_iter=5000, tol=1e-10)
            self.reg_.fit(Xw / self.scale_, yw / self.yscale_)
        self.coef_ = np.zeros(7)
        self.coef_[self.cols] = self.reg_.coef_ / self.scale_ * self.yscale_
        self.outliers_ = self.reg_.outliers_
        return self

    def predict_rows(self, X):
        return X @ self.coef_

    def predict(self, t, ra0, dec0, parallax=True):
        t = np.atleast_1d(np.asarray(t, float))
        on = np.full(len(t), parallax)
        xi = self.predict_rows(features(np.zeros(len(t), int), t, on, ra0, dec0))
        eta = self.predict_rows(features(np.ones(len(t), int), t, on, ra0, dec0))
        return xi, eta


def training_set(obs, ra0, dec0, use=None):
    """obs -> (X, y, sigma, groups) with one row per coordinate."""
    rows = [o for o in obs if use is None or use(o)]
    if not rows:
        raise ValueError("no observations")
    axis = np.array([o["axis"] for o in rows], int)
    t = np.array([o["epoch"] for o in rows], float)
    xi, eta = to_plane(np.array([o["ra"] for o in rows]), np.array([o["dec"] for o in rows]), ra0, dec0)
    y = np.where(axis == 0, xi, eta)
    sig = np.array([np.sqrt(o["sigma_mas"] ** 2 + o["floor_mas"] ** 2 + o.get("plx_slack_mas", 0) ** 2) for o in rows])
    X = features(axis, t, [o["plx"] == "single" for o in rows], ra0, dec0)
    groups = np.array([o["catalogue"] for o in rows])
    return X, y, sig, groups


def cv_score(model, X, y, sig, groups):
    """Leave-one-catalogue-out cross-validation. Score = mean held-out chi^2 per row, each row capped at
    25 (5 sigma) so one mismatched catalogue cannot decide; also the median miss in mas."""
    if len(set(groups)) < 3:
        return None
    z2, mas = [], []
    for tr, te in LeaveOneGroupOut().split(X, y, groups):
        if len(set(groups[tr])) < 2 or np.ptp(X[tr][:, 2] + X[tr][:, 3]) < 5 or len(tr) < len(MODELS[model]) + 1:
            continue
        m = StarPathModel(model).fit(X[tr], y[tr], sig[tr])
        r = y[te] - m.predict_rows(X[te])
        z2 += list(np.minimum((r / sig[te]) ** 2, 25.0)); mas += list(np.abs(r))
    return {"chi2": float(np.mean(z2)), "median_mas": float(np.median(mas)), "n_rows": len(z2)} if z2 else None


def robust_chi2(model, X, y, sig):
    r = (y - model.predict_rows(X)) / sig
    return float(np.sum(np.minimum(r ** 2, 25.0)))


def noise_scale(model, X, y, sig):
    """How much more the data scatter than their stated errors: 1.4826 x median |residual / sigma| (MAD),
    at least 1. Robust, so one mismatched catalogue neither hides nor inflates it."""
    z = (y - model.predict_rows(X)) / sig
    return max(1.0, 1.4826 * float(np.median(np.abs(z))))


def covariance(model, X, y, sig):
    """Weighted least-squares covariance of the learnt coefficients, scaled by the robust noise scale."""
    A = X[:, model.cols] / sig[:, None]
    k2 = noise_scale(model, X, y, sig) ** 2
    cov = np.full((7, 7), np.nan)
    try:
        cov[np.ix_(model.cols, model.cols)] = np.linalg.inv(A.T @ A) * k2
    except np.linalg.LinAlgError:
        pass
    return cov


def max_acceleration(model):
    """Largest acceleration (mas/yr^2) physics allows: perspective acceleration 2 mu v_r / d with
    |v_r| <= 300 km/s, using the learnt motion and parallax, plus 0.3 mas/yr^2 for an unseen companion."""
    mu = np.hypot(model.coef_[2], model.coef_[3])                       # mas/yr
    plx = max(model.coef_[4], 0.0) if 4 in model.cols else 0.0
    return 2 * mu * 300 * (plx / 1000) * 1.0227e-6 + 0.3


def physical(model, X, y, sig, plx_hint=0.0):
    """Extra terms must be real and possible: parallax positive, >= 3 sigma and below 1000 mas;
    acceleration >= 3 sigma on some axis and no larger than max_acceleration()."""
    cov = covariance(model, X, y, sig)
    err = np.sqrt(np.diag(cov))
    c = model.coef_
    why = []
    if 4 in model.cols and not (0 < c[4] < 1000 and np.isfinite(err[4]) and c[4] >= 3 * err[4]):
        why.append(f"parallax {c[4]:.0f} +/- {err[4]:.0f} mas is not a 3-sigma positive, physical detection")
    if 5 in model.cols:
        acc = float(np.hypot(c[5], c[6]))
        if not (np.isfinite(err[5]) and max(abs(c[5]) / err[5], abs(c[6]) / err[6]) >= 3):
            why.append("acceleration is below 3 sigma")
        else:
            m2 = StarPathModel(model.model); m2.coef_ = c.copy(); m2.cols = model.cols
            if 4 not in model.cols:
                m2.coef_[4] = plx_hint; m2.cols = model.cols + [4]
            lim = max_acceleration(m2)
            if acc > lim:
                why.append(f"acceleration {acc:.2f} mas/yr^2 exceeds the {lim:.2f} physics allows "
                           "(likely a blended or mismatched catalogue position, not motion)")
    return not why, why


def choose(X, y, sig, groups, plx_hint=0.0):
    """Pick the feature set by BIC on the robust fit (chi^2 with each row capped at 5 sigma, plus
    k ln n), among models whose extra terms are physically significant (see physical()).
    Leave-one-catalogue-out CV scores are computed too and reported, but with ~10 catalogues of very
    unequal precision, dropping Hipparcos or Gaia leaves a richer model unconstrained, so CV alone
    under-rates real effects such as perspective acceleration."""
    n = len(y)
    scores = {}
    for m, cols in MODELS.items():
        if n < 2 * len(cols):
            continue
        fit = StarPathModel(m).fit(X, y, sig)
        chi2 = robust_chi2(fit, X, y, sig)
        ok, why = physical(fit, X, y, sig, plx_hint) if m != "linear" else (True, [])
        scores[m] = {"chi2": round(chi2, 2), "k": len(cols), "bic": round(chi2 + len(cols) * np.log(n), 2),
                     "allowed": ok, "rejected_because": why, "cv": cv_score(m, X, y, sig, groups)}
    allowed = [m for m in scores if scores[m]["allowed"]]
    if not allowed:
        return "linear", scores
    return min(allowed, key=lambda m: scores[m]["bic"]), scores


def param_bootstrap(model_name, X, y, sig, n=200, seed=0):
    """Parametric bootstrap: refit on the learnt path plus noise drawn from each row's uncertainty
    (scaled up by the robust reduced chi^2 when the data scatter more than their stated errors)."""
    base = StarPathModel(model_name).fit(X, y, sig)
    yhat = base.predict_rows(X)
    k = noise_scale(base, X, y, sig)
    rng = np.random.default_rng(seed)
    return np.array([StarPathModel(model_name).fit(X, yhat + rng.normal(0, sig * k), sig).coef_ for _ in range(n)]), float(k)


# ---- data collection -----------------------------------------------------------------------------------------
def guess_position(star, t):
    """Where the star should be at t, from the best catalogue solution found by identify(). Used only to
    find the star in each survey (which candidate is it?); the training values are the surveys' own."""
    t = float(t)
    if star.get("_guess"):
        r, d = physics.predict(star["_guess"], [t], parallax=False)
        return float(r[0]) % 360, float(d[0])
    ep = star.get("epoch", 2000.0)
    d = star["dec"] + (star["pmdec"] or 0) * (t - ep) / MAS_PER_DEG
    r = star["ra"] + (star["pmra"] or 0) * (t - ep) / MAS_PER_DEG / np.cos(np.radians(d))
    return r % 360, d


def cached_tap(key, q):
    f = CACHE / key / f"{hashlib.sha1(q.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())["rows"]
    rows = tap(q)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"query": q, "rows": rows}))
    return rows


GAIA_COLS = "g.source_id,g.ra,g.dec,g.pmra,g.pmdec,g.parallax,g.radial_velocity,g.phot_g_mean_mag"


def _gaia_ref(row):
    if not row.get("pmra"):
        return None
    return {"ra": float(row["ra"]), "dec": float(row["dec"]), "epoch": 2016.0, "pmra": float(row["pmra"]),
            "pmdec": float(row["pmdec"]), "parallax": _f(row, "parallax"), "radial_velocity": _f(row, "radial_velocity"),
            "source": f"Gaia DR3 {row['source_id']}"}


def identify(star, log=print):
    """Find the star's best existing astrometric solution, by catalogue number where possible:
    Gaia DR3 (by source id, or via Gaia's Hipparcos cross-match), else Hipparcos-2 by HIP number, else a
    Gaia DR3 cone search scored on position and motion together. Sets star['_guess']."""
    key = star["key"]
    try:
        if star.get("gaia_dr3"):
            rows = cached_tap(key, f"SELECT {GAIA_COLS} FROM gaiadr3.gaia_source g WHERE g.source_id={int(star['gaia_dr3'])}")
            if rows and _gaia_ref(rows[0]):
                star["_guess"] = _gaia_ref(rows[0]); return star["_guess"]["source"]
        if star.get("hip"):
            rows = cached_tap(key, f"SELECT {GAIA_COLS} FROM gaiadr3.hipparcos2_best_neighbour b JOIN gaiadr3.gaia_source g "
                                   f"ON g.source_id=b.source_id WHERE b.original_ext_source_id={int(star['hip'])}")
            if rows and _gaia_ref(rows[0]):
                star["_guess"] = _gaia_ref(rows[0]); return star["_guess"]["source"] + " (Gaia's Hipparcos cross-match)"
            h = cached_tap(key, f"SELECT hip,ra,dec,pm_ra,pm_de,plx FROM public.hipparcos_newreduction WHERE hip={int(star['hip'])}")
            if h:
                h = h[0]
                star["_guess"] = {"ra": float(h["ra"]), "dec": float(h["dec"]), "epoch": 1991.25, "pmra": float(h["pm_ra"]),
                                  "pmdec": float(h["pm_de"]), "parallax": _f(h, "plx"), "source": f"Hipparcos-2 HIP {h['hip']}"}
        # Gaia DR3 near the (Hipparcos or database) path, scored on position and motion together
        r, d = guess_position(star, 2016.0)
        base = star.get("_guess") or star
        pm = np.hypot(base.get("pmra") or 0, base.get("pmdec") or 0)
        rows = cached_tap(key, f"SELECT TOP 50 {GAIA_COLS} FROM gaiadr3.gaia_source g WHERE "
                               f"1=CONTAINS(POINT('ICRS',g.ra,g.dec),CIRCLE('ICRS',{r:.7f},{d:.7f},{(20 + 0.02 * pm) / 3600:.6f}))")
        best = None
        for row in rows:
            g = _gaia_ref(row)
            if not g:
                continue
            sep = np.hypot((g["ra"] - r) * np.cos(np.radians(d)), g["dec"] - d) * 3600
            dpm = np.hypot(g["pmra"] - (base.get("pmra") or 0), g["pmdec"] - (base.get("pmdec") or 0))
            score = sep / (5 + 0.002 * pm) + dpm / (50 + 0.05 * pm)
            if score < 2 and (best is None or score < best[0]):
                best = (score, g)
        if best:
            star["_guess"] = best[1]; return best[1]["source"] + " (matched on position and motion)"
    except Exception as e:
        log(f"   identification query failed ({str(e)[:80]}); using the database values")
    return star.get("_guess", {}).get("source") or f"{star.get('source', 'database')} values"


def collect(star, log=print):
    """Query every catalogue around the star's expected position; return candidate observations per catalogue."""
    key = star["key"]
    g = star.get("_guess") or star
    pm = np.hypot(g["pmra"] or 0, g["pmdec"] or 0) / 1000                        # arcsec/yr
    ep = g.get("epoch", 2000.0)

    def one(cat):
        spec = CATALOGUES[cat]
        lo, hi = spec["span"]
        mid = (lo + hi) / 2
        r, d = guess_position(star, mid)
        # cover the path over the catalogue's epochs, plus slack for an imperfect guess
        slack = 0.01 if star.get("_guess") else 0.15
        rad = (15 + pm * ((hi - lo) / 2 + slack * abs(mid - ep) + 1)) / 3600
        try:
            res = cone(key, cat, r, d, min(rad, 0.15))
        except Exception as e:
            return cat, [], f"query failed ({str(e)[:80]})"
        cands = []
        for row in res["rows"]:
            try:
                parts = spec["obs"](row)
            except (TypeError, ValueError, KeyError):
                continue
            if any(not np.isfinite(p[2]) or not np.isfinite(p[1]) for p in parts):
                continue
            cands.append({"parts": parts, "row": row})
        return cat, cands, None

    only = None
    if star.get("wanderers"):
        from targets import TARGETS
        only = TARGETS.get(star["wanderers"], {}).get("only_catalogues")
    cats = [c for c in CATALOGUES if only is None or c in only]
    if only:
        log(f"   only {', '.join(only)} can have detected this object (see pipeline/targets.py)")
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, cats))
    out = {}
    for cat, cands, err in results:
        if err:
            log(f"   {cat}: {err}")
        out[cat] = cands
    return out


def parallax_guess(star):
    """Expected parallax (mas) from the database distance, used only to size errors."""
    g = star.get("_guess") or {}
    if g.get("parallax"):
        return max(float(g["parallax"]), 0.0)
    if star.get("dist_pc"):
        return 1000.0 / star["dist_pc"]
    return 0.0


def match(star, cands, predict_fn, tol_fn):
    """Nearest candidate to the predicted position at its own epoch, within tolerance. Returns obs rows."""
    obs = []
    slack = 0.5 * parallax_guess(star)
    for cat, cs in cands.items():
        best = None
        for c in cs:
            if cat == "UCAC4" and abs(c["parts"][0][1] - 1991.25) < 0.01:
                continue                          # UCAC4 copies Hipparcos for Hipparcos stars: not a new measurement
            (_, te_ra, ra, s_ra), (_, te_de, dec, s_de) = c["parts"]
            t = (te_ra + te_de) / 2
            pr, pd = predict_fn(t)
            sep = np.hypot((ra - pr) * np.cos(np.radians(pd)), dec - pd) * 3600
            if sep <= tol_fn(t) and (best is None or sep < best[0]):
                best = (sep, c)
        if best is None:
            continue
        spec = CATALOGUES[cat]
        for axis, t, val, s in best[1]["parts"]:
            # each axis keeps its own position (ra or dec) and epoch
            (r_, d_) = (val, best[1]["parts"][1][2]) if axis == 0 else (best[1]["parts"][0][2], val)
            obs.append({"catalogue": cat, "axis": axis, "epoch": float(t), "ra": float(r_), "dec": float(d_),
                        "sigma_mas": float(s if s and s > 0 else spec["floor"]), "floor_mas": spec["floor"],
                        "plx": spec["plx"], "plx_slack_mas": slack if spec["plx"] == "mean" else 0.0,
                        "gaia": spec.get("gaia", False), "match_arcsec": round(float(best[0]), 3)})
    return obs


def wanderers_obs(star):
    """WANDERERS' own measured centroids (4.6 um) for the repo's targets."""
    tid = star.get("wanderers")
    f = DATA / tid / "target.json" if tid else None
    if not f or not f.exists():
        return []
    out = []
    for p in json.loads(f.read_text()).get("track", []):
        if p.get("ch", "w2") != "w2":
            continue
        name = "WANDERERS " + (p["mission"] if p["mission"] in ("WISE", "NEOWISE") else "SPHEREx")
        for axis in (0, 1):
            out.append({"catalogue": f"{name} {p['year']:.2f}", "axis": axis, "epoch": p["year"], "ra": p["ra"], "dec": p["dec"],
                        "sigma_mas": 1000.0, "floor_mas": 300.0, "plx": "single" if p["mission"] == "SPHEREx" else "mean",
                        "plx_slack_mas": 0.5 * parallax_guess(star) if p["mission"] == "WISE" else 0.0, "gaia": False,
                        "match_arcsec": None, "wanderers": True})
    return out


# ---- main entry --------------------------------------------------------------------------------------------
def load_index():
    return json.loads((DATA / "stars" / "index.json").read_text())["stars"]


def find(stars, q):
    ql = q.strip().lower()
    for s in stars:
        if s["key"].lower() == ql:
            return s
    for s in stars:
        if s["name"].lower() == ql or any(a.lower() == ql for a in s["aliases"]):
            return s
    for s in stars:
        if ql in s["name"].lower() or any(ql in a.lower() for a in s["aliases"]):
            return s
    return None


def fit_all(obs, ra0, dec0, model=None, plx_hint=0.0):
    X, y, sig, groups = training_set(obs, ra0, dec0)
    if model is None:
        model, scores = choose(X, y, sig, groups, plx_hint)
    else:
        scores = None
    m = StarPathModel(model).fit(X, y, sig)
    return m, model, scores, (X, y, sig, groups)


def run(star, log=print, now=None):
    key = star["key"]
    log(f"== {star['name']} ({key})")
    ident = identify(star, log)
    log(f"   identified via {ident}")
    ra0, dec0 = guess_position(star, T0)                 # tangent point: expected position at 2000
    cands = collect(star, log)
    # pass 1: match each survey to the identified solution. Tolerance: 1.5" + the parallax + a share of
    # the motion that grows with time from the solution's epoch (looser if only database values exist).
    g = star.get("_guess") or star
    pm = np.hypot(g["pmra"] or 0, g["pmdec"] or 0) / 1000
    ep = g.get("epoch", 2000.0)
    plx_as = parallax_guess(star) / 1000
    grow = 0.002 if star.get("_guess") else 0.1
    obs = match(star, cands, lambda t: guess_position(star, t), lambda t: 1.5 + plx_as + grow * pm * abs(t - ep))
    obs += wanderers_obs(star)
    if len({o["catalogue"] for o in obs}) < 2:
        raise RuntimeError("fewer than two catalogues have this star; cannot learn a path")
    # pass 2 (only when no catalogue solution identified the star): re-match against a first learnt path
    if not star.get("_guess"):
        m1, _, _, _ = fit_all(obs, ra0, dec0, "linear")

        def learnt(t):
            xi, eta = m1.predict([t], ra0, dec0, parallax=False)
            r, d = from_plane(xi, eta, ra0, dec0)
            return float(r[0]), float(d[0])
        obs = match(star, cands, learnt, lambda t: 1.5 + plx_as + 0.002 * pm * abs(t - 2016)) + wanderers_obs(star)
    span = max(o["epoch"] for o in obs) - min(o["epoch"] for o in obs)
    if len({o["catalogue"] for o in obs}) < 2 or span < 5:
        raise RuntimeError(f"only {len({o['catalogue'] for o in obs})} catalogue(s) over {span:.1f} years; too little to learn a path")
    for o in obs:
        log(f"   {o['catalogue']:<22} {'RA ' if o['axis'] == 0 else 'Dec'} epoch {o['epoch']:.2f}  sigma {o['sigma_mas']:.1f} mas")  if o["axis"] == 0 else None

    model, chosen, scores, (X, y, sig, groups) = fit_all(obs, ra0, dec0, plx_hint=parallax_guess(star))
    resid = y - model.predict_rows(X)
    for o, r_, s_, out in zip(obs, resid, sig, model.outliers_):
        o["resid_mas"] = round(float(r_), 2); o["resid_sigma"] = round(float(r_ / s_), 2); o["down_weighted"] = bool(out)

    # Gaia hold-out: learn without any Gaia release, predict Gaia DR3's 2016.0 position.
    holdout = None
    dr3_obs = [o for o in obs if o["catalogue"] == "Gaia DR3"]
    non_gaia = [o for o in obs if not o["gaia"]]
    if dr3_obs and len({o["catalogue"] for o in non_gaia}) >= 2 and np.ptp([o["epoch"] for o in non_gaia]) >= 5:
        mn, _, _, _ = fit_all(non_gaia, ra0, dec0, plx_hint=parallax_guess(star))   # same recipe, chosen again without Gaia
        xi_p, eta_p = mn.predict([2016.0], ra0, dec0, parallax=False)
        g_ra = next(o["ra"] for o in dr3_obs if o["axis"] == 0); g_de = next(o["dec"] for o in dr3_obs if o["axis"] == 1)
        gx, gy = to_plane(g_ra, g_de, ra0, dec0)
        holdout = {"trained_on": sorted({o["catalogue"] for o in non_gaia}), "model": mn.model,
                   "predicted_ra": float(from_plane(xi_p, eta_p, ra0, dec0)[0][0]),
                   "predicted_dec": float(from_plane(xi_p, eta_p, ra0, dec0)[1][0]),
                   "gaia_dr3_ra": g_ra, "gaia_dr3_dec": g_de,
                   "miss_mas": round(float(np.hypot(xi_p[0] - gx, eta_p[0] - gy)), 1),
                   "years_extrapolated": round(2016.0 - max(o["epoch"] for o in non_gaia if o["epoch"] < 2016.0), 1)}

    # Learnt parameters with bootstrap uncertainties, and the trajectory.
    now = now or float(np.round(time_now(), 3))
    years = np.arange(1900, 2100.01, 1.0)
    years = np.unique(np.concatenate([years, [now]]))
    xi, eta = model.predict(years, ra0, dec0, parallax=False)
    coefs, noise_scale = param_bootstrap(chosen, X, y, sig)
    def path_of(c):
        mm = StarPathModel(chosen); mm.coef_ = c
        return np.vstack(mm.predict(years, ra0, dec0, parallax=False))
    boot = np.array([path_of(c) for c in coefs])
    unc_fit = np.percentile(np.hypot(boot[:, 0, :] - xi, boot[:, 1, :] - eta), 68, axis=0)
    # If no acceleration term was chosen, an acceleration below detection can still bend the path over a
    # century (e.g. Proxima's perspective acceleration). Add 1/2 sigma_acc (t - T0)^2 in quadrature, with
    # sigma_acc from the covariance of the same model plus acceleration terms.
    sig_acc = 0.0
    if not chosen.startswith("accel"):
        alt = "accel+parallax" if "parallax" in chosen else "accel"
        if len(y) > len(MODELS[alt]):
            ma = StarPathModel(alt).fit(X, y, sig)
            e = np.sqrt(np.diag(covariance(ma, X, y, sig)))
            if np.isfinite(e[5]) and np.isfinite(e[6]):
                sig_acc = float(np.hypot(e[5], e[6]))
    unc_acc = 0.5 * sig_acc * (years - T0) ** 2
    unc = np.hypot(unc_fit, unc_acc)
    ra, dec = from_plane(xi, eta, ra0, dec0)
    path = [[round(float(t), 3), round(float(r), 7), round(float(dd), 7), round(float(a) / 1000, 3), round(float(b) / 1000, 3),
             None if not np.isfinite(u) else round(float(u) / 1000, 3)] for t, r, dd, a, b, u in zip(years, ra, dec, xi, eta, unc)]

    # fine path with the parallax loop (if the chosen model has one), 2010-2030
    fine_t = np.arange(2010.0, 2030.001, 10 / 365.25)
    fx, fy = model.predict(fine_t, ra0, dec0, parallax=True)
    fine = [[round(float(t), 4), round(float(a) / 1000, 4), round(float(b) / 1000, 4)] for t, a, b in zip(fine_t, fx, fy)]

    params = {k: float(v) for k, v in zip(PARAMS, model.coef_)}
    # robust spread (half the 16-84% range), so a rare non-converged refit cannot inflate it
    perr = {k: float(np.diff(np.percentile(coefs[:, i], [16, 84]))[0] / 2) for i, k in enumerate(PARAMS)}

    # Compare with Gaia DR3's own solution, if the star is in Gaia DR3.
    gaia = None
    g = [c["row"] for c in cands.get("Gaia DR3", [])]
    if dr3_obs:
        gra = next(o["ra"] for o in dr3_obs if o["axis"] == 0)
        row = min(g, key=lambda r: abs(float(r["ra"]) - gra) + abs(float(r["dec"]) - next(o["dec"] for o in dr3_obs if o["axis"] == 1)))
        gref = {"ra": float(row["ra"]), "dec": float(row["dec"]), "epoch": 2016.0, "pmra": _f(row, "pmra", default=0),
                "pmdec": _f(row, "pmdec", default=0), "parallax": _f(row, "parallax", default=None),
                "radial_velocity": _f(row, "radial_velocity", default=None)}
        diffs = {}
        for yr in (1900.0, 2100.0):
            pr, pd = physics.predict(gref, [yr], parallax=False)
            mx, my = model.predict([yr], ra0, dec0, parallax=False)
            px, py = to_plane(pr, pd, ra0, dec0)
            diffs[str(int(yr))] = round(float(np.hypot(mx[0] - px[0], my[0] - py[0])) / 1000, 3)
        gaia = {"source_id": row.get("source_id"), "pmra": gref["pmra"], "pmdec": gref["pmdec"], "parallax": gref["parallax"],
                "pmra_error": _f(row, "pmra_error"), "pmdec_error": _f(row, "pmdec_error"), "parallax_error": _f(row, "parallax_error"),
                "radial_velocity": gref["radial_velocity"], "ml_minus_gaia_path_arcsec": diffs}

    def at(yr):
        i = int(np.argmin(np.abs(years - yr)))
        p = path[i]
        return {"year": p[0], "ra": p[1], "dec": p[2], "unc_arcsec": p[5],
                "moved_from_2000_arcsec": round(float(np.hypot(p[3] - path[int(np.argmin(np.abs(years - 2000)))][3],
                                                               p[4] - path[int(np.argmin(np.abs(years - 2000)))][4])), 2)}

    result = {
        "key": key, "name": star["name"], "star": {k: v for k, v in star.items() if not k.startswith("_")},
        "identified_via": ident,
        "model": {"library": "scikit-learn", "estimator": "HuberRegressor (robust linear regression)",
                  "sklearn_version": __import__("sklearn").__version__,
                  "chosen_features": chosen, "selection": "BIC on the robust fit (leave-one-catalogue-out CV reported)",
                  "scores": scores,
                  "uncertainty": f"parametric bootstrap (200 refits, noise x{noise_scale:.2f})"
                                 + (f" plus an undetected acceleration of up to {sig_acc:.3f} mas/yr^2 (1 sigma)" if sig_acc else ""), "trained_on_rows": int(len(y)), "catalogues": sorted({o["catalogue"] for o in obs}),
                  "epoch_span": [round(min(o["epoch"] for o in obs), 2), round(max(o["epoch"] for o in obs), 2)],
                  "note": "Fitted per star on its own measured positions; no pretrained weights."},
        "anchor": {"ra": ra0, "dec": dec0, "note": "offsets are arcsec on the sky from this point (catalogue position at 2000)"},
        "learnt": {"pmra_mas_yr": params["pm_xi"], "pmdec_mas_yr": params["pm_eta"],
                   "pmra_err": perr["pm_xi"], "pmdec_err": perr["pm_eta"],
                   "parallax_mas": params["parallax"] if "parallax" in chosen else None,
                   "parallax_err": perr["parallax"] if "parallax" in chosen else None,
                   "acc_ra_mas_yr2": params["acc_xi"] if chosen.startswith("accel") else None,
                   "acc_dec_mas_yr2": params["acc_eta"] if chosen.startswith("accel") else None,
                   "speed_arcsec_yr": float(np.hypot(params["pm_xi"], params["pm_eta"]) / 1000),
                   "pm_epoch": T0,
                   # same motion read at Gaia DR3's epoch (adds the learnt acceleration, if any)
                   "pmra_2016": params["pm_xi"] + params["acc_xi"] * (2016.0 - T0),
                   "pmdec_2016": params["pm_eta"] + params["acc_eta"] * (2016.0 - T0)},
        "observations": obs,
        "holdout_gaia": holdout, "gaia_dr3": gaia,
        # the database's own catalogue motion (HYG = Hipparcos values; literature for WISE 0855), for stars Gaia lacks
        "catalogue_motion": {"source": star.get("source") or "HYG v4.1 (Hipparcos)", "pmra": star.get("pmra"),
                             "pmdec": star.get("pmdec"),
                             "parallax": round(1000 / star["dist_pc"], 2) if star.get("dist_pc") else None},
        "path": {"fields": ["year", "ra", "dec", "dx_arcsec", "dy_arcsec", "unc68_arcsec"], "rows": path,
                 "fine_fields": ["year", "dx_arcsec", "dy_arcsec"], "fine": fine},
        "now": now,
        "table": [at(y_) for y_ in (1900, 1950, 2000, now, 2050, 2100)],
        "computed": time.strftime("%Y-%m-%d"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{key}.json").write_text(json.dumps(result, separators=(",", ":"), default=lambda o: None if o is None else str(o)))
    L = result["learnt"]
    log(f"   model: {chosen}; learnt pm ({L['pmra_mas_yr']:.1f}, {L['pmdec_mas_yr']:.1f}) mas/yr"
        + (f", parallax {L['parallax_mas']:.1f} mas" if L["parallax_mas"] is not None else ""))
    if gaia:
        log(f"   Gaia DR3:            pm ({gaia['pmra']:.1f}, {gaia['pmdec']:.1f}) mas/yr, parallax {gaia['parallax']}")
    if holdout:
        log(f"   Gaia hold-out: trained without Gaia, predicted DR3 2016.0 position to {holdout['miss_mas']} mas")
    return result


def time_now():
    from astropy.time import Time
    return float(Time.now().jyear)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Learn star trajectories with scikit-learn (see module docstring).")
    ap.add_argument("stars", nargs="*", help="keys or names from app/data/stars/index.json")
    ap.add_argument("--showcase", action="store_true", help="the precomputed set shipped with the page")
    a = ap.parse_args(argv)
    stars = load_index()
    names = (SHOWCASE if a.showcase else []) + a.stars
    if not names:
        ap.error("give a star or --showcase")
    failed = 0
    for q in names:
        s = find(stars, q)
        if not s:
            print(f"!! {q}: not in the star database", flush=True); failed += 1; continue
        try:
            run(s, log=lambda m: print(m, flush=True))
        except Exception as e:
            print(f"!! {s['name']}: {e}", flush=True); failed += 1
    write_list()
    return 1 if failed and len(names) == 1 else 0


def write_list():
    """app/data/stars/pred/index.json: which stars have a precomputed prediction."""
    if not OUT.exists():
        return
    have = sorted(p.stem for p in OUT.glob("*.json") if p.stem != "index")
    (OUT / "index.json").write_text(json.dumps(have))


if __name__ == "__main__":
    sys.exit(main())
