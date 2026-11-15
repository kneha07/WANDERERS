"""Searchable star list for WANDERERS (console search + Sky Compass).

    python pipeline/make_stars.py path/to/hygdata_v40.csv.gz

Source: HYG database v4.0 (astronexus, CC BY-SA 4.0), which combines Hipparcos, Yale Bright Star and Gliese.
Kept: every star with magnitude <= 6.5 (naked eye), every star with an IAU proper name, and every star
within 10 parsecs. Plus the WANDERERS prepared targets (WISE 0855 is not in HYG: too cold and faint).
Output app/data/stars.json: [name, other names, ra deg, dec deg, mag, spectral type, distance ly, constellation, flags]
Derived data stays under CC BY-SA 4.0.
"""
import csv, gzip, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GREEK = {"Alp": "Alpha", "Bet": "Beta", "Gam": "Gamma", "Del": "Delta", "Eps": "Epsilon", "Zet": "Zeta", "Eta": "Eta",
         "The": "Theta", "Iot": "Iota", "Kap": "Kappa", "Lam": "Lambda", "Mu": "Mu", "Nu": "Nu", "Xi": "Xi", "Omi": "Omicron",
         "Pi": "Pi", "Rho": "Rho", "Sig": "Sigma", "Tau": "Tau", "Ups": "Upsilon", "Phi": "Phi", "Chi": "Chi", "Psi": "Psi", "Ome": "Omega"}
# constellation abbreviation -> (name, genitive)
CON = {
 "And": ("Andromeda", "Andromedae"), "Ant": ("Antlia", "Antliae"), "Aps": ("Apus", "Apodis"), "Aqr": ("Aquarius", "Aquarii"),
 "Aql": ("Aquila", "Aquilae"), "Ara": ("Ara", "Arae"), "Ari": ("Aries", "Arietis"), "Aur": ("Auriga", "Aurigae"),
 "Boo": ("Boötes", "Boötis"), "Cae": ("Caelum", "Caeli"), "Cam": ("Camelopardalis", "Camelopardalis"), "Cnc": ("Cancer", "Cancri"),
 "CVn": ("Canes Venatici", "Canum Venaticorum"), "CMa": ("Canis Major", "Canis Majoris"), "CMi": ("Canis Minor", "Canis Minoris"),
 "Cap": ("Capricornus", "Capricorni"), "Car": ("Carina", "Carinae"), "Cas": ("Cassiopeia", "Cassiopeiae"), "Cen": ("Centaurus", "Centauri"),
 "Cep": ("Cepheus", "Cephei"), "Cet": ("Cetus", "Ceti"), "Cha": ("Chamaeleon", "Chamaeleontis"), "Cir": ("Circinus", "Circini"),
 "Col": ("Columba", "Columbae"), "Com": ("Coma Berenices", "Comae Berenices"), "CrA": ("Corona Australis", "Coronae Australis"),
 "CrB": ("Corona Borealis", "Coronae Borealis"), "Crv": ("Corvus", "Corvi"), "Crt": ("Crater", "Crateris"), "Cru": ("Crux", "Crucis"),
 "Cyg": ("Cygnus", "Cygni"), "Del": ("Delphinus", "Delphini"), "Dor": ("Dorado", "Doradus"), "Dra": ("Draco", "Draconis"),
 "Equ": ("Equuleus", "Equulei"), "Eri": ("Eridanus", "Eridani"), "For": ("Fornax", "Fornacis"), "Gem": ("Gemini", "Geminorum"),
 "Gru": ("Grus", "Gruis"), "Her": ("Hercules", "Herculis"), "Hor": ("Horologium", "Horologii"), "Hya": ("Hydra", "Hydrae"),
 "Hyi": ("Hydrus", "Hydri"), "Ind": ("Indus", "Indi"), "Lac": ("Lacerta", "Lacertae"), "Leo": ("Leo", "Leonis"),
 "LMi": ("Leo Minor", "Leonis Minoris"), "Lep": ("Lepus", "Leporis"), "Lib": ("Libra", "Librae"), "Lup": ("Lupus", "Lupi"),
 "Lyn": ("Lynx", "Lyncis"), "Lyr": ("Lyra", "Lyrae"), "Men": ("Mensa", "Mensae"), "Mic": ("Microscopium", "Microscopii"),
 "Mon": ("Monoceros", "Monocerotis"), "Mus": ("Musca", "Muscae"), "Nor": ("Norma", "Normae"), "Oct": ("Octans", "Octantis"),
 "Oph": ("Ophiuchus", "Ophiuchi"), "Ori": ("Orion", "Orionis"), "Pav": ("Pavo", "Pavonis"), "Peg": ("Pegasus", "Pegasi"),
 "Per": ("Perseus", "Persei"), "Phe": ("Phoenix", "Phoenicis"), "Pic": ("Pictor", "Pictoris"), "Psc": ("Pisces", "Piscium"),
 "PsA": ("Piscis Austrinus", "Piscis Austrini"), "Pup": ("Puppis", "Puppis"), "Pyx": ("Pyxis", "Pyxidis"), "Ret": ("Reticulum", "Reticuli"),
 "Sge": ("Sagitta", "Sagittae"), "Sgr": ("Sagittarius", "Sagittarii"), "Sco": ("Scorpius", "Scorpii"), "Scl": ("Sculptor", "Sculptoris"),
 "Sct": ("Scutum", "Scuti"), "Ser": ("Serpens", "Serpentis"), "Sex": ("Sextans", "Sextantis"), "Tau": ("Taurus", "Tauri"),
 "Tel": ("Telescopium", "Telescopii"), "Tri": ("Triangulum", "Trianguli"), "TrA": ("Triangulum Australe", "Trianguli Australis"),
 "Tuc": ("Tucana", "Tucanae"), "UMa": ("Ursa Major", "Ursae Majoris"), "UMi": ("Ursa Minor", "Ursae Minoris"), "Vel": ("Vela", "Velorum"),
 "Vir": ("Virgo", "Virginis"), "Vol": ("Volans", "Volantis"), "Vul": ("Vulpecula", "Vulpeculae"),
}
LY_PER_PC = 3.26156


def main(path):
    out, seen = [], set()
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            if r["proper"] == "Sol":
                continue
            mag = float(r["mag"]) if r["mag"] else 99
            dist = float(r["dist"]) if r["dist"] else 0
            near = 0 < dist <= 10
            if not (mag <= 6.5 or r["proper"] or near):
                continue
            con = r["con"]
            names = []
            if r["proper"]:
                names.append(r["proper"])
            if r["bayer"] and con in CON:
                g = r["bayer"].split("-")
                gr = GREEK.get(g[0])
                if gr:
                    names.append(f"{gr}{(' ' + g[1]) if len(g) > 1 else ''} {CON[con][1]}")
            if r["flam"] and con in CON:
                names.append(f"{r['flam']} {CON[con][1]}")
            if r["gl"]:
                names.append(r["gl"].replace("Gl ", "Gliese ").strip())
            if r["hd"]:
                names.append(f"HD {r['hd']}")
            if r["hip"]:
                names.append(f"HIP {r['hip']}")
            if not names:
                continue
            key = names[0]
            if key in seen:
                continue
            seen.add(key)
            flags = ("V" if r["var"] else "") + ("N" if near else "")
            out.append([names[0], "|".join(names[1:]), round(float(r["ra"]) * 15, 5), round(float(r["dec"]), 5),
                        round(mag, 2), r["spect"], round(dist * LY_PER_PC, 2) if 0 < dist < 100000 else None,
                        CON.get(con, ("", ""))[0], flags])
    # WANDERERS prepared targets: link them to the full analysis (id in the flags column)
    idx = json.loads((ROOT / "app" / "data" / "index.json").read_text())
    for t in idx:
        hit = next((s for s in out if t["name"].split(" ")[0].lower() in (s[0] + "|" + s[1]).lower() and
                    abs(s[2] - t["ra"]) < 0.1 and abs(s[3] - t["dec"]) < 0.1), None)
        if hit:
            hit[8] += f"W:{t['id']}"
            if t["name"] not in hit[0] and t["name"] not in hit[1]:
                hit[1] = t["name"] + "|" + hit[1]
        else:
            out.append([t["name"], "", round(t["ra"], 5), round(t["dec"], 5), None, "", None, "", f"W:{t['id']}"])
    out.sort(key=lambda s: (s[4] if s[4] is not None else 50))
    (ROOT / "app" / "data" / "stars.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    named = sum(1 for s in out if s[0] and not s[0].startswith(("HD ", "HIP ")))
    print(f"stars: {len(out)} ({named} with a common name); WANDERERS targets linked: "
          f"{sum(1 for s in out if 'W:' in s[8])}")


if __name__ == "__main__":
    main(sys.argv[1])
