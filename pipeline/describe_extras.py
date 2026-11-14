"""Give the extra prepared targets proper names and descriptions (they were added with --ra/--dec)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
KINDS = {
    "Proxima Centauri": ("Nearest star to the Sun: a small red dwarf 4.2 light-years away", "Nearest star to the Sun"),
    "61 Cygni": ("A pair of orange dwarfs: the first star ever to have its distance measured (1838)", "First star distance ever measured"),
    "Wolf 359": ("One of the closest and faintest red dwarfs, 7.9 light-years away", "Faint nearby red dwarf"),
    "Lalande 21185": ("A red dwarf 8.3 light-years away with known planets", "Red dwarf with planets"),
    "Kapteyn's Star": ("An ancient halo star racing through our neighbourhood (second-fastest moving star)", "Ancient fast halo star"),
    "Luhman 16": ("The closest pair of brown dwarfs, 6.5 light-years away (not in Gaia's main catalogue)", "Closest brown dwarf pair"),
}
for d in (ROOT / "data" / "cache").glob("pos_*/target_def.json"):
    t = json.loads(d.read_text())
    if t["name"] in KINDS:
        t["kind"], t["teaser"] = KINDS[t["name"]]
        d.write_text(json.dumps(t, indent=1))
        tj = ROOT / "app" / "data" / d.parent.name / "target.json"
        if tj.exists():
            x = json.loads(tj.read_text()); x["kind"] = t["kind"]; x["teaser"] = t["teaser"]; tj.write_text(json.dumps(x, indent=1))
            print("described", t["name"])
