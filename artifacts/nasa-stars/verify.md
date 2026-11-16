# Sky Compass stars from NASA HEASARC: verify record

Issue: kneha07/WANDERERS#90. Branch: `feature/nasa-stars`. Date: 2026-11-15.

## Change

```
NASA HEASARC xamin query (table hipparcos, V <= 7)      app/data/stars/index.json (HYG v4.1)
  position J1991.25 + proper motion → J2000                names, HIP keys, distances, constellations
  V mag, spectral letter                                    (fallback for stars with no Hipparcos row)
                    └──────────── join on HIP ─────────────┘
                                     ▼
                     app/data/skystars.json (V <= 6.5)
```

- `pipeline/make_sky_stars.py`: new `hipparcos()` fetch. `stars()` overrides ra, dec, V mag and spectral letter from it.
- The HEASARC TAP endpoint gives only binary VOTable (`FORMAT=csv` is refused). The xamin `format=text` query is used instead.
- The script stops if the answer is cut short (`OVERFLOW` or under 15,000 rows).
- The script asserts that Sirius lands on its J2000 place, so the proper-motion step stays correct.
- Credits: `app/skyview.js` (compass info panel) and `app/explorer-learn.js`.

## Evidence

| Check | Result |
|---|---|
| Stars in skystars.json | 8,920 before, 8,920 after; the same keys |
| From HEASARC / HYG only | 8,870 / 50 |
| V mag or spectral letter changed | 0 stars |
| Position shift, median | 0″ |
| Position shift, worst | 16″ (Alpha Cen A/B, Epsilon Indi), 15″ (Beta Hydri); 5 stars over 10″ |
| `node --test test/*.test.js` | 664 pass, 0 fail |
| Compass in browser (port 8006) | loads 8,920 stars, no console errors, credit shows "Hipparcos (ESA) via NASA HEASARC" |

A 16″ shift is smaller than one screen pixel at 10× zoom (about 21″ per pixel).

## Test change

`test/skyview.test.js` "one for one" compared raw RA and Dec within 0.001°. It now measures the angle on the sky within 0.01°. Raw RA stretches near the poles: Beta Hydri at −77° moves 0.018° in RA for a 15″ shift.

## Not done

- `test/browser/realsky.mjs` (the Deep photo vs canvas registration check) was not run. It needs Edge through WSL.
- `app/app.js:48` Star database tab credit still says HYG v4.0. That tab still uses HYG, so it is unchanged.
