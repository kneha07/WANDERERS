# Boot and demo script

Status on 2026-11-14 (afternoon): WANDERERS (the precomputed missions) and the live blink tool both run locally. The one-click start (`start.cmd` / `start.command` / `node start.js`) and the `/explore/` mode inside WANDERERS are in progress. Until they land, use "Boot today".

## Boot (target: one click)

Once `start.js` lands:

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

## Boot today (before the merge)

1. WANDERERS (static, precomputed data): `python -m http.server 8002 -d app`. Run it from a checkout of `origin/main`. Open `http://localhost:8002`.
2. Live API: `backend/.venv/Scripts/python -m uvicorn backend.app:app --port 8000`. On macOS/Linux, use `backend/.venv/bin/python`.
3. Live page: `npm run dev` in `web/`. Open `http://localhost:5173`.
4. Before a demo, warm the cache: `backend/.venv/Scripts/python -m backend.precompute`.

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
