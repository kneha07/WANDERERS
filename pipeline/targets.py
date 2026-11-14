"""Test targets named in the Planet X and SPHEREx challenge brief, plus how to find each one.

Positions and motions come from Gaia DR3 at run time when the object is in Gaia.
WISE 0855 is too cold and faint for Gaia, so its reference values come from the
literature (Luhman & Esplin 2016, AJ 152, 78) and are marked as such in the output.
"""

TARGETS = {
    "barnard": {
        "name": "Barnard's Star",
        "kind": "Nearby red dwarf, the fastest-moving star in our sky",
        "gaia_source_id": 4472832130942575872,
        "story": "motion",
    },
    "eps_indi_b": {
        "name": "Epsilon Indi B",
        "kind": "A pair of brown dwarfs orbiting the star Epsilon Indi",
        # J2000 position and common proper motion, used to find the Gaia match near epoch 2016.0
        "seed": {"ra": 331.0438, "dec": -56.7827, "epoch": 2000.0, "pmra": 3966.0, "pmdec": -2536.0},
        "story": "motion+spectrum",
    },
    "wise0855": {
        "name": "WISE 0855-0714",
        "kind": "The coldest known brown dwarf, about as cold as the North Pole",
        # Coordinates from the challenge brief (AllWISE designation, epoch ~2010.5);
        # proper motion and parallax from Luhman & Esplin 2016.
        "literature": {"ra": 133.79513, "dec": -7.24515, "epoch": 2010.5,
                        "pmra": -8123.0, "pmdec": 673.0, "parallax": 449.0,
                        "ref": "Luhman & Esplin 2016, AJ 152, 78"},
        "story": "motion+not-in-gaia",
    },
    "rw_aur": {
        "name": "RW Aurigae",
        "kind": "A young star that dims unpredictably behind clouds of dust",
        "seed": {"ra": 76.95642, "dec": 30.40142, "epoch": 2000.0, "pmra": 0.0, "pmdec": 0.0},
        "story": "variability",
    },
    "r_dra": {
        "name": "R Draconis",
        "kind": "A pulsating red giant (Mira variable) that brightens and fades over about 245 days",
        "seed": {"ra": 248.1676, "dec": 66.7550, "epoch": 2000.0, "pmra": 0.0, "pmdec": 0.0},
        "story": "variability",
    },
}


# Targets added from the command line (pipeline/fetch.py --ra .. --dec ..) are stored next to their
# cached data so every pipeline step sees them.
import json as _json
from pathlib import Path as _Path
_CACHE = _Path(__file__).resolve().parent.parent / "data" / "cache"
for _f in sorted(_CACHE.glob("*/target_def.json")):
    TARGETS.setdefault(_f.parent.name, _json.loads(_f.read_text()))
