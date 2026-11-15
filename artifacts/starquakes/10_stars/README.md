# Ten stars' starquakes

Smallest and densest (highest pitch) to largest. Each star's internal sound waves are sped up **42,000×**, the speed-up
Stanford's SoSH project used for the Sun, so pitch compares fairly. Arcturus is a red giant: at 42,000× it would sit
below hearing, so it gets one extra, stated speed-up. Each file is 16 s at 8 kHz. Use headphones for the low ones.

Made by `node scripts/starquake_ten.js` (model: `app/starquake.js`; recordings: `pipeline/starquake.py`).

| # | File | Star | How we know | ν_max (µHz) | Δν (µHz) | Hum | Beats |
|---|---|---|---|---|---|---|---|
| 1 | `01_barnards_star.wav` | Barnard's Star | **Predicted** | 15,376 | 591 | 646 Hz | 24.8 Hz |
| 2 | `02_61_cygni_a.wav` | 61 Cygni A | **Predicted** | 6,027 | 231 | 253 Hz | 9.7 Hz |
| 3 | `03_tau_ceti.wav` | Tau Ceti | **Predicted** | 4,418 | 181 | 186 Hz | 7.6 Hz |
| 4 | `04_alpha_centauri_b.wav` | Alpha Centauri B | **Published** | 4,000 | 161 | 168 Hz | 6.8 Hz |
| 5 | `05_kic_8006161.wav` | KIC 8006161 | **Measured** | 3,386 | 149 | 142 Hz | 6.3 Hz |
| 6 | `06_the_sun.wav` | The Sun | **Published** | 3,090 | 135 | 130 Hz | 5.7 Hz |
| 7 | `07_alpha_centauri_a.wav` | Alpha Centauri A | **Published** | 2,300 | 106 | 96.6 Hz | 4.4 Hz |
| 8 | `08_kic_6106415.wav` | KIC 6106415 | **Measured** | 2,248 | 104 | 94.4 Hz | 4.4 Hz |
| 9 | `09_procyon.wav` | Procyon | **Published** | 1,000 | 55.5 | 42.0 Hz | 2.3 Hz |
| 10 | `10_arcturus.wav` | Arcturus | **Predicted** | 5.95 | 1.04 | 50.0 Hz (×200 more) | 8.7 Hz |

- **Measured**: a real recording, made from Kepler photometry. The measured mode spacing matches Lund et al. 2017 to within 0.5%.
- **Published**: ν_max and Δν measured by astronomers; the mode pattern comes from theory.
  - Alpha Centauri B: Kjeldsen et al. 2005, ApJ 635, 1281
  - The Sun: Solar reference values: Kjeldsen & Bedding 1995, A&A 293, 87; Huber et al. 2011, ApJ 743, 143
  - Alpha Centauri A: Bedding et al. 2004, ApJ 614, 380 (ground-based radial velocities)
  - Procyon: Bedding et al. 2010, ApJ 713, 935
- **Predicted**: size, mass and temperature estimated from the star catalogue, then the asteroseismic scaling relations. Expect errors of tens of percent.
  - Barnard's Star: Predicted: approximate, Ribas et al. 2018, Nature 563, 365. Red dwarfs are predicted to have tiny, very fast starquakes, but none has been detected yet: this is a prediction.
  - 61 Cygni A: Predicted: estimated from the catalogue (V, distance, B−V colour); mass from the mass–luminosity relation.
  - Tau Ceti: Predicted: estimated from the catalogue (V, distance, B−V colour); mass from the mass–luminosity relation.
  - Arcturus: Predicted: estimated from the catalogue (V, distance, B−V colour); giant mass assumed 1.3 M☉.
