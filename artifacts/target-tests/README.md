# Challenge target tests, 2026-11-14 (round 1)

Tester: the orchestrator, through the live local API (`GET /api/frames?q=...`, default FOV 5', `per_group=12`).
Each contact sheet shows the stacked frames scaled 6x and the amber "where to look" ring. The last tile is the difference image (last survey minus first survey).

| Target | Query | Frames | Images (failed) | Cold call | Result |
|---|---|---|---|---|---|
| Barnard's Star | `Barnard's Star` | 6 | 56 (0) | cached | PASS. The star moves north about 1.8 px. The ring follows it. The difference image shows a bright/dark pair. One frame has a black core pixel (saturation). |
| Epsilon Indi B | `eps Ind B` | 5 | 60 (0) | 25.8 s | PASS. The pair shows on the east side (left), which matches the proper motion. Some hot pixels remain. |
| WISE 0855 | `WISE J085510.83-071442.5` | 4 | 48 (0) | cached | WEAK. The source is at the detection limit in the stack and in D6 (only 2 images per detector per survey). Fix: a D6-only stack. |
| WISE 0855 | `08h55m10.831s -07d14m42.53s` | 4 | 48 (0) | cached | As expected. These are 2010 coordinates, so the object is about 20 px west of center, and there is no ring (no proper motion). |
| RW Aurigae | `RW Aur` | 3 | 36 (0) | cached | PASS. The brightness changes between surveys. The difference image shows a dark blob (fainter later). |
| R Draconis | `R Dra` | 9 | 108 (0) | cached | FAIL (display). Saturated cores show as black holes, and the difference image is wrong at the star. Two frames have the same label, "2025-07 survey". |

## Findings sent to the implementer

1. HIGH: saturated cores show as black holes (R Dra, Barnard 2025-09). Show them as white, mark the frame `saturated`, and keep them out of the difference image.
2. MEDIUM: duplicate frame labels (R Dra). Use the mean-epoch date.
3. MEDIUM: WISE 0855 is too faint in the all-detector stack. Add a `det=D6` long-wavelength stack, and use it as the default for the WISE chip.
4. LOW: the WISE chip note must say that the challenge coordinates are from 2010.
5. LOW (not sent): D1/D2 frames show scattered-light gradients that the plane background fit does not remove.
