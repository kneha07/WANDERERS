"""Independent facts from Gaia DR3 for each target, used as extra evidence on the cards.

    python pipeline/gaia_facts.py            # all targets with a Gaia source

From gaiadr3.gaia_source: parallax (-> distance), G magnitude, BP-RP colour, the photometric
variability flag and the GSP-Phot temperature. From gaiadr3.vari_classifier_result: Gaia's own
variable-star class, based on ~34 months of Gaia photometry (independent of our SPHEREx snapshots).
Writes data/cache/<id>/gaia_facts.json; evidence.py adds it to the card.
"""
import json, sys
from pathlib import Path

import pyvo

sys.path.insert(0, str(Path(__file__).parent))
from fetch import CACHE, GAIA_TAP, num

CLASS_NAMES = {
    "LPV": "long-period variable (Mira-type pulsating giant)", "YSO": "young stellar object",
    "SOLAR_LIKE": "solar-like (spotted, active) star", "ECL": "eclipsing binary", "RS": "RS CVn active binary",
    "DSCT|GDOR|SXPHE": "delta Scuti / gamma Dor pulsator", "RR": "RR Lyrae pulsator", "CEP": "Cepheid",
}


def facts_for(source_id):
    tap = pyvo.dal.TAPService(GAIA_TAP)
    g = tap.run_sync(f"SELECT parallax, parallax_error, phot_g_mean_mag, bp_rp, phot_variable_flag, teff_gspphot "
                     f"FROM gaiadr3.gaia_source WHERE source_id={source_id}").to_table()
    out = {"source_id": int(source_id)}
    if len(g):
        r = g[0]
        plx = num(r["parallax"], None)
        out.update({
            "parallax_mas": plx, "distance_ly": (3261.56 / plx) if plx and plx > 0 else None,
            "g_mag": num(r["phot_g_mean_mag"], None), "bp_rp": num(r["bp_rp"], None),
            "variable_flag": str(r["phot_variable_flag"]).strip() if r["phot_variable_flag"] is not None else None,
            "teff_k": num(r["teff_gspphot"], None),
        })
    v = tap.run_sync(f"SELECT best_class_name, best_class_score FROM gaiadr3.vari_classifier_result "
                     f"WHERE source_id={source_id}").to_table()
    if len(v):
        cls = str(v[0]["best_class_name"]).strip()
        out["vari_class"] = cls
        out["vari_class_text"] = CLASS_NAMES.get(cls, cls)
        out["vari_score"] = num(v[0]["best_class_score"], None)
    return out


def main(ids):
    for d in sorted(CACHE.glob("*/gaia.json")):
        tid = d.parent.name
        if ids and tid not in ids:
            continue
        ref = json.loads(d.read_text())["ref"]
        if ref.get("source_id") is None:
            # not in Gaia: keep the literature distance if we have one
            plx = ref.get("parallax")
            f = {"source_id": None, "parallax_mas": plx, "distance_ly": (3261.56 / plx) if plx else None,
                 "note": f"Not in Gaia DR3; parallax from {ref.get('source')}"}
        else:
            try:
                f = facts_for(ref["source_id"])
            except Exception as e:
                print(f"!! {tid}: {e}"); continue
        (d.parent / "gaia_facts.json").write_text(json.dumps(f, indent=1))
        dist = f"{f['distance_ly']:.1f} ly" if f.get("distance_ly") else "?"
        print(f"{tid:<12} distance {dist:<10} teff {f.get('teff_k')}  variable flag {f.get('variable_flag')}  "
              f"Gaia class {f.get('vari_class')}")


if __name__ == "__main__":
    main(sys.argv[1:])
