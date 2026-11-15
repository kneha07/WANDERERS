# User-advocate review: feat/star-info (fix-loop round 3, phase 2)

- Seat: user_advocate (independent; I did not write this code). Runs after tech_lead PASS and project_manager PASS (r3).
- Branch `feat/star-info` at `df13adb`, worktree `.worktrees/star-info`.
- Live stack **through `server.js`**: `PORT=8101 LIVE_PORT=8102 node start.js --no-open`. Headless Chrome (Playwright,
  `channel: 'chrome'`), fresh profile per walk, 1440 × 900 and 375 × 812 (mobile, touch).
- I did not touch the main checkout or ports 8000/8001. At the end, 8101 and 8102 are free (`netstat`).
- Date: 2026-11-14.

## Verdict

**PASS.** No high finding. NH1 is fixed live. NM1 and NM2 are fixed live. 3 new low findings.

```
cold A (loading) ──► click chip B ──► B shows ──► 30 s later: server up, still B
   x5 names (3 at 1440, 2 at 375) + curl -m 2 abort   ──►   0 ERR_STREAM, health 200
```

## Must-checks

| # | Check | Result | Evidence (this walk) |
|---|---|---|---|
| 1 | NH1: cold name, switch chip while loading | PASS | 1440: Gliese 412 → R Dra, Gliese 445 → Barnard's Star, Struve 2398 → RW Aur. 375: Ross 154 → eps Ind B, Wolf 424 → R Dra. Each time the heading was "Loading A…" when I clicked; B showed; server alive 30 s later; heading still B. Plus `curl -m 2 /api/frames?q=Gliese+1` (aborted), then health polled until the late answer (see below). Server log: 0 `ERR_STREAM`, 0 `stopped (exit`. |
| 2 | NM1/NM2: typed `08h55m10.831s -07d14m42.53s` | PASS | Note under image: "A fast-moving star (WISEA J085510.74-071442.5, 8.2″/yr) is 127″ from here. Typed coordinates from an old catalogue may miss it — search it by name." Brightness: "No source at this position — the brightness numbers are sky noise." 0 matches for "larger than the noise". About: "…no source shows at this position, so its brightness numbers are sky noise." |
| 3a | About for Barnard's Star | PASS | "Barnard's Star is a red dwarf (spectral type M4V) about 6.0 light-years away. / In our SPHEREx frames it moves about 8.9″ per year toward the north-northwest. / SIMBAD lists 924 papers about it." Sources: CDS Sesame / SIMBAD · Wikipedia · SPHEREx. Warm: 0.01 s. Cold (first call this run): skeleton bars for > 10 s, no false text. |
| 3b | About for a clicked field star | PASS | "The nearest Gaia DR3 star, 2.8″ away, has G = 18.2 (Gaia brightness; larger is fainter). / This tool measures motion and brightness only at the target, so compare this mark between frames by eye. / Its history is unknown here." |
| 4a | No old target under a new heading | PASS | Barnard → Lacaille 9352 at 1 s, 5 s, 12 s: heading "Loading Lacaille 9352…", Motion has no Barnard text, label "Showing Barnard's Star until Lacaille 9352 loads." |
| 4b | Fast unknown-name error | PASS | `zzqx not a star r3`: 7.9 s cold (1440), 0.5 s warm (375). "No object called … found. Try another name or type RA/Dec …" + "Edit the name". |
| 4c | Share-link note | PASS | "This link opens only on this computer until the tool is hosted (issue #24). The report gives the RA and Dec instead." |

Abort probe: `curl -m 2` on cold `Gliese 1`, then health polled every 5 s for 240 s: health 200 every time, 0
`ERR_STREAM`. Limit: the backend did not log a finished answer for any aborted cold request within 240 s, so I did
not see the exact "late answer reaches a closed socket" moment live. The server stayed up through 5 browser aborts and
1 curl abort, and the tech_lead probe (fake upstream) covers the late-answer path.

## Round-2 findings

| Finding | Status | Note |
|---|---|---|
| NH1 server crash on target switch | FIXED | Must-check 1. Stress walk "Second target" (the screen that crashed twice in round 2) now PASS. |
| NM1 "larger than the noise" for empty sky | FIXED | Must-check 2. |
| NM2 no hint for old fast-mover coordinates | FIXED | Must-check 2. Residual: see UL1, UL2. |
| NL1 field name twice in Talk report | FIXED (per PM; not re-walked) | `web/src/rail.tsx` uses `titleOf(r).catalog`. |
| NL2 two motion numbers | FIXED | Motion: "moves about 8.9″ per year … (1.6 pixels in 13 months), as its catalogue motion predicts (10.4″ per year)". About uses the same 8.9″. |
| NL3 "G = 16.9" unexplained | FIXED | "(Gaia brightness; larger is fainter)". |
| NL4 stale label placement, old timeline | NOT FIXED (tracked #47) | Label still under the image. |
| NL5 About only in Data tab | NOT FIXED (tracked #47) | – |
| NL6 375 chip row scrolled to end | FIXED (per PM; not re-measured) | – |

## New findings

- **UL1 (low). At 1440 × 900 the fast-mover hint is below the fold.** Typed WISE 0855: the note box is at y 935–974
  (viewport 900). The user sees an empty field and must scroll to learn why. At 375 it is at y 779–837, half in view.
  Same placement class as NL4. Screenshot `ua-r3/1440-wise-typed.png`.
- **UL2 (low). The hint gives a distance but no direction.** "is 127″ from here" — the field is 5′, so the star is in
  the image, but the user cannot tell which dot. A direction ("127″ to the north-east") or the Ring on it would let
  the user find it without a new search.
- **UL3 (low). A cold About card can sit in skeletons for more than 10 s.** First Barnard call this run: Sesame
  `cds.unistra.fr` failed (ConnectionError) and the card waited on the fallback. Honest (no false text), but no
  "still asking the catalogs…" text. Second call: instant.

## UX stress walk (`designing-ux-mechanics/stress-walk.mjs`, through server.js)

Config: copy of `web/ux-walk.json` with `baseUrl` `http://localhost:8101` (the repo file was not edited).

| # | Check | Target | Result | Detail |
|---|---|---|---|---|
| N2 | Back (system) reaches home within 2 presses | Result (chip) | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Second target | PASS | 2 press(es) |
| N2 | Back (system) reaches home within 2 presses | Candidate marked | PASS | 1 press(es) |
| N2 | Back (system) reaches home within 2 presses | Tutorial layer | PASS | 0 press(es) |
| D1 | No empty state before the first answer | Frames (deep link) | PASS | skeleton, cache or loading shown |
| M1 | No layout shift when data lands (CLS ≤ 0.1) | Frames (deep link) | PASS | CLS 0.047 |
| A1 | Press shows a response within 100 ms | Search button | PASS | 20 ms |
| A2 | A double tap sends once | Search button | PASS | 1 request(s) |
| L1 | At most one layer over a screen | all walked steps | PASS | never more than one |

9 PASS, 0 FAIL.

## Manual checklist

| Item | Result | Reason |
|---|---|---|
| N1 | PASS | Back returns to the previous target (stress walk "Second target", 2 presses) |
| N3 | PASS | Marks use replaceState; no form re-opens on Back |
| N4 | PASS | Deep link `?q=…&c=…` opens target with marks (round 2; unchanged code) |
| N5 | NOT TESTED | – |
| N6 | PASS | Reload keeps target and marks (round 2; unchanged code) |
| L2 | PASS (partial) | Esc and close button close the tutorial; backdrop NOT TESTED |
| L3 | PASS | Focus returns to "?" (verify-ui) |
| L4 | PASS | No confirm dialogs |
| D2 | PASS | Warm targets show at once (0.45 s) |
| D3 | PASS | About grows in place with skeletons |
| D4 | PASS | Server stays up after aborts, so Retry and the next search work |
| D5 | NOT TESTED | – |
| A3–A5 | NOT TESTED | – |
| A6 | PASS (n/a) | No costly actions |
| M2–M5 | NOT TESTED | – |

## Shneiderman (one note each)

- Consistency: chips, names and coordinates use one flow and one heading form. OK.
- Shortcuts: Space/arrows for the flipbook; no key for Blink/Difference. Low, unchanged.
- Informative feedback: the hint and the sky-noise line now explain an empty field. Good.
- Closure: "Report copied…" and Talk opens. Good.
- Simple error handling: unknown name fails fast with "Edit the name"; server no longer dies. Good.
- Easy reversal: Back works; Remove has no Undo (old L2, open).
- Internal locus of control: the user can switch target during a load; it now works. Good.
- Short-term memory: stale label + dim image during a switch. Good (placement is NL4).
- Accessibility: text labels, no info by colour alone, no horizontal scroll at 375. Contrast not measured.

## Problem solved?

Yes. A user can change their mind during a slow load without stopping the app. A user who types the old WISE 0855
coordinates gets told why the center is empty and how to find the star, and is no longer told that empty sky blinks.

## Evidence (scratchpad, not committed)

`C:\Users\user\AppData\Local\Temp\claude\e6e349967ae79c2f\9142796b-c37a-4076-8fed-41ca7800fa56\scratchpad\`:
`ua-r3-crash.mjs`, `ua-r3-misc.mjs`, `ua-r3-about.mjs`, `ua-r3-walk.json`, `ua-r3-stress.log`, `ua-r3-server.log`,
`ua-r3/*.png`.
