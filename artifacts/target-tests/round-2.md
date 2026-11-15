# Challenge target tests, round 2 (2026-11-14, evening)

Tester: the orchestrator. Stack: `node start.js` on `main` at `0def95a` (WANDERERS `server.js` :8000 → proxy → live API :8001). Request: `GET http://localhost:8000/api/frames?q=<target>` with the defaults (FOV 5', `per_group` 12, all detectors).

| Target | HTTP | Time | Frames | Centroids | Photometry | Gaia stars | RGB frames | Saturated | Failed images |
|---|---|---|---|---|---|---|---|---|---|
| Barnard's Star | 200 | 3.7 s | 6 | 6 | 0 | 150 | 6 | 6 | 0 |
| Epsilon Indi B (`eps Ind B`) | 200 | 3.4 s | 5 | 5 | 4 | 20 | 5 | 0 | 0 |
| WISE 0855 (`WISE J085510.83-071442.5`) | 200 | 3.0 s | 4 | 3 | 3 | 28 | 4 | 0 | 0 |
| RW Aurigae (`RW Aur`) | 200 | 3.2 s | 3 | 3 | 0 | 109 | 3 | 2 | 0 |
| R Draconis (`R Dra`) | 200 | 3.1 s | 9 | 9 | 0 | 21 | 9 | 9 | 0 |
| Kapteyn's Star (not a challenge target) | 200 | 7.0 s | 3 | 3 | 0 | 20 | 3 | 3 | 0 |

All targets were in the disk cache. The time includes the Gaia query, which runs on each request from its own cache.

## Checks by eye (browser, 1440 px and 375 px)

- **Kapteyn's Star, Realistic look:** a colour star with a soft glow. Gaia ghosts sit on the field stars. The label says "False-colour infrared · smoothed, with glow, for display · measurements use raw pixels".
- **Kapteyn's Star, motion panel:** measured 8.6″ towards PA 128°, predicted 8.5″ towards PA 131° (frame 1 → 3).
- **Barnard's Star, motion panel:** measured 9.6″ towards PA 348°, predicted 11.2″ towards PA 356° (frame 1 → 6). Offsets are 0.5–2.9″, from a saturated core with wing centroids.
- **"Your sky now", Seattle:** Barnard's Star is "46° above your horizon, towards the south". Kapteyn's Star "never rises from here", which is correct: at Dec −45°, its highest point is about 2.6° below the Seattle horizon.
- **Sky context:** the SPHEREx 2.2 µm HiPS loads, with the flipbook's field-of-view square.
- **375 px:** the layout stacks, and there is no horizontal scroll (scroll width 375 = client width).

## Results against round 1

| Round-1 finding | Round 2 |
|---|---|
| R Dra saturated cores showed as black holes | Fixed: cores show as white, and frames are marked `saturated` |
| Duplicate frame labels (R Dra) | Fixed: date-range labels |
| WISE 0855 too faint in the all-detector stack | Fixed: the chip uses the D6 stack (`det=D6`). D6 photometry is 0.31 / 0.57 / 0.86 / 0.51 mJy. |
| WISE 0855 challenge coordinates are from 2010 | Fixed: the chip note says so, and the chip uses the 2026 position |
| D1/D2 scattered light | Open: kneha07/WANDERERS#5 |

## Known limits (open)

- RW Aur and R Dra are saturated, so the live tool has no brightness series for them. The panel says so and links to the WANDERERS matched-wavelength check. Decision: no flux estimate from the wings (#6).
- Barnard's Star shows 150 Gaia ghosts, which is busy, mostly at phone size. The ghosts fade with magnitude.
- Centroid pull from stars closer than 1 px, and the RGB colour shift when a channel has no images: kneha07/WANDERERS#21.
