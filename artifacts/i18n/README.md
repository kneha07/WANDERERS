# Language versions (简体中文, 繁體中文 台灣 / 香港, हिन्दी, Tiếng Việt, 한국어): run record, 2026-11-15

## How it works

```
page loads ──> i18n.js adds a language menu (EN · 简中 · 繁·台 · 繁·港 · हिन्दी · Việt · 한국어) next to each theme toggle
                 │
                 ├─ lang = ?lang=en|zh|tw|hk|hi|vi|ko  →  saved choice (localStorage "wanderers-lang")  →  browser language
                 │          (zh-HK / zh-MO → hk, zh-TW / zh-Hant → tw, other zh → zh)
                 │
                 └─ not en: load i18n-<lang>.js (English → <lang> dictionary)
                         swap text nodes + placeholder/title/aria-label/alt by whole-string match
                         MutationObserver translates content that scripts add later
```

Changing the language reloads the page. Hindi (हिन्दी) is the Indian language, as the most spoken one.

## Dictionary

1. `en-*.json`: `en-0…3` are 1,169 strings seen at page load; `en-4…7` are 756 strings and number templates seen only after clicks (all 4 visitor modes); `en-8` is one loading message added by hand.
2. `<lang>-*.json`: translations by parallel translator agents; every key checked present.
3. `python scripts/build_i18n.py` writes `app/i18n-<lang>.js` for every language found.
   Entries (strings that stay the same are dropped): zh 1,792 · ko 1,783 · vi 1,780 · hi 1,682 (Hindi keeps the 88 constellation names in English).

Traditional Chinese is not translated from English. `scripts/zh_to_traditional.py` converts every `zh-*.json` with OpenCC
(`s2twp` → `tw-*.json` with Taiwan words such as 軟體 / 影片 / 網路; `s2hk` → `hk-*.json` with Hong Kong words such as 軟件 / 視頻 / 網絡).
Needs `pip install opencc-python-reimplemented==0.1.7` at build time only. Entries: tw 1,792 · hk 1,792.

To add strings: add pairs to a `<lang>-*.json` file, then run the build script again. After a change to `zh-*.json`, run `zh_to_traditional.py` first.
To add a language: add `<lang>-*.json`, run the build, add the code to `LANGS` in `app/i18n.js` and the file to `SHELL` in `app/sw.js`.

## Checks

- All 6 pages in zh, hi, vi and ko: title, headings and controls are translated; only star names, file names and mission names stay English (on purpose).
- 375 px phone width (mobile emulation): no page is wider than the screen, in all 7 languages (tw and hk checked by page load only, no clicks). The header got a smaller wordmark and tighter gaps at ≤ 420 px.
- `node --test test/*.test.js`: 671 pass, 0 fail. `test/i18n.test.js` checks every dictionary keeps its `{n}` placeholders, and that the browser language picks the right version (zh-Hant-HK → Hong Kong, zh-Hant → Taiwan). `i18n.js` loads as the last script, so the script-order tests still hold.
- Hindi headings get line-height 1.35, so Devanagari marks do not touch the next line.
- The menu change ko → vi reloads in Vietnamese and drops `?lang` from the address.

## Known limits

- Text that no probe saw stays English. Numbers inside text are handled by number templates (see the decision note).
- Translations are machine-made and not reviewed by native speakers (issue kneha07/WANDERERS#96; Taiwan and Hong Kong are not listed there yet, owner said "not now" on 2026-11-15). Vietnamese constellation names use formal Hán-Việt forms. Korean uses "웹 망원경" in one short label but "Webb" in longer sentences.
- Some sentences are split by links into parts; each part is translated alone, so word order can read a bit stiff.
- New English text added later stays English until someone adds it to the dictionary.
- No separate URL per language for search engines; English shows briefly before the dictionary loads.

## Upgrade path (if more languages are planned)

No redesign is needed for one more language: add a dictionary file and a build step. For real localization, upgrade step by step:

1. Format numbers and dates with `Intl`.
2. Change JS sentences built with numbers into `t("key", {n})` templates per language (fixes the main gap).
3. Add a test that fails when a visible string has no translation.
4. Only if search ranking matters: build `/zh/...` pages at deploy time.

Tracked in issue kneha07/WANDERERS#94 (https://github.com/kneha07/WANDERERS/issues/94), closed 2026-11-15 with the result comment. Step 2 is now covered by number templates in `i18n.js` without a script rewrite; step 3 is covered for placeholders only.

## Decision note: strings with numbers (issue #94), 2026-11-15

- Problem: in zh/hi/vi/ko the star detail panels stay English. Metric: visible English sentences after a click probe of all 6 pages in zh. Before: 674. Target: < 30 (names and data codes only).
- Evidence: 674 sentences, 293 templates; 609 (90 %) have a number inside, 65 (10 %) are fixed sentences that show only after a click. Mostly Observatory panels starModel, starQuake, starProfile, lrCard, pathBody, facts. The 1,700 SPHEREx flag codes (BLOOM, OVERFLOW, …) are data codes and stay English.
- 3 Whys: English shows → text is not a dictionary key → numbers change per star, and load-time collection never clicked → i18n.js keys on the finished text, scripts paste numbers into English templates.
- Plan: i18n.js looks up the exact text first, then the number template ("{0} light-years away") and puts the numbers back. A click probe in all 4 visitor modes collected 756 new shapes (en-4…7.json). Build and test/i18n.test.js check that every translation keeps its placeholders.
- Rejected: rewriting 282 script templates as t() calls (about 10 files, conflicts with open branches).
- Verification (same click probe, visible English sentences, all 6 pages):

  | Language | Before | After |
  |---|---|---|
  | zh | 674 | 12 |
  | hi | — | 12 |
  | vi | — | 9 |
  | ko | — | Observatory 8; other pages not measured (probe stopped, see below) |

  What is left is names, catalog IDs, citations and data-source labels (for example "ESA Gaia DR3", "Bedding et al. 2010"), which stay English on purpose.
- Phone width: 375 px mobile emulation, 6 pages × 5 languages, no page wider than the screen (load only, no clicks).
- Probe lesson: a click-every-button probe opens save prompts. The Sky Survey CSV/JSON export and the starquake .wav save build a hidden `<a download>` and click it from script (`survey.js`, `share.js`, `starquake-ui.js`). A skip list by button name fails once the names are translated. Do not run click probes on these pages again without blocking `<a download>` clicks first.
