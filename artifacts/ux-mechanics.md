# UX mechanics: WANDERERS Explore redesign (/explore/)

Date: 2026-11-14. Branch: `feat/explore-redesign`. Design system: `design-system/spherex-blink/MASTER.md`.

Set-up for every check below:

```
browser ──► Vite dev server :5183 (web/, VITE_API_TARGET=http://localhost:8011)
                 └─/api─► FastAPI backend :8011 (backend/ of this branch, after the merge of main)
```

## 1. Stress walk (automated)

Command, from `web/`:

```bash
node <ycm-harness>/skills/designing-ux-mechanics/stress-walk.mjs ux-walk.json --out ../artifacts/ux-walk
```

Exit status 0. Viewport 390 x 844 with touch. The config is `web/ux-walk.json`; its `setup` step closes the
first-run tutorial.

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Result (chip) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Second target | PASS | 2 press(es) |
| N2 | Back (system) reaches home within 2 presses | Candidate marked | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Tutorial layer | PASS | 0 press(es) |
| D1 | No empty state before the first answer | Frames (deep link) | PASS | skeleton, cache or loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Frames (deep link) | PASS | CLS 0.030 |
| A1 | Press shows a response within 100 ms | Search button | PASS | 20 ms |
| A2 | A double tap sends once | Search button | PASS | 1 request(s) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

9 PASS, 0 FAIL. The raw table is `artifacts/ux-walk/stress-walk.md`.

## 2. Behaviour checks in a real browser (automated)

Command, from `web/`: `node scripts/verify-ui.mjs` (Chrome, 1440 x 900). Exit status 0, 23 PASS, 0 FAIL.

| Mechanic | Result |
|---|---|
| The tutorial opens on the first visit, only once; Esc closes it; focus returns to the "?" button | PASS |
| A chip loads a target; Back returns to the previous target at once (in-memory cache) | PASS |
| Space pauses; ArrowRight steps one frame; arrows in the search field do not step | PASS |
| A mark on Barnard's Star says "Known in Gaia DR3: 4472832130942575872, G 8.2, 0.3″ away" | PASS |
| The URL holds the mark (`c=`, replaceState); the mark survives a reload | PASS |
| One toast says what happened; "Copy share link" copies the URL with the mark | PASS |
| `look=colour` goes to the URL, shows the honesty label, and persists to the next target | PASS |
| The D6 view (no `rgb_png`) disables the colour presets | PASS |
| WISE 0855 D6 brightness: "Change: 98% (2.7σ) from 0.3096 to 0.8602 mJy — within the noise" | PASS |
| Difference view goes to the URL (`view=diff`); a timeline click jumps to the nearest frame | PASS |
| The frames table sorts by a column (`aria-sort`) | PASS |
| No page errors during the walk | PASS |

Other checks (scripts in the session scratchpad, results here):

| Check | Result |
|---|---|
| Horizontal scroll at 375, 768, 1024 and 1440 px, home and result screens | none (PASS) |
| Enter on the focused flipbook marks a candidate at the center | PASS |
| Reduced motion: no autoplay; the sky map jumps (20′ at once); the dome dot is static | PASS |
| Bad name ("zzqx not a star"): error with icon, text, examples and Retry, next to the search | PASS |
| Sky map flies: 20′ → 49° → 60° (pan) → 37° → 20′ on the new target (`redesign-skymap-fly-1440.png`) | PASS |
| "Your sky now", Seattle, 2026-11-14 23:04 UTC: Barnard 46.6° (astropy 46.61°), RW Aur −9.8° (−9.82°), Kapteyn −76.2° (−76.23°) | PASS |
| The Sky now panel crashed once (animation index); its error boundary kept the rest working. Fixed. | PASS after fix |

## 3. Pre-delivery checklist (MASTER.md)

| Item | Result | Evidence |
|---|---|---|
| Text contrast 4.5:1 or more (body text 7:1 on the panel) | PASS | text 14.6:1 on the panel; muted 7.1:1 on the panel, 6.0:1 on raised; white on action 5.0:1; data blue 9.1:1; amber 9.7:1; green 8.9:1; error 6.7:1 |
| Visible focus on every control; full keyboard use | PASS | 2px data-blue `:focus-visible` ring; tabs (arrows, Home, End); timeline is a slider (arrows, Home, End); sort buttons; Enter on the flipbook marks a candidate |
| No emoji icons; every icon button has a label | PASS | inline SVG icons; play, pause, step and "?" have `aria-label` |
| Tap targets 44px or more | PASS (own controls) | every button, link, tab, select and table button is 44px or more. Aladin Lite's own zoom buttons are smaller (third-party UI). |
| CLS below 0.1 | PASS | stress walk M1: 0.030 |
| Reduced motion respected | PASS | no autoplay, no transitions, sky map jumps, static dome dot, tutorial blink shown side by side |
| 375 / 768 / 1024 / 1440 px with no horizontal scroll | PASS | measured `scrollWidth` = `clientWidth` on home and result at all four widths |
| No NASA insignia, logotype or seal; footer says "Not an official NASA product." | PASS | custom favicon; footer text on every screen |
| No raw hex colour in a component | PASS | `grep` finds 0 hex literals in `web/src/*.tsx`; tokens in `index.css` |
| No meaning by colour alone | PASS | ring = thick dashed circle, Gaia = thin circle, candidate = numbered square; badges have ✓ or ? and text; SAT = triangle and survey number; errors have an icon and text |

## 4. Screenshots (looked at)

`artifacts/ux-walk/redesign-*.png`: Barnard's Star, Kapteyn's Star and RW Aur at 1440 and 375 px (full page),
Kapteyn's Star in the Raw and Realistic looks at both widths, the tutorial at both widths, the home screen at both
widths, and the sky-map fly strip.

## 5. Known limits

- RW Aur and Barnard's Star are saturated in SPHEREx (RW Aur: surveys 2–3; Barnard: all). The backend gives no
  flux there, so the brightness chart cannot show the RW Aur change. The panel shows the points that exist
  (RW Aur survey 1: D1 160 mJy, D3 619 mJy), says "Saturated in surveys 2–3: too bright for SPHEREx to measure
  here", and links to the matched-wavelength check in WANDERERS (`/?target=rw_aur`).
- Aladin Lite 3.8.2 maps a cube slice number to a frame in a non-linear way. `SkyContext.tsx` inverts that
  mapping (marked `ponytail:`) so the SPHEREx HiPS shows frame 46 (2.19 µm).
- The CDS primary HiPS host answered 404 on 2026-11-14, so 2MASS and DSS2 come from the IRSA mirrors.
- "Your sky now" uses a geometric horizon (no refraction) and mean sidereal time: about 0.1° accuracy.
- The stress walk does not test L2–L4, D2, D4, D5, A3–A6, M2–M5 and N4–N6 of the checklist by script;
  section 2 covers the layer, toast, keyboard and URL items by hand-written browser checks.
