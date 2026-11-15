# Run record: pick up from Fable, finish the handoff (2026-11-14/15)

Handoff: `docs/HANDOFF.md` (tasks 1-4).

| Task | Result |
|---|---|
| 1. Land `feature/insights` | PR #25 opened, then merged by the team |
| 2. Real sky behind Sky Compass | PR #40: ported onto the AR compass from #33. 29/29 browser checks, 188 unit tests. Open items: #42 |
| 3. Mover search finds its own targets | Fix done (`fix/mover-pairing`, `47acba3`), not pushed: data decision in #41 |
| 4. Next product item | Not started: needs the owner's choice (asteroid check, one product #6/#9, live-API host #24, timeline, production basics) |

## Decisions
- Real-sky split with a second agent (user's choice): it did offline shell, star taps, lines, roll (`feature/real-sky-core`); this run did Infrared, drag the sky, cache checks (`feature/real-sky-finish`). Both merged, then ported in #40.
- Port design: `app/realsky.js` holds the sky; Deep uses Aladin `TAN` (the camera projection); Eye reads `data/skystars.json`, main's `data/stars.json` stays the search file.

## Findings
- Edge signs a fresh test profile in with the Windows account and syncs the user's extensions (MetaMask etc.). Browser checks must use `--disable-sync --disable-extensions`.
- `compass.js` imported three.js (CDN) statically through `intro.js`: a CDN failure stopped the page. Now loaded on demand.
- Aladin Lite logs the page address to CDS by default: `log: false` added in `app.js` and `telescope.js`.
- Registration near the horizon: refraction lifts drawn stars (0.5° at 0°), photographs cannot follow; checks use objects at 5° or more.
- Fusion (`orient.js`) applies `fineAz` only at the next sensor event, smoothed: drag-the-sky solves on a modelled pose.

## Branches left (not merged, kept for reference)
`feature/real-sky`, `feature/real-sky-core` (worktree `.worktrees/real-sky-2`), `feature/real-sky-finish` (`.worktrees/real-sky-finish`), `fix/mover-pairing`, `fix/mover-pairing-data` (`.worktrees/movers`).
