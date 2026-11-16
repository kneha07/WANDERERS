# Language versions (中文, हिन्दी, Tiếng Việt, 한국어): run record, 2026-11-15

## How it works

```
page loads ──> i18n.js adds a language menu (EN · 中文 · हिन्दी · Việt · 한국어) next to each theme toggle
                 │
                 ├─ lang = ?lang=en|zh|hi|vi|ko  →  saved choice (localStorage "wanderers-lang")  →  browser language
                 │
                 └─ not en: load i18n-<lang>.js (English → <lang> dictionary)
                         swap text nodes + placeholder/title/aria-label/alt by whole-string match
                         MutationObserver translates content that scripts add later
```

Changing the language reloads the page. Hindi (हिन्दी) is the Indian language, as the most spoken one.

## Dictionary

1. `en-*.json`: 1,169 visible strings collected from the 6 pages in a browser.
2. `<lang>-*.json`: translations by parallel translator agents; every key checked present.
3. `python scripts/build_i18n.py` writes `app/i18n-<lang>.js` for every language found.
   Entries (strings that stay the same are dropped): zh 1,096 · vi 1,090 · ko 1,093 · hi 993 (Hindi keeps the 88 constellation names in English).

To add strings: add pairs to a `<lang>-*.json` file, then run the build script again.
To add a language: add `<lang>-*.json`, run the build, add the code to `LANGS` in `app/i18n.js` and the file to `SHELL` in `app/sw.js`.

## Checks

- All 6 pages in zh, hi, vi and ko: title, headings and controls are translated; only star names, file names and mission names stay English (on purpose).
- 375 px phone width (mobile emulation): no page is wider than the screen, in all 5 languages. The header got a smaller wordmark and tighter gaps at ≤ 420 px.
- `node --test test/*.test.js`: 664 pass, 0 fail. `i18n.js` loads as the last script, so the script-order tests still hold.
- Hindi headings get line-height 1.35, so Devanagari marks do not touch the next line.
- The menu change ko → vi reloads in Vietnamese and drops `?lang` from the address.

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

Tracked in issue kneha07/WANDERERS#94 (https://github.com/kneha07/WANDERERS/issues/94).
- Translations are machine-made and not reviewed by native speakers (issue kneha07/WANDERERS#96). Vietnamese constellation names use formal Hán-Việt forms. Korean uses "웹 망원경" in one short label but "Webb" in longer sentences.

## Decision note: strings with numbers (issue #94), 2026-11-15 (in progress)

- Problem: in zh/hi/vi/ko the star detail panels stay English. Metric: visible English sentences after a click probe of all 6 pages in zh. Before: 674. Target: < 30 (names and data codes only).
- Evidence: 674 sentences, 293 templates; 609 (90 %) have a number inside, 65 (10 %) are fixed sentences that show only after a click. Mostly Observatory panels starModel, starQuake, starProfile, lrCard, pathBody, facts. The 1,700 SPHEREx flag codes (BLOOM, OVERFLOW, …) are data codes and stay English.
- 3 Whys: English shows → text is not a dictionary key → numbers change per star, and load-time collection never clicked → i18n.js keys on the finished text, scripts paste numbers into English templates.
- Plan: i18n.js looks up the exact text first, then the number template ("{0} light-years away") and puts the numbers back. A click probe in all 4 visitor modes collected 756 new shapes (en-4…7.json). Build and test/i18n.test.js check that every translation keeps its placeholders.
- Rejected: rewriting 282 script templates as t() calls (about 10 files, conflicts with open branches).
- Probe lesson: the click probe clicked the Sky Survey CSV/JSON export buttons, which opened save prompts; the probe now skips export/download/share/camera buttons.
