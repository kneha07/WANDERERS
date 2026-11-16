"""Make the Traditional Chinese dictionaries from the Simplified ones with OpenCC.

  artifacts/i18n/zh-N.json --s2twp--> tw-N.json  (Taiwan: 軟體, 影片, 網路, 裡)
                           --s2hk---> hk-N.json  (Hong Kong: 軟件, 視頻, 網絡, 裏)

Only the translations are converted; the English keys and {n} placeholders stay the same.
Run after any change to zh-*.json, then run scripts/build_i18n.py.
Needs: pip install opencc-python-reimplemented==0.1.7 (build-time only; the site does not use it).
"""
import json
from pathlib import Path

from opencc import OpenCC

src = Path(__file__).resolve().parent.parent / "artifacts" / "i18n"
for code, cfg in (("tw", "s2twp"), ("hk", "s2hk")):
    cc = OpenCC(cfg)
    for f in sorted(src.glob("zh-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out = src / f.name.replace("zh-", f"{code}-", 1)
        out.write_text(json.dumps({k: cc.convert(v) for k, v in d.items()}, ensure_ascii=False, indent=0) + "\n",
                       encoding="utf-8", newline="\n")
    print(code, cfg, "done")
