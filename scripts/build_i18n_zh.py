"""Merge artifacts/i18n/zh-*.json (English -> Chinese) into app/i18n-zh.js.

Run: python scripts/build_i18n_zh.py
To add strings: put more {"English": "中文"} pairs in a zh-*.json file and run again.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
d = {}
for f in sorted((root / "artifacts" / "i18n").glob("zh-*.json")):
    d.update(json.loads(f.read_text(encoding="utf-8")))
d = {" ".join(k.split()): v for k, v in d.items() if v and v != k}
assert d, "no translations found"
out = root / "app" / "i18n-zh.js"
out.write_text("/* Built by scripts/build_i18n_zh.py from artifacts/i18n/zh-*.json. Do not edit by hand. */\n"
               "window.I18N_ZH = " + json.dumps(d, ensure_ascii=False, indent=0) + ";\n", encoding="utf-8")
print(len(d), "strings ->", out)
