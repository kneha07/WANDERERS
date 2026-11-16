# Review: merge of `feature/chinese-version` (10fdbc4) into `main` (442e5c2)

- Date: 2026-11-15. Tracking issue: #110. Related: #94 (closed), #96 (native-speaker review).
- Integration branch: `integrate/chinese-version` in `.worktrees/integrate-zh`. Not pushed.
- Reviewer: an independent agent. It did not write the branch.

## Verdict: PASS (after the fixes on the integration branch)

One High finding was found and fixed. No open High finding.

```
main 442e5c2 ──┐
               ├── 586efce  merge --no-ff feature/chinese-version (1 conflict: app/compass.html)
10fdbc4 ───────┘     │
                     ├── fed43c2  fixes: new strings (<lang>-9.json), HK words, Done flag, lazy dictionaries
                     └── (this file)
```

## Conflict resolution

`app/compass.html`, the script list at the end of the body.

- Kept main's script tags and newest `?v=` keys: `realsky.js?v=20261118h`, `compass.js`, `learn.js?v=20261118g`.
- Added the branch's `i18n.js` before the `compass.js` module (app/compass.html:239).
- Auto-merged without conflict: `app/observatory.html`, `app/sw.js`. Both were checked by hand.

## Findings

### High

| # | File:line | Finding | Fix |
|---|---|---|---|
| H1 | app/compass.js:874 | The sight-check button tested its own text: `if ($("aimGo").textContent === "Done")`. The language menu translates "Done" (完成, हो गया, Xong, 완료). In 6 languages, a tap on "Done" did not close the aim bar. It calibrated north again with the phone's pose at the time of the tap. A moved phone gave a wrong north. | The state is now a flag: `S.aimOk` (app/compass.js:868, 874, 877). `compass.js?v=20261118m`. |

### Medium

| # | File:line | Finding | Fix or status |
|---|---|---|---|
| M1 | app/compass.html, app/learn.js, app/realsky.js, app/search.js, app/skyview.js | Main added about 180 visible English strings after the branch base 58722d9. In zh, they stayed English: pull-out bar labels, search placeholder, 🎓 menu items, all 7 Learn modes, "✓ I saw it", distance and "For scale" lines, galaxy cards, HEASARC credits. | Fixed. `artifacts/i18n/<lang>-9.json` adds 183 strings and number templates. Rebuilt with `scripts/zh_to_traditional.py` and `scripts/build_i18n.py`. Generated files were not edited by hand. |
| M2 | scripts/zh_to_traditional.py:26 | Mainland words were left in `hk-*.json`: 上傳, 粘貼, 撤銷, 設置, 原始文件, 韋布 (Webb). | Fixed. 6 entries added to `HK_WORDS` (上載, 貼上, 復原, 設定, 原始檔案, 韋伯). The self-check covers 3 of them. |
| M3 | app/sw.js:38 | The service worker fetched all 6 dictionaries (1.6 MB) at install for every visitor, also for English users. The shell before was 2.2 MB, so this was +73 %. | Fixed. The dictionaries are in `LAZY`: each one is stored the first time its language is used. Trade-off: a non-English visitor needs one online visit after the worker installs before that language works offline. |

### Low

| # | File:line | Finding | Status |
|---|---|---|---|
| L1 | app/i18n.js:48 | `v.replace(v.trim(), t)` reads `$&`, `$1` in a translation as patterns. No dictionary has `$` now. | Fixed: `() => t`. |
| L2 | app/i18n.js:36 | The dictionary cache key was fixed at `20261116e`. Changed dictionaries need a new key. | Fixed: `20261118a`, and `i18n.js?v=20261118a` on all 6 pages. |
| L3 | app/realsky.js:403 | The Deep status line ("Background: Digitized Sky Survey 2 (visible light). … · No motion sensors: drag to aim") stays English. It joins 3 changing parts into one text node. It was in the branch base too. | Open. Needs per-part text nodes or `t()` templates (README upgrade path step 2). |
| L4 | app/learn.js, app/realsky.js | Sentences with a name stay English: "Find Bellatrix", "A bright star in Orion, magnitude 1.6.", "Pole star: Vega …", galaxy names. Names stay English by the branch's rule; the sentence around them does too. | Open. Same fix as L3. |
| L5 | app/learn.js:91 | Main bug, not from this branch: `yearText` uses `toLocaleString("en-US")` on a year, so the Time machine shows "2,026 CE". | Open. Report to main. |
| L6 | app/i18n.js:24 | The menu's `aria-label` stays "Language" in every language. A screen reader in zh reads an English word. The options have `lang` and `title`. | Open. Small. Owner decides. |
| L7 | artifacts/i18n/zh-*.json | The zh text mixes ASCII and full-width punctuation ("網絡?先在", "(AirDrop、數據線或 iCloud)"). tw and hk keep mainland quotes “ ” where Taiwan and Hong Kong use 「 」. tw keeps 韋布 (Taiwan name: 韋伯). | Open. Native-speaker review (#96). |
| L8 | app/compass.html (Korean) | A heading split by `<br>` is translated in parts. Korean reads "휴대폰을 향해 보세요하늘로" (word order wrong). Known limit in the README. | Open. |

## Review of the branch diff

- XSS / injection: PASS. `i18n.js` writes only `nodeValue` and `setAttribute` on `placeholder`, `title`, `aria-label`, `alt`. It never writes `innerHTML`, `href`, `src` or an event attribute. Dictionaries are static same-origin files. A number template inserts only digits taken from the original text.
- MutationObserver: PASS. It observes `childList`, `characterData` and the 4 text attributes. It does not observe `hidden`. The layer stack in app/compass.js observes only `hidden`, so the two observers cannot loop. A dictionary chain check (does a translation match another key?) found 0 chains in all 6 dictionaries. Cost on compass.html in zh with the tour running for 10 s: 103 callbacks, 6.1 ms in total. In English: no dictionary loads and no observer starts (0 callbacks).
- Other code that reads text back from the DOM: `starquake-ui.js:50` saves and restores a label (safe). `explorer-observatory.js:117` copies a translated status into a summary (safe). `compass.js:874` was H1.
- Service worker: PASS after M3. `i18n.js` is in `SHELL`; the dictionaries are in `LAZY`. `bare()` drops `?v=`, so cache keys match.
- CSP / `app/_headers`: PASS. No new host. `app/_headers` and `server.js` are unchanged.
- Accessibility: PASS. The `<select>` has `aria-label="Language"`. Each option has `lang` and a full-name `title`. `<html lang>` changes per language (zh-CN, zh-TW, zh-HK, hi, vi, ko).
- English with no choice: PASS. With empty storage, no `?lang` and an en-US browser, `index.html` stays English, `<html lang="en">`, and no dictionary loads.

## Checks run (in `.worktrees/integrate-zh`)

| Check | Result |
|---|---|
| `node --test test/*.test.js` | 679 tests: 677 pass, 0 fail, 2 skipped. Main had 670 pass; the branch adds 7 (`test/i18n.test.js`). |
| `node --check` on `app/*.js` (50 files), `server.js`, `fields.js`, `start.js` | 53 files, 0 errors. |
| `node test/browser/realsky.mjs` (headless Edge, network) | 60 PASS, 0 FAIL. Screenshots and `browser-checks.json` restored afterwards. |
| Browser: compass.html and index.html in en, zh, tw, hk, hi, vi, ko | 14 loads, 0 page errors. Title, `<html lang>` and menu value correct for each. |
| Browser: English left in zh, all 6 pages at load | Only names, catalogue IDs, data codes and mission names. New strings from main: none left. |
| Browser: English left in zh after each of the 7 Learn modes (and tour "Next stop") | Before the fix: about 110 strings. After: 4 (L3, L4: "Saturn", "Find Bellatrix", the Bellatrix clue, the Deep status line). |
| `git diff --check main HEAD` | Clean. |
| `git ls-files -u`, conflict markers | None. |
| `.github/workflows` `uses:` | 19 lines, all pinned to a 40-character SHA. The branch does not change `.github`. |

## Not verified

- No native speaker read any language. The 183 new strings in `<lang>-9.json` are machine translations by this reviewer. Add them to #96.
- No real phone. The H1 fix was checked by code reading only: the desktop has no motion sensors, so the sight check cannot pass there.
- Offline use of a non-English language on a phone (M3 trade-off) was not tested.
- Click probes on observatory, starfix, stories and survey were not repeated. Main did not change their visible text after 58722d9 (only script keys on observatory.html).

## Owner decisions

1. Hong Kong words not changed, because they are also used in Hong Kong or need context: 視圖 (8×, Hong Kong UI often uses 檢視), 點擊 (1×), 數據線 (1×), 網絡連接 (Hong Kong also uses 連線), FITS 頭文件 (標頭?).
2. M3 trade-off: keep the dictionaries lazy (less data for everyone) or store all 6 at install (offline in any language after one visit).
3. L6: translate the menu's own "Language" label or keep it English as a fixed landmark.
