"""Star profile: what a star is made of and how it compares with the Sun.

    python pipeline/star_profile.py hip8102               # one star (key or name from app/data/stars/index.json)
    python pipeline/star_profile.py --defaults            # the stars the page shows by default (targets + ready stars)

Writes app/data/stars/profile/<key>.json with:
  * physical properties, each with its source (best first):
      literature values in app/data/starquake_stars.json  >  Gaia DR3 FLAME / GSP-Phot (astrophysical_parameters)
      >  Hypatia Catalog stellar properties  >  the page estimates from the catalogue itself (left to the browser)
  * chemistry: element abundances [X/H] (dex, relative to the Sun, Asplund et al. 2009 scale) from the Hypatia Catalog
    (Hinkel et al. 2014; literature spectroscopy of FGKM stars within 500 pc), and its known planets;
  * spectrum: the star's real Gaia DR3 XP (BP/RP) sampled spectrum, 336-1020 nm, via the Gaia DataLink service.
Missing pieces are left out; nothing is invented. Queries are cached in data/cache/stars/<key>/.
"""
import argparse, csv, hashlib, io, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import star_ml as M                                   # identify(), cached_tap(), tap(), load_index(), find()

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"
OUT = DATA / "stars" / "profile"
CACHE = ROOT / "data" / "cache" / "stars"
HYPATIA = "https://hypatiacatalog.com/hypatia/api/v2"
DATALINK = "https://gea.esac.esa.int/data-server/data"
ELEMENTS = ["Li", "C", "N", "O", "Na", "Mg", "Al", "Si", "S", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni",
            "Cu", "Zn", "Sr", "Y", "Zr", "Ba", "La", "Ce", "Nd", "Eu"]


def http(url, key, kind, timeout=90):
    """Cached GET (text)."""
    f = CACHE / key / f"{kind}-{hashlib.sha1(url.encode()).hexdigest()[:16]}.txt"
    if f.exists():
        return f.read_text()
    for k in range(3):
        try:
            txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WANDERERS/1.0"}), timeout=timeout).read().decode()
            break
        except Exception:
            if k == 2:
                raise
            time.sleep(3 * (k + 1))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(txt)
    return txt


def names_for(row, gaia_id):
    out = []
    if row.get("hip"):
        out.append(f"HIP {row['hip']}")
    out += [a for a in row.get("aliases", []) if re.match(r"^(HD|Gl|GJ) ", a)]
    if gaia_id:
        out.append(f"Gaia DR3 {gaia_id}")
    return out


def hypatia(row, gaia_id, key):
    """Hypatia star properties, planets and [X/H] for ELEMENTS (Asplund 2009 solar scale)."""
    for name in names_for(row, gaia_id):
        try:
            star = json.loads(http(f"{HYPATIA}/star/?{urllib.parse.quote(name)}", key, "hyp-star"))
        except Exception:
            continue
        if not star or not isinstance(star, list) or star[0].get("status") != "found":
            continue
        q = urllib.parse.urlencode([("name", name)] * len(ELEMENTS) + [("element", e.lower()) for e in ELEMENTS]
                                   + [("solarnorm", "asplund09")] * len(ELEMENTS))
        comp = json.loads(http(f"{HYPATIA}/composition/?{q}", key, "hyp-comp"))
        ab = {}
        for e, c in zip(ELEMENTS, comp if isinstance(comp, list) else []):
            if isinstance(c, dict) and c.get("mean") is not None:
                ab[e] = {"x_h": round(float(c["mean"]), 3), "spread": round(float(c.get("plusminus") or c.get("std") or 0), 3),
                         "n_catalogs": len(c.get("catalogs_linear") or {})}
        s = star[0]
        planets = [{"name": p.get("name"), "mass_mjup": p.get("m_p"), "period_d": p.get("p"), "a_au": p.get("a"), "e": p.get("e")}
                   for p in (s.get("planets") or []) if p.get("name")]
        return {"matched_as": name, "teff": s.get("teff"), "logg": s.get("logg"), "spec": s.get("spec"), "disk": s.get("disk"),
                "abundances": ab, "planets": planets,
                "source": "Hypatia Catalog (Hinkel et al. 2014, AJ 148, 54), hypatiacatalog.com; solar scale Asplund et al. 2009"}
    return None


def gaia_params(gaia_id):
    rows = M.tap("SELECT s.source_id, s.phot_g_mean_mag, s.bp_rp, s.parallax, s.has_xp_sampled, a.teff_gspphot, a.logg_gspphot, "
                 "a.mh_gspphot, a.radius_flame, a.lum_flame, a.mass_flame, a.age_flame, a.evolstage_flame, a.radius_gspphot "
                 f"FROM gaiadr3.gaia_source s LEFT JOIN gaiadr3.astrophysical_parameters a ON a.source_id = s.source_id WHERE s.source_id = {int(gaia_id)}")
    if not rows:
        return None
    r = {k: v for k, v in rows[0].items() if v not in ("", None)}
    num = lambda k: float(r[k]) if k in r else None
    return {"source_id": r["source_id"], "g_mag": num("phot_g_mean_mag"), "bp_rp": num("bp_rp"), "has_xp": r.get("has_xp_sampled") == "true",
            "teff": num("teff_gspphot"), "logg": num("logg_gspphot"), "mh": num("mh_gspphot"), "radius": num("radius_flame") or num("radius_gspphot"),
            "lum": num("lum_flame"), "mass": num("mass_flame"), "age_gyr": num("age_flame")}


def xp_spectrum(gaia_id, key):
    url = f"{DATALINK}?RETRIEVAL_TYPE=XP_SAMPLED&ID={int(gaia_id)}&FORMAT=csv&RELEASE=Gaia%20DR3"
    txt = http(url, key, "xp")
    rows = list(csv.DictReader(io.StringIO(txt)))
    if not rows or "wavelength" not in rows[0]:
        return None
    wl = [float(r["wavelength"]) for r in rows]
    fl = [float(r["flux"]) for r in rows]
    er = [float(r["flux_error"]) for r in rows]
    peak = max(fl) or 1.0
    return {"wavelength_nm": wl, "flux": [round(f / peak, 4) for f in fl], "flux_error": [round(e / peak, 4) for e in er],
            "units": "flux per wavelength, scaled to 1 at the peak",
            "source": "Gaia DR3 XP (BP/RP) sampled mean spectrum, ESA Gaia DataLink (De Angeli et al. 2023; Montegriffo et al. 2023)"}


def pick(*cands):
    """First candidate with a value: (value, source)."""
    for v, src in cands:
        if v is not None and v == v:
            return {"value": round(float(v), 4), "source": src}
    return None


def build(row, info, gaia, hyp):
    lit = info or {}
    lit_src = lit.get("params_ref") or lit.get("ref") or "literature"
    hyp_t = hyp and hyp.get("teff")
    props = {
        "mass": pick((lit.get("M"), lit_src), (gaia and gaia["mass"], "Gaia DR3 FLAME")),
        "radius": pick((lit.get("R"), lit_src), (gaia and gaia["radius"], "Gaia DR3 FLAME / GSP-Phot")),
        "teff": pick((lit.get("teff"), lit_src), (hyp_t, "Hypatia Catalog (spectroscopic)"), (gaia and gaia["teff"], "Gaia DR3 GSP-Phot")),
        "luminosity": pick((gaia and gaia["lum"], "Gaia DR3 FLAME")),
        "logg": pick((hyp and hyp.get("logg"), "Hypatia Catalog"), (gaia and gaia["logg"], "Gaia DR3 GSP-Phot")),
        "age_gyr": pick((gaia and gaia["age_gyr"], "Gaia DR3 FLAME")),
    }
    fe = hyp and hyp["abundances"].get("Fe")
    props["metallicity"] = pick((fe and fe["x_h"], "Hypatia Catalog [Fe/H]"), (gaia and gaia["mh"], "Gaia DR3 GSP-Phot [M/H] (rough photometric estimate)"))
    return {k: v for k, v in props.items() if v}


def run(row, log=print):
    key = row["key"]
    info = json.loads((DATA / "starquake_stars.json").read_text()).get(key)
    star = dict(row)
    ident = M.identify(star, log)
    m = re.search(r"Gaia DR3 (\d+)", ident or "")
    gaia_id = int(m.group(1)) if m else row.get("gaia_dr3")
    gaia = gaia_params(gaia_id) if gaia_id else None
    hyp = hypatia(row, gaia_id, key)
    spec = xp_spectrum(gaia_id, key) if gaia and gaia.get("has_xp") else None
    res = {"key": key, "name": row["name"], "gaia_dr3": str(gaia_id) if gaia_id else None,
           "properties": build(row, info, gaia, hyp), "gaia": gaia,
           "chemistry": {k: hyp[k] for k in ("abundances", "source", "matched_as", "spec", "disk")} if hyp and hyp["abundances"] else None,
           "planets": hyp["planets"] if hyp and hyp["planets"] else [], "spectrum": spec, "computed": time.strftime("%Y-%m-%d")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{key}.json").write_text(json.dumps(res, separators=(",", ":")))
    p = res["properties"]
    log(f"== {row['name']} ({key}): " + ", ".join(f"{k} {v['value']:g}" for k, v in p.items())
        + f"; {len(res['chemistry']['abundances']) if res['chemistry'] else 0} elements; {len(res['planets'])} planets; XP {'yes' if spec else 'no'}")
    return res


def default_keys(stars):
    """Stars the page shows by default: the analysed targets and every star with a learnt path."""
    keys = []
    ready = DATA / "stars" / "pred" / "index.json"
    if ready.exists():
        keys += json.loads(ready.read_text())
    for t in json.loads((DATA / "index.json").read_text()):
        s = M.find(stars, t["name"]) or next((x for x in stars if x.get("wanderers") == t["id"]), None)
        if s:
            keys.append(s["key"])
    return list(dict.fromkeys(keys))


def write_index():
    if OUT.exists():
        (OUT / "index.json").write_text(json.dumps(sorted(p.stem for p in OUT.glob("*.json") if p.stem != "index")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Star profile: properties vs the Sun, chemistry, real spectrum")
    ap.add_argument("stars", nargs="*")
    ap.add_argument("--defaults", action="store_true")
    a = ap.parse_args(argv)
    stars = M.load_index()
    wanted = (default_keys(stars) if a.defaults else []) + a.stars
    if not wanted:
        ap.error("give a star or --defaults")
    bad = 0
    for q in wanted:
        row = M.find(stars, q)
        if not row:
            print(f"!! {q}: not in the star database", flush=True); bad += 1; continue
        try:
            run(row, log=lambda s: print(s, flush=True))
        except Exception as e:
            print(f"!! {row['name']}: {e}", flush=True); bad += 1
    write_index()
    return 1 if bad and len(wanted) == 1 else 0


if __name__ == "__main__":
    sys.exit(main())
