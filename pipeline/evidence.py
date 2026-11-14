"""Rule-based evidence card for each analysed target, plus app/data/index.json.

    python pipeline/evidence.py

Every check is a plain measurement compared with a stated threshold. "Confidence" is simply how
many independent checks agree (high: 3+, medium: 2, low: 0-1). No machine-learning score and no
invented percentages, so every line on the card can be traced back to data.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"
TEASER = {
    "barnard": "Fastest star in the sky",
    "eps_indi_b": "Brown dwarf pair",
    "wise0855": "Coldest brown dwarf (boss level)",
    "rw_aur": "Young star that flickers",
    "r_dra": "Pulsating red giant",
}
ORDER = ["barnard", "r_dra", "rw_aur", "eps_indi_b", "wise0855"]


def card(t):
    checks, numbers = [], []
    m, v, col = t.get("motion"), t.get("variability"), t.get("ir_color") or {}
    moved = matches = red = varies = False

    if m:
        moved = m["shift_spherex_pixels"] >= 2 and m["measured_arcsec_per_yr"] >= 0.3
        checks.append({"state": "ok" if moved else "no",
                       "text": (f"Moved {m['shift_arcsec']:.0f}″ between {m['from_year']:.0f} and {m['to_year']:.0f} "
                                f"({m['shift_spherex_pixels']:.1f} SPHEREx pixels)") if moved else
                               f"No measurable motion between {m['from_year']:.0f} and {m['to_year']:.0f}"})
        numbers.append({"label": "measured motion", "value": f"{m['measured_arcsec_per_yr']:.2f}″/yr"})
        if m["expected_arcsec_per_yr"] > 0:
            numbers.append({"label": f"catalogue motion ({t['reference']['source'].split(',')[0]})",
                            "value": f"{m['expected_arcsec_per_yr']:.2f}″/yr"})
            rel = abs(m["measured_arcsec_per_yr"] - m["expected_arcsec_per_yr"]) / max(m["expected_arcsec_per_yr"], 0.3)
            matches = rel < 0.25
            if moved:
                pct = f"{rel*100:.1f}%" if rel >= 0.001 else "under 0.1%"
                checks.append({"state": "ok" if matches else "warn",
                               "text": (f"Measured speed matches the catalogue: {m['measured_arcsec_per_yr']:.2f} vs "
                                        f"{m['expected_arcsec_per_yr']:.2f}″/yr (difference {pct})") if matches else
                                       f"Measured speed differs from the catalogue by {pct}; check the images"})

    if t["target_in_gaia"]:
        checks.append({"state": "ok", "text": f"Gaia DR3 has this object (source {t['reference']['source_id']})"})
    else:
        checks.append({"state": "warn", "text": "No Gaia DR3 counterpart: too faint or too cold for Gaia's visible-light camera. "
                                                f"Catalogued in the literature ({t['reference']['source']})."})

    if col.get("ratio"):
        r = col["ratio"]
        lim = col.get("lower_limit")
        red = r >= 2
        checks.append({"state": "ok" if red else "no",
                       "text": ((f"Bright at 4–4.75 µm but not detected in the 3.3 µm methane band: at least {r:.0f}× brighter, "
                                 "a deep methane dip of a very cold brown dwarf (a normal star would be below 1×)") if lim else
                                (f"{r:.1f}× brighter at 4–4.75 µm than in the 3.3 µm methane band: the methane dip of a cold brown dwarf "
                                "(a normal star would be below 1×)")) if red else
                               f"4–4.75 µm / 3.3 µm ratio {r:.1f}: no strong methane dip (a normal star is below 1)"})
        numbers.append({"label": "methane test (4–4.75 / 3.3 µm)", "value": (f"> {r:.0f}×" if lim else f"{r:.1f}×")})

    if v:
        sig = abs(v["delta_mag"]) > max(0.1, 3 * v["uncertainty_mag"])
        varies = sig
        checks.append({"state": "ok" if sig else "no",
                       "text": (f"{'Faded' if v['delta_mag'] > 0 else 'Brightened'} by {abs(v['delta_mag']):.2f} ± {v['uncertainty_mag']:.2f} mag "
                                f"between {v['from']} and {v['to']}"
                                + (" (measured in the wings of its image, because its core saturates SPHEREx)"
                                   if v.get("method", "").startswith("PSF-wing") else "")
                                if sig else f"Steady brightness between {v['from']} and {v['to']} "
                                            f"({v['delta_mag']:+.2f} ± {v['uncertainty_mag']:.2f} mag)")})
        numbers.append({"label": f"brightness change {v['from']}→{v['to']}", "value": f"{v['delta_mag']:+.2f} mag"})

    if t["spectrum_points"] and t["flagged_points"] > 0.5 * t["spectrum_points"]:
        left = t["spectrum_points"] - t["flagged_points"]
        checks.append({"state": "warn", "text": f"{t['flagged_points']} of {t['spectrum_points']} SPHEREx measurements flagged "
                       "(overflow or bloom: the object is too bright for SPHEREx). " +
                       (f"The spectrum uses the {left} clean ones." if left >= 10 else
                        "No reliable SPHEREx spectrum, so we do not show one.")})

    # Classification from the checks above, most specific first.
    if red and moved:
        cls, support = "Cold brown dwarf (methane-rich)", [moved, red, matches or not t["target_in_gaia"]]
    elif varies:
        cls, support = "Variable star", [varies, t["target_in_gaia"], not moved]
    elif moved and t["target_in_gaia"]:
        cls, support = "Nearby star with fast proper motion", [moved, matches, t["target_in_gaia"]]
    elif moved:
        cls, support = "Unexplained mover", [moved]
    else:
        cls, support = "Steady star (no change in these snapshots)", [t["target_in_gaia"], not moved]
    n = sum(bool(s) for s in support)
    # Known = the object is in Gaia or in a published catalogue we resolved it from. A position
    # typed in by a user with nothing catalogued there would be a candidate.
    known = t["target_in_gaia"] or bool(t["reference"].get("catalogued", True))
    # Confidence: high when every key check passes (and there are at least two), medium when two
    # pass, low otherwise. One step down, with the reason shown, when most SPHEREx data is saturated
    # and the class depends on SPHEREx photometry rather than on motion.
    level = 2 if (n == len(support) and n >= 2) or n >= 3 else 1 if n == 2 else 0
    caveat = None
    saturated = t["spectrum_points"] and t["flagged_points"] > 0.8 * t["spectrum_points"]
    if saturated and cls in ("Variable star", "Steady star (no change in these snapshots)") and level > 0:
        level -= 1
        caveat = "lowered because most SPHEREx measurements are saturated"
    return {"status": "known" if known else "candidate", "classification": cls,
            "confidence": ["low", "medium", "high"][level], "confidence_note": caveat,
            "checks_passed": n, "checks_needed": len(support), "checks": checks, "numbers": numbers}


def main():
    index = []
    for d in sorted(DATA.glob("*/target.json")):
        t = json.loads(d.read_text())
        t["evidence"] = card(t)
        d.write_text(json.dumps(t, indent=1))
        ref = t["reference"]
        index.append({"id": t["id"], "name": t["name"], "teaser": TEASER.get(t["id"], t["kind"]),
                      "ra": t["grid"]["centre_ra"], "dec": t["grid"]["centre_dec"]})
        print(f"{t['name']:<18} {t['evidence']['status']:<9} {t['evidence']['classification']:<38} "
              f"confidence {t['evidence']['confidence']}")
    index.sort(key=lambda x: ORDER.index(x["id"]) if x["id"] in ORDER else 99)
    (DATA / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
