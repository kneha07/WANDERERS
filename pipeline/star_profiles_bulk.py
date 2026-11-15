"""Profiles for EVERY star in the star database, gathered in bulk.

    python pipeline/star_profiles_bulk.py            # all ~12,000 stars (about 10 minutes, cached)

The per-star pipeline (star_profile.py) is complete but slow (several live queries per star), so it only runs for the
default stars and on request. This bulk step gives every other star the same measured basics without one query each:
  * Hypatia Catalog: star properties and planets via the `star` endpoint, 100 HIP numbers per call; element abundances
    via the `data` endpoint, one call per element for all ~14,000 Hypatia stars (median over studies, Asplund 2009 scale).
  * Gaia DR3 FLAME / GSP-Phot (radius, luminosity, mass, age, Teff, log g, [M/H]) via TAP, 1,000 stars per query,
    joined through Gaia's official Hipparcos cross-match.
Writes app/data/stars/profile_bulk/<shard>.json, shard = HIP number mod 100 (stars without a HIP number: "x"), each
a {key: profile} map in the same shape as star_profile.py output but without the spectrum (fetched on request).
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import star_ml as M
import star_profile as SP

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"
OUT = DATA / "stars" / "profile_bulk"
CACHE = ROOT / "data" / "cache" / "stars" / "_bulk"
HYP = "https://hypatiacatalog.com/hypatia/api/v2"


def get_json(url, name, timeout=180):
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    for k in range(8):                                    # patient: a dropped connection or DNS hiccup should not end the run
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WANDERERS/1.0"}), timeout=timeout).read())
            break
        except Exception as e:
            if k == 7:
                raise
            time.sleep(min(120, 10 * 2 ** k))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d))
    return d


def shard_of(key):
    return str(int(key[3:]) % 100) if key.startswith("hip") and key[3:].isdigit() else "x"


def hypatia_stars(hips, log):
    """hip -> Hypatia star record (preferred name, Teff, logg, spectral type, planets)."""
    out = {}
    for i in range(0, len(hips), 100):
        batch = hips[i:i + 100]
        q = "&".join(f"HIP{h}" for h in batch)
        recs = get_json(f"{HYP}/star/?{q}", f"hyp-star-{batch[0]}-{len(batch)}")
        for r in recs if isinstance(recs, list) else []:
            if r.get("status") == "found" and r.get("requested_name", "").startswith("HIP"):
                out[int(r["requested_name"][3:])] = r
        if i % 2000 == 0:
            log(f"   Hypatia stars: {i + len(batch)}/{len(hips)} asked, {len(out)} found")
    return out


def hypatia_abundances(log):
    """Hypatia preferred name -> {element: [X/H]} for every element, from one bulk call per element."""
    ab = {}
    for el in SP.ELEMENTS:
        d = get_json(f"{HYP}/data/?" + urllib.parse.urlencode({"xaxis1": el, "yaxis1": "Fe", "solarnorm": "asplund09"}), f"hyp-data-{el}")
        for v in d.get("values", []):
            if v.get("xaxis") is not None:
                ab.setdefault(v["name"], {})[el] = round(float(v["xaxis"]), 3)
    log(f"   Hypatia abundances: {len(ab)} stars, {len(SP.ELEMENTS)} elements")
    return ab


def gaia_by_hip(hips, log):
    """hip -> Gaia DR3 astrophysical parameters (FLAME, GSP-Phot) and XP availability."""
    out = {}
    for i in range(0, len(hips), 1000):
        batch = hips[i:i + 1000]
        q = ("SELECT b.original_ext_source_id AS hip, s.source_id, s.has_xp_sampled, s.ra, s.dec, s.pmra, s.pmdec, s.pmra_error, "
             "s.pmdec_error, s.parallax, s.parallax_error, s.radial_velocity, s.radial_velocity_error, a.teff_gspphot, a.logg_gspphot, a.mh_gspphot, "
             "a.radius_flame, a.radius_gspphot, a.lum_flame, a.mass_flame, a.age_flame "
             "FROM gaiadr3.hipparcos2_best_neighbour b JOIN gaiadr3.gaia_source s ON s.source_id = b.source_id "
             "LEFT JOIN gaiadr3.astrophysical_parameters a ON a.source_id = b.source_id "
             f"WHERE b.original_ext_source_id IN ({','.join(map(str, batch))})")
        f = CACHE / f"gaia2-{batch[0]}-{len(batch)}.json"
        rows = None
        for k in range(6):
            if f.exists():
                rows = json.loads(f.read_text()); break
            try:
                rows = M.tap(q, timeout=300); break
            except Exception:
                if k == 5:
                    raise
                time.sleep(min(120, 10 * 2 ** k))
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(rows))
        for r in rows:
            num = lambda k: float(r[k]) if r.get(k) not in ("", None) else None
            out[int(r["hip"])] = {"source_id": r["source_id"], "has_xp": r.get("has_xp_sampled") == "true", "teff": num("teff_gspphot"),
                                  "logg": num("logg_gspphot"), "mh": num("mh_gspphot"), "radius": num("radius_flame") or num("radius_gspphot"),
                                  "lum": num("lum_flame"), "mass": num("mass_flame"), "age_gyr": num("age_flame"),
                                  # astrometry at epoch 2016.0, for the 1900-2100 and long-range paths of stars without a learnt path
                                  "astrometry": {k2: num(k2) for k2 in ("ra", "dec", "pmra", "pmdec", "pmra_error", "pmdec_error", "parallax",
                                                                        "parallax_error", "radial_velocity", "radial_velocity_error")}}
        log(f"   Gaia: {min(i + 1000, len(hips))}/{len(hips)} asked, {len(out)} matched")
    return out


def main():
    log = lambda s: print(s, flush=True)
    stars = M.load_index()
    info_all = json.loads((DATA / "starquake_stars.json").read_text())
    hips = sorted({s["hip"] for s in stars if s.get("hip")})
    log(f"== bulk profiles for {len(stars)} stars ({len(hips)} with HIP numbers)")
    hyp = hypatia_stars(hips, log)
    ab = hypatia_abundances(log)
    gaia = gaia_by_hip(hips, log)
    shards, n_meas = {}, 0
    for s in stars:
        h = s.get("hip")
        hs, g = hyp.get(h), gaia.get(h)
        abund = ab.get(hs["name"]) if hs else None
        hyp_rec = None
        if hs:
            hyp_rec = {"teff": hs.get("teff"), "logg": hs.get("logg"),
                       "abundances": {el: {"x_h": v} for el, v in (abund or {}).items()},
                       "planets": [{"name": p.get("name"), "mass_mjup": p.get("m_p"), "period_d": p.get("p"), "a_au": p.get("a"), "e": p.get("e")}
                                   for p in (hs.get("planets") or []) if p.get("name")]}
        props = SP.build(s, info_all.get(s["key"]), g, hyp_rec)
        if not props and not abund and not g:
            continue                                      # nothing measured: the page falls back to the catalogue estimate
        n_meas += 1
        rec = {"key": s["key"], "name": s["name"], "gaia_dr3": g["source_id"] if g else None, "properties": props, "gaia": g,
               "chemistry": {"abundances": hyp_rec["abundances"], "matched_as": hs["name"], "spec": hs.get("spec"), "disk": hs.get("disk"),
                             "source": "Hypatia Catalog (Hinkel et al. 2014), median of studies; solar scale Asplund et al. 2009"} if abund else None,
               "planets": hyp_rec["planets"] if hyp_rec else [], "spectrum": None, "bulk": True}
        shards.setdefault(shard_of(s["key"]), {})[s["key"]] = rec
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    for sh, recs in shards.items():
        (OUT / f"{sh}.json").write_text(json.dumps(recs, separators=(",", ":")))
    summary = {"stars": len(stars), "with_measurements": n_meas, "with_abundances": sum(1 for r in (x for d in shards.values() for x in d.values()) if r["chemistry"]),
               "with_gaia": sum(1 for r in (x for d in shards.values() for x in d.values()) if r["gaia"]),
               "with_planets": sum(1 for r in (x for d in shards.values() for x in d.values()) if r["planets"]), "computed": time.strftime("%Y-%m-%d")}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    log(f"   wrote {len(shards)} shards: {summary}")


if __name__ == "__main__":
    main()
