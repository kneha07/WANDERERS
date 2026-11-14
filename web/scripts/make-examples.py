"""Cut the tutorial and field-guide examples (web/public/examples/*.png) from real /api/frames responses.

Usage: python make-examples.py <dir with Barnards_Star.json, Kapteyns_Star.json, RW_Aur.json> <out dir>
The JSON files are saved answers of GET /api/frames?q=<name>&fov=5 (SPHEREx DR1/QR3 via IRSA).
The crops keep the raw display pixels; the page scales them up with image-rendering: pixelated.
"""
import base64, io, json, sys
from pathlib import Path
from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
load = lambda name: json.loads((src / f"{name}.json").read_text())
png = lambda s: Image.open(io.BytesIO(base64.b64decode(s.split(",", 1)[1]))).convert("L")
det = lambda r, d, g: next(x["png"] for x in r["detectors"][d] if x["group_index"] == g)

barnard, kapteyn, rwaur = load("Barnards_Star"), load("Kapteyns_Star"), load("RW_Aur")
mid = (14, 14, 35, 35)  # 21 x 21 px around the target (left, top, right, bottom)
crops = {
    "mover-1": (png(barnard["frames"][0]["png"]), mid),
    "mover-2": (png(barnard["frames"][4]["png"]), mid),
    "dipole": (png(kapteyn["difference"]["png"]), mid),
    "blinker-1": (png(rwaur["frames"][0]["png"]), mid),
    "blinker-2": (png(rwaur["frames"][2]["png"]), mid),
    "blinker-diff": (png(rwaur["difference"]["png"]), mid),
    "hot-pixel": (png(det(rwaur, "D5", 1)), (28, 12, 49, 33)),
    "saturated-core": (png(barnard["frames"][0]["png"]), (17, 17, 32, 32)),
    "no-data": (png(det(barnard, "D2", 5)), mid),
}
for name, (im, box) in crops.items():
    im.crop(box).save(out / f"{name}.png", optimize=True)
    print(name, box)
for r, label in ((barnard, "Barnard"), (kapteyn, "Kapteyn"), (rwaur, "RW Aur")):
    print(label, [f["label"] for f in r["frames"]], r["difference"]["from"], "->", r["difference"]["to"])
