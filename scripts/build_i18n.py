"""Merge artifacts/i18n/<lang>-*.json (English -> <lang>) into app/i18n-<lang>.js, for every language found.

Run: python scripts/build_i18n.py
To add strings: put more {"English": "translation"} pairs in a <lang>-*.json file and run again.
To add a language: add <lang>-*.json files, run this, then add the language to LANGS in app/i18n.js
and the file to SHELL in app/sw.js.
"""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "artifacts" / "i18n"
langs = sorted({m.group(1) for f in src.glob("*-*.json") if (m := re.fullmatch(r"([a-z]{2})-\d+\.json", f.name)) and m.group(1) != "en"})
assert langs, "no translations found"
for lang in langs:
    d = {}
    for f in sorted(src.glob(f"{lang}-*.json")):
        d.update(json.loads(f.read_text(encoding="utf-8")))
    d = {" ".join(k.split()): v for k, v in d.items() if v and v != k}
    out = root / "app" / f"i18n-{lang}.js"
    out.write_text("/* Built by scripts/build_i18n.py from artifacts/i18n/" + lang + "-*.json. Do not edit by hand. */\n"
                   "window.I18N_DICT = " + json.dumps(d, ensure_ascii=False, indent=0) + ";\n", encoding="utf-8", newline="\n")
    print(lang, len(d), "strings ->", out.relative_to(root))
