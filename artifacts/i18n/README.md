# Chinese (中文) version: run record, 2026-11-15

## How it works

```
page loads ──> i18n.js adds an EN / 中文 button next to each theme toggle
                 │
                 ├─ lang = ?lang=zh|en  →  saved choice (localStorage "wanderers-lang")  →  browser language
                 │
                 └─ zh: load i18n-zh.js (English → 中文 dictionary)
                         swap text nodes + placeholder/title/aria-label/alt by whole-string match
                         MutationObserver translates content that scripts add later
```

Switching back to English reloads the page.

## Dictionary

1. `en-*.json`: 1,169 visible strings collected from the 6 pages in a browser.
2. `zh-*.json`: translations (4 parallel translator agents; every key checked present).
3. `python scripts/build_i18n_zh.py` writes `app/i18n-zh.js` (1,096 entries; strings that stay the same are dropped).

To add strings: add pairs to a `zh-*.json` file, then run the build script again.

## Checks

- All 6 pages in zh: title, headings and controls are Chinese; only star names, file names and mission names stay English (on purpose).
- 375 px phone width: no page is wider than the screen, in EN and in zh. The header got a smaller wordmark and tighter gaps at ≤ 420 px.
- `node --test test/*.test.js`: 664 pass, 0 fail. `i18n.js` loads as the last script, so the script-order tests still hold.

## Known limits

- Text that scripts build with numbers inside (for example "34 epochs · 4.6 µm") stays English.
- Some sentences are split by links into parts; each part is translated alone, so word order can read a bit stiff.
- New English text added later stays English until someone adds it to the dictionary.
- No separate URL per language for search engines; English shows briefly before the dictionary loads.

## Upgrade path (if more languages are planned)

No redesign is needed for one more language: add a dictionary file and a build step. For real localization, upgrade step by step:

1. Format numbers and dates with `Intl`.
2. Change JS sentences built with numbers into `t("key", {n})` templates per language (fixes the main gap).
3. Add a test that fails when a visible string has no translation.
4. Only if search ranking matters: build `/zh/...` pages at deploy time.

Whether to file an issue for this is an open owner decision (asked 2026-11-15).
