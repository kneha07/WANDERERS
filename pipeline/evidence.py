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
CACHE = ROOT / "data" / "cache"
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
        # Below the detection limit the centroid shift is mostly noise (R Draconis: saturated core), so say so.
        numbers.append({"label": "measured motion" if moved else "apparent drift (below the detection limit, not a real motion)",
                        "value": f"{m['measured_arcsec_per_yr']:.2f}″/yr"})
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

    if t["target_in_gaia"] and t["reference"].get("match_arcsec", 0) > 2:
        checks.append({"state": "warn", "text": f"Nearest Gaia DR3 star is {t['reference']['match_arcsec']:.1f}″ from the typed "
                       "position, so it may not be the object you meant. Very cold or fast objects (like WISE 0855 and "
                       "Luhman 16) are often missing from Gaia."})
    elif t["target_in_gaia"]:
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

    # Independent facts from Gaia DR3 (pipeline/gaia_facts.py), when available.
    gf = t.get("gaia_facts") or {}
    gaia_var = bool(gf.get("vari_class")) or gf.get("variable_flag") == "VARIABLE"
    if gf.get("distance_ly"):
        numbers.append({"label": "distance (" + ("Gaia parallax" if gf.get("source_id") else "literature") + ")",
                        "value": f"{gf['distance_ly']:,.1f} ly" if gf["distance_ly"] < 100 else f"{gf['distance_ly']:,.0f} ly"})
    if gf.get("teff_k"):
        numbers.append({"label": "temperature (Gaia estimate)", "value": f"{gf['teff_k']:,.0f} K"})
    if gaia_var:
        cls_txt = gf.get("vari_class_text") or "variable"
        agree = "agrees with" if varies else "while"
        checks.append({"state": "ok" if varies else "warn",
                       "text": f"Gaia independently classifies it as a {cls_txt} from about 3 years of its own photometry"
                               + ("; this agrees with our SPHEREx measurement" if varies else
                                  "; our two SPHEREx snapshots just did not catch a change")})

    # Classification from the checks above, most specific first.
    if red and moved:
        cls, support = "Cold brown dwarf (methane-rich)", [moved, red, matches or not t["target_in_gaia"]]
    elif varies:
        cls, support = "Variable star", [varies, gaia_var or t["target_in_gaia"], not moved]
    elif moved and t["target_in_gaia"]:
        cls, support = "Nearby star with fast proper motion", [moved, matches, t["target_in_gaia"]]
    elif moved:
        cls, support = "Unexplained mover", [moved]
    elif "variability" in (t.get("story") or ""):
        # Listed as a variable star in pipeline/targets.py: calling it "steady" would be wrong, we only missed the change.
        cls, support = "Known variable star, quiet in these snapshots", [t["target_in_gaia"], not moved]
        checks.append({"state": "warn", "text": "Catalogued as a variable star, but these SPHEREx visits show no change larger "
                       "than the measurement uncertainty. A few snapshots can miss a change that happens between them."})
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
    confirmed = cls == "Variable star" and gaia_var        # an independent survey agrees: no penalty
    if saturated and cls in ("Variable star", "Steady star (no change in these snapshots)",
                             "Known variable star, quiet in these snapshots") and level > 0 and not confirmed:
        level -= 1
        caveat = "lowered because most SPHEREx measurements are saturated"
    return {"status": "known" if known else "candidate", "classification": cls,
            "confidence": ["low", "medium", "high"][level], "confidence_note": caveat,
            "checks_passed": n, "checks_needed": len(support), "checks": checks, "numbers": numbers}


SPHEREX_PIXEL = 6.15      # arcsec
MOON = 1800.0             # arcsec, width of the full Moon
SUN_TEFF = 5772.0         # K
EARTH_ORBIT_KMS = 29.8


def _round2(x):
    """Two significant figures for far distances, where the parallax is not better than that."""
    if x < 100:
        return f"{x:.1f}"
    p = 10 ** (len(str(int(x))) - 2)
    return f"{round(x / p) * p:,.0f}"


def insights(t):
    """What the measurements mean, and what this view cannot show. Every fact is derived from numbers
    already on the card with a stated formula ("basis"); nothing is looked up or guessed here."""
    facts, limits = [], []
    m, v, col = t.get("motion"), t.get("variability"), t.get("ir_color") or {}
    ref, gf = t.get("reference") or {}, t.get("gaia_facts") or {}
    mu = m["measured_arcsec_per_yr"] if m else 0
    moved = bool(m) and m["shift_spherex_pixels"] >= 2 and mu >= 0.3
    plx = ref.get("parallax") or gf.get("parallax_mas")
    dist = gf.get("distance_ly") or (3261.56 / plx if plx and plx > 0 else None)

    if moved and plx and plx > 0:
        kms = 4.74 * mu / (plx / 1000)
        facts.append({"id": "speed", "headline": f"About {kms:.0f} km/s across the sky",
                      "detail": f"That is {kms / EARTH_ORBIT_KMS:.1f} times the speed of Earth around the Sun. It is sideways speed only: "
                                "motion toward or away from us does not show in images.",
                      "basis": f"4.74 × {mu:.2f}″/yr ÷ parallax {plx / 1000:.3f}″"})
    if moved:
        yrs = MOON / mu
        facts.append({"id": "moon", "headline": f"Crosses the width of the full Moon in about {round(yrs, -1):,.0f} years",
                      "detail": "A typical star in these images needs more than 100,000 years, which is why this one stands out in a flipbook.",
                      "basis": f"1,800″ ÷ {mu:.2f}″/yr"})
    if dist:
        near = dist < 20
        facts.append({"id": "distance",
                      "headline": f"{'About ' if dist >= 100 else ''}{_round2(dist)} light-years away" + (": one of the Sun's nearest neighbours" if near else ""),
                      "detail": f"The light in these images left it about {_round2(dist)} years ago."
                                + (" A distance this large is uncertain." if dist >= 1000 else ""),
                      "basis": "3.26 ÷ parallax (″), " + ("Gaia DR3" if gf.get("source_id") else ref.get("source", "literature"))})
    if gf.get("teff_k"):
        facts.append({"id": "temperature", "headline": f"About {round(gf['teff_k'], -2):,.0f} K at its surface",
                      "detail": f"That is {gf['teff_k'] / SUN_TEFF * 100:.0f}% of the Sun's surface temperature (5,772 K), so it glows mostly in infrared light.",
                      "basis": "Gaia DR3 estimate from its colours"})
    if (col.get("ratio") or 0) >= 2:
        facts.append({"id": "methane", "headline": "Cold enough to hold methane gas",
                      "detail": "Methane survives only in atmospheres below roughly 1,300 K, cooler than any true star. It absorbs light "
                                f"near 3.3 µm, which is why this object is {'at least ' if col.get('lower_limit') else ''}{col['ratio']:.1f}× brighter at 4–4.75 µm.",
                      "basis": "SPHEREx flux at 4–4.75 µm ÷ flux at 3.3 µm"})
    if v and abs(v["delta_mag"]) > max(0.1, 3 * v["uncertainty_mag"]):
        pct = (10 ** (-0.4 * v["delta_mag"]) - 1) * 100
        facts.append({"id": "change", "headline": f"{'Faded' if pct < 0 else 'Brightened'} by about {abs(pct):.0f}% between {v['from']} and {v['to']}",
                      "detail": "Measured in infrared light, where pulsating and dust-hidden stars change less than they do in visible light.",
                      "basis": f"10^(−0.4 × {v['delta_mag']:+.2f} mag)"})
    if t.get("target_in_gaia") is False:
        facts.append({"id": "infrared_only", "headline": "Invisible to Gaia's visible-light camera",
                      "detail": "It shows up only in infrared light. Objects like this are what an infrared survey can find and a visible-light survey cannot.",
                      "basis": "no Gaia DR3 source at the predicted position"})

    if m:
        span = m["to_year"] - m["from_year"]
        pix = m["shift_arcsec"] / m["shift_spherex_pixels"] if m["shift_spherex_pixels"] > 0.5 else SPHEREX_PIXEL
        if span > 0:
            limits.append(f"Motion: an object must shift 2 SPHEREx pixels ({2 * pix:.0f}″) to count as moving. Over these {span:.1f} years "
                          f"that means faster than {max(0.3, 2 * pix / span):.2f}″ per year. Slower objects read as “no measurable motion”.")
        vis = sorted(x["year"] for x in t.get("spherex_visits") or [])
        if len(vis) >= 2 and vis[-1] > vis[0]:
            limits.append(f"SPHEREx alone covers only {(vis[-1] - vis[0]) * 12:.0f} months here: by the same 2-pixel rule, enough only for motion faster than "
                          f"{2 * pix / (vis[-1] - vis[0]):.0f}″ per year. The 2010 WISE image is what makes slower motion visible.")
    vis_n = len(t.get("spherex_visits") or [])
    if vis_n:
        limits.append(f"Brightness: compared at {vis_n} SPHEREx visit{'s' if vis_n != 1 else ''} only. A change between or outside those dates is not seen.")
    if t.get("spectrum_points") and t.get("flagged_points", 0) > 0.5 * t["spectrum_points"]:
        limits.append("Bright stars: this one overflows SPHEREx pixels, so its spectrum and exact brightness are not reliable here.")
    limits.append("Solar System: the page checks against Gaia stars only. It does not check asteroids or comets, "
                  "so a moving dot without a Gaia circle may be a known asteroid.")
    limits.append(f"Crowding: one SPHEREx pixel is {SPHEREX_PIXEL}″ wide, so two close objects can blend into one dot and one spectrum.")
    return {"facts": facts, "limits": limits}


def main():
    index = []
    for d in sorted(DATA.glob("*/target.json")):
        t = json.loads(d.read_text())
        gf = CACHE / d.parent.name / "gaia_facts.json"
        if gf.exists():
            t["gaia_facts"] = json.loads(gf.read_text())
        t["evidence"] = card(t)
        t["insights"] = insights(t)
        d.write_text(json.dumps(t, indent=1))
        ref = t["reference"]
        index.append({"id": t["id"], "name": t["name"], "teaser": TEASER.get(t["id"], t["kind"]),
                      "ra": t["grid"]["centre_ra"], "dec": t["grid"]["centre_dec"],
                      "fov": round(t["grid"]["npix"] * t["grid"]["arcsec_per_pix"])})   # side of the field, arcsec
        print(f"{t['name']:<18} {t['evidence']['status']:<9} {t['evidence']['classification']:<38} "
              f"confidence {t['evidence']['confidence']}")
    index.sort(key=lambda x: ORDER.index(x["id"]) if x["id"] in ORDER else 99)
    (DATA / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
