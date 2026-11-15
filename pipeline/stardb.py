"""Build the searchable star database for the page from the HYG catalogue.

    python pipeline/stardb.py            # download HYG v4.1 (once, cached) and write app/data/stars/index.json

Source: HYG Database v4.1 (Hipparcos + Yale Bright Star + Gliese), D. Nash / astronexus,
https://github.com/astronexus/HYG-Database, licence CC BY-SA 4.0. The raw CSV (34 MB) is cached in
data/cache/stars/ and not committed. The index keeps every star a person is likely to search for:
anything with a proper name, a Bayer/Flamsteed designation or a Gliese number, plus every star
brighter than magnitude 6.5 (naked eye). The WANDERERS targets that HYG lacks (Epsilon Indi B,
WISE 0855) are added from pipeline/targets.py / app/data so they can be searched too.

Catalogue values here are for display and as a starting guess only. HYG copies Hipparcos values
(and caps some: Barnard's Star pmDec reads 9999.99 instead of ~10362 mas/yr); the trajectory is
learnt from measured positions by pipeline/star_ml.py, not taken from these numbers.
"""
import csv, json, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "stars"
OUT = ROOT / "app" / "data" / "stars"
HYG_URL = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"
HYG_CSV = CACHE / "hygdata_v41.csv"
NAKED_EYE = 6.5

GREEK = {"Alp": "Alpha", "Bet": "Beta", "Gam": "Gamma", "Del": "Delta", "Eps": "Epsilon", "Zet": "Zeta",
         "Eta": "Eta", "The": "Theta", "Iot": "Iota", "Kap": "Kappa", "Lam": "Lambda", "Mu": "Mu", "Nu": "Nu",
         "Xi": "Xi", "Omi": "Omicron", "Pi": "Pi", "Rho": "Rho", "Sig": "Sigma", "Tau": "Tau", "Ups": "Upsilon",
         "Phi": "Phi", "Chi": "Chi", "Psi": "Psi", "Ome": "Omega"}
# IAU constellation abbreviation -> (name, genitive)
CON = {
    "And": ("Andromeda", "Andromedae"), "Ant": ("Antlia", "Antliae"), "Aps": ("Apus", "Apodis"),
    "Aqr": ("Aquarius", "Aquarii"), "Aql": ("Aquila", "Aquilae"), "Ara": ("Ara", "Arae"), "Ari": ("Aries", "Arietis"),
    "Aur": ("Auriga", "Aurigae"), "Boo": ("Bootes", "Bootis"), "Cae": ("Caelum", "Caeli"),
    "Cam": ("Camelopardalis", "Camelopardalis"), "Cnc": ("Cancer", "Cancri"), "CVn": ("Canes Venatici", "Canum Venaticorum"),
    "CMa": ("Canis Major", "Canis Majoris"), "CMi": ("Canis Minor", "Canis Minoris"), "Cap": ("Capricornus", "Capricorni"),
    "Car": ("Carina", "Carinae"), "Cas": ("Cassiopeia", "Cassiopeiae"), "Cen": ("Centaurus", "Centauri"),
    "Cep": ("Cepheus", "Cephei"), "Cet": ("Cetus", "Ceti"), "Cha": ("Chamaeleon", "Chamaeleontis"),
    "Cir": ("Circinus", "Circini"), "Col": ("Columba", "Columbae"), "Com": ("Coma Berenices", "Comae Berenices"),
    "CrA": ("Corona Australis", "Coronae Australis"), "CrB": ("Corona Borealis", "Coronae Borealis"),
    "Crv": ("Corvus", "Corvi"), "Crt": ("Crater", "Crateris"), "Cru": ("Crux", "Crucis"), "Cyg": ("Cygnus", "Cygni"),
    "Del": ("Delphinus", "Delphini"), "Dor": ("Dorado", "Doradus"), "Dra": ("Draco", "Draconis"),
    "Equ": ("Equuleus", "Equulei"), "Eri": ("Eridanus", "Eridani"), "For": ("Fornax", "Fornacis"),
    "Gem": ("Gemini", "Geminorum"), "Gru": ("Grus", "Gruis"), "Her": ("Hercules", "Herculis"),
    "Hor": ("Horologium", "Horologii"), "Hya": ("Hydra", "Hydrae"), "Hyi": ("Hydrus", "Hydri"), "Ind": ("Indus", "Indi"),
    "Lac": ("Lacerta", "Lacertae"), "Leo": ("Leo", "Leonis"), "LMi": ("Leo Minor", "Leonis Minoris"),
    "Lep": ("Lepus", "Leporis"), "Lib": ("Libra", "Librae"), "Lup": ("Lupus", "Lupi"), "Lyn": ("Lynx", "Lyncis"),
    "Lyr": ("Lyra", "Lyrae"), "Men": ("Mensa", "Mensae"), "Mic": ("Microscopium", "Microscopii"),
    "Mon": ("Monoceros", "Monocerotis"), "Mus": ("Musca", "Muscae"), "Nor": ("Norma", "Normae"),
    "Oct": ("Octans", "Octantis"), "Oph": ("Ophiuchus", "Ophiuchi"), "Ori": ("Orion", "Orionis"), "Pav": ("Pavo", "Pavonis"),
    "Peg": ("Pegasus", "Pegasi"), "Per": ("Perseus", "Persei"), "Phe": ("Phoenix", "Phoenicis"), "Pic": ("Pictor", "Pictoris"),
    "Psc": ("Pisces", "Piscium"), "PsA": ("Piscis Austrinus", "Piscis Austrini"), "Pup": ("Puppis", "Puppis"),
    "Pyx": ("Pyxis", "Pyxidis"), "Ret": ("Reticulum", "Reticuli"), "Sge": ("Sagitta", "Sagittae"),
    "Sgr": ("Sagittarius", "Sagittarii"), "Sco": ("Scorpius", "Scorpii"), "Scl": ("Sculptor", "Sculptoris"),
    "Sct": ("Scutum", "Scuti"), "Ser": ("Serpens", "Serpentis"), "Sex": ("Sextans", "Sextantis"), "Tau": ("Taurus", "Tauri"),
    "Tel": ("Telescopium", "Telescopii"), "Tri": ("Triangulum", "Trianguli"), "TrA": ("Triangulum Australe", "Trianguli Australis"),
    "Tuc": ("Tucana", "Tucanae"), "UMa": ("Ursa Major", "Ursae Majoris"), "UMi": ("Ursa Minor", "Ursae Minoris"),
    "Vel": ("Vela", "Velorum"), "Vir": ("Virgo", "Virginis"), "Vol": ("Volans", "Volantis"), "Vul": ("Vulpecula", "Vulpeculae"),
}


def download():
    if not HYG_CSV.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {HYG_URL}", flush=True)
        tmp = HYG_CSV.with_suffix(".part")
        tmp.write_bytes(urllib.request.urlopen(HYG_URL, timeout=300).read())
        tmp.rename(HYG_CSV)
    return HYG_CSV


def bayer_names(r):
    """'9Alp CMa' -> ['Alpha Canis Majoris', 'Alp CMa', '9 CMa', '9 Canis Majoris'] (whatever applies)."""
    out, con = [], r["con"]
    cname = CON.get(con, (con, con))[1]
    if r["bayer"]:
        letter = r["bayer"].split("-")[0]                      # 'Alp-1' -> 'Alp'
        sup = r["bayer"].split("-")[1] if "-" in r["bayer"] else ""
        full = GREEK.get(letter, letter) + (sup and f"{sup}")
        out += [f"{full} {cname}", f"{letter}{sup} {con}"]
    if r["flam"]:
        out += [f"{r['flam']} {cname}", f"{r['flam']} {con}"]
    return out


def name_of(r):
    if r["proper"]:
        return r["proper"]
    b = bayer_names(r)
    if b:
        return b[0]
    for k, p in (("gl", ""), ("hip", "HIP "), ("hd", "HD "), ("hr", "HR ")):
        if r[k]:
            return p + r[k]
    return f"HYG {r['id']}"


def key_of(r):
    return f"hip{r['hip']}" if r["hip"] else f"hyg{r['id']}"


def num(v, nd=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if nd is not None else x


def entry(r):
    aliases = [r["proper"], *bayer_names(r), r["gl"], r["bf"]]
    aliases += [f"HIP {r['hip']}" if r["hip"] else "", f"HD {r['hd']}" if r["hd"] else "", f"HR {r['hr']}" if r["hr"] else ""]
    dist = num(r["dist"])
    return {
        "key": key_of(r), "name": name_of(r),
        "aliases": sorted({a for a in aliases if a and a != name_of(r)}),
        "ra": round(num(r["ra"]) * 15, 6) if num(r["ra"]) is not None else None,   # HYG RA is in hours
        "dec": num(r["dec"], 6), "mag": num(r["mag"], 2),
        "dist_pc": dist if dist and dist < 100000 else None,           # 100000 = unknown in HYG
        "pmra": num(r["pmra"], 2), "pmdec": num(r["pmdec"], 2), "rv": num(r["rv"], 1),
        "ci": num(r["ci"], 3),                                        # B-V colour: temperature for the starquake model
        "spect": r["spect"] or None, "con": CON.get(r["con"], (r["con"], ""))[0] if r["con"] else None,
        "hip": int(r["hip"]) if r["hip"] else None,
    }


def wanderers_targets(stars):
    """Link the repo's targets to their HYG row (nearest within 60" at epoch 2000), or add them if HYG
    lacks them (Epsilon Indi B, WISE 0855), using the reference in their analysed target.json."""
    import numpy as np
    sys.path.insert(0, str(ROOT / "pipeline"))
    from targets import TARGETS
    ra = np.array([s["ra"] for s in stars]); dec = np.array([s["dec"] for s in stars])
    extras = []
    for tid, t in TARGETS.items():
        f = ROOT / "app" / "data" / tid / "target.json"
        if not f.exists():
            continue
        ref = json.loads(f.read_text())["reference"]
        dt = 2000.0 - ref["epoch"]                        # move the reference to HYG's epoch 2000
        d0 = ref["dec"] + (ref["pmdec"] or 0) * dt / 3.6e6
        r0 = ref["ra"] + (ref["pmra"] or 0) * dt / 3.6e6 / np.cos(np.radians(d0))
        sep = np.hypot((ra - r0) * np.cos(np.radians(d0)), dec - d0) * 3600
        i = int(np.argmin(sep))
        if sep[i] < 60:
            stars[i]["wanderers"] = tid
            if tid not in stars[i]["aliases"]:
                stars[i]["aliases"].append(tid)
            continue
        extras.append({"key": f"wanderers_{tid}", "name": t["name"], "aliases": [tid, "WANDERERS target"],
                       "ra": round(ref["ra"], 7), "dec": round(ref["dec"], 7), "mag": None,
                       "dist_pc": round(1000 / ref["parallax"], 3) if ref.get("parallax") else None,
                       "pmra": round(ref["pmra"], 2), "pmdec": round(ref["pmdec"], 2), "rv": None, "spect": None,
                       "con": None, "hip": None, "epoch": ref["epoch"], "gaia_dr3": ref.get("source_id"),
                       "wanderers": tid, "source": ref.get("source", "WANDERERS")})
    return stars + extras


def build():
    rows = list(csv.DictReader(open(download(), newline="", encoding="utf-8")))
    keep = [r for r in rows if r["id"] != "0" and (r["proper"] or r["bf"] or r["gl"] or (num(r["mag"]) or 99) <= NAKED_EYE)]
    stars = [entry(r) for r in keep]
    stars = wanderers_targets(stars)
    stars.sort(key=lambda s: (s["mag"] is None, s["mag"] if s["mag"] is not None else 99))
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"source": "HYG Database v4.1 (astronexus), CC BY-SA 4.0, plus WANDERERS targets",
            "url": "https://github.com/astronexus/HYG-Database", "n_hyg_total": len(rows) - 1,
            "selection": f"proper name, Bayer/Flamsteed or Gliese designation, or brighter than V={NAKED_EYE}",
            "fields": "ra/dec degrees (J2000, epoch 2000), mag V, dist_pc, pm mas/yr, rv km/s"}
    (OUT / "index.json").write_text(json.dumps({"meta": meta, "stars": stars}, separators=(",", ":"), ensure_ascii=False))
    print(f"star database: {len(stars)} searchable stars of {len(rows) - 1} in HYG -> {(OUT / 'index.json').relative_to(ROOT)}"
          f" ({(OUT / 'index.json').stat().st_size / 1e6:.1f} MB)", flush=True)
    return stars


if __name__ == "__main__":
    build()
