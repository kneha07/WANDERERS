## What

The Sky Compass drawn stars now take position, V magnitude and spectral type from the **Hipparcos table at NASA HEASARC**. HYG v4.1 stays for names, HIP keys, distances and constellations, so taps still open the same Star database record.

```
NASA HEASARC hipparcos (J1991.25 + proper motion → J2000)   HYG v4.1
  position, V mag, spectral letter                            names, keys, distances
                      └──────── join on HIP ────────┘
                                   ▼
                     app/data/skystars.json (V <= 6.5)
```

## Evidence

- Same 8,920 stars. 8,870 come from HEASARC; 50 have no Hipparcos row and keep HYG values.
- 0 stars change magnitude or colour. Position shift: median 0″, worst 16″ (Alpha Cen), under 1 px at 10× zoom.
- `node --test test/*.test.js`: 664 pass, 0 fail.
- Compass in the browser loads the new file with no console errors. The info panel credit reads "Stars: Hipparcos (ESA) via NASA HEASARC".

Full record: `artifacts/nasa-stars/verify.md`.

## Notes

- HEASARC TAP gives only binary VOTable, so the pipeline uses the xamin `format=text` query. The script stops if the answer is cut short.
- `test/skyview.test.js` now measures the angle on the sky (0.01°) instead of raw RA/Dec (0.001°).
- Not run: `test/browser/realsky.mjs` (Deep photo registration). CI runs it.

Closes #90

🤖 Generated with [Claude Code](https://claude.com/claude-code)
