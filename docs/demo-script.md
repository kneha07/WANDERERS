# Boot and demo script

Status on 2026-11-14 (evening): the one-click start and the `/explore/` mode work (tested with commit `f18c472`). The NASA-style redesign of `/explore/` is in progress on branch `feat/explore-redesign`.

## Boot (one click)

Needs Node.js and Python 3.11 or later. The first run installs the packages, so it takes a few minutes. Later runs take seconds.

- Windows: double-click `start.cmd`.
- macOS: double-click `start.command`.
- Any OS: run `node start.js`. Add `--precompute` the first time, so the 5 targets load at once.

The script starts the live API on port 8001 and WANDERERS on port 8000. Then it opens `http://localhost:8000`.

```
start.js ──► backend/.venv uvicorn :8001  (live SPHEREx frames, disk cache)
        └──► node server.js :8000 ──► /           WANDERERS missions (precomputed)
                                  ├─► /explore/   live blink tool (any target)
                                  └─► /api/frames proxy to :8001
```

- Open `http://localhost:8000` for the missions, and `http://localhost:8000/explore/` for the live explorer. The missions page also links to it with "Explore any patch (live) →".
- Stop: press Ctrl+C in the start window, or close it.
- If a port is busy: the script reuses our own servers on 8000/8001. It stops with a message if another program uses them.

### Stable demo copy (while implementers work on `main`)

`main` can hold half-finished work during development. For a demo, run from the worktree `.worktrees/demo` (detached at a good commit): double-click `.worktrees/demo/start.cmd`. Its `backend/.venv` and `web/node_modules` are junctions to the main checkout, so it needs no new install.

## Demo script (about 2 minutes)

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | WANDERERS, Barnard's Star | Show the 2010 → 2026 path and the Gaia ghosts | "Pluto was found by flipping two photos. We flip 16 years of infrared sky." |
| 0:25 | Evidence card | Point at the checks and "Confidence: high" | "Every claim shows its evidence. Unmatched objects are candidates, never discoveries." |
| 0:45 | WANDERERS, WISE 0855 | Switch to 4.6 µm | "The coldest known brown dwarf. It is bright only near 4.6 µm." |
| 1:00 | Coordinate box | Type a position outside the 5 targets → "Explore this patch live" | "Now any patch of sky, live from NASA's archive." |
| 1:10 | Live tool, Kapteyn's Star | Type `Kapteyn's Star`, then press Show. Wait about 25 s (cold) or 2 s (cached). | "SPHEREx maps the whole sky every six months. We stack each survey." |
| 1:35 | Difference view | Press Difference | "Dark where it was, bright where it is now. That pair is a mover." |
| 1:50 | Click the star | Open SIMBAD / Gaia from the popover; copy the share link | "Is it known? One click to check. Not known? Report it to Backyard Worlds." |

Screenshots of these steps: `artifacts/demo/1-wanderers-barnard.jpg`, `artifacts/demo/2-live-barnard.jpg`, `artifacts/demo/3-live-kapteyn-diff.jpg`.

## Demo safety

- Run the precompute step before the demo. IRSA sometimes answers 502/503 during the hackathon, and the cache makes the demo independent of that.
- Warm the cache for Kapteyn's Star too: open it once before the demo.
- R Draconis is saturated in SPHEREx. A display fix is in progress, so do not use it for the live part yet.
- Record the screen at 1440 × 900 or more. The sky images are small, and the page scales them up with sharp pixels.
