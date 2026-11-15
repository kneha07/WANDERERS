// Tests for app/starquake.js (starquake model and synthesis) and app/data/starquake_stars.json.
// Run from the repository root:  node --test test/starquake.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const Q = require("../app/starquake.js");
const INFO = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app", "data", "starquake_stars.json"), "utf8"));
const STARS = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app", "data", "stars", "index.json"), "utf8")).stars;
const row = (name) => STARS.find((s) => s.name === name);

test("the Sun comes out of the scaling relations, and 3 mHz x 42,000 = 126 Hz", () => {
  assert.equal(Q.numaxOf(1, 1, 5777), 3090);
  assert.equal(Q.dnuOf(1, 1), 135.1);
  assert.ok(Math.abs(3e-3 * Q.SPEEDUP - 126) < 1e-9);
  assert.ok(Math.abs(Q.gammaOf(5777) - 1) < 1e-12);
  // the Sun's beats: 135 uHz spacing -> about 5.7 Hz
  assert.ok(Math.abs(135.1e-6 * Q.SPEEDUP - 5.67) < 0.01);
});

test("mode pattern: l=0 modes are dnu apart, l=2 sits just below l=0, envelope peaks at nu_max", () => {
  const ms = Q.modes({ numax: 3090, dnu: 135.1, gamma: 1 });
  const l0 = ms.filter((m) => m.l === 0).map((m) => m.nu);
  for (let i = 1; i < l0.length; i++) assert.ok(Math.abs(l0[i] - l0[i - 1] - 135.1) < 1e-9);
  const top = ms.filter((m) => m.l === 0).reduce((a, b) => (a.height > b.height ? a : b));
  assert.ok(Math.abs(top.nu - 3090) < 135.1 / 2);
  const n = top.n, l2 = ms.find((m) => m.l === 2 && m.n === n - 1);
  assert.ok(top.nu - l2.nu > 0 && top.nu - l2.nu < 12, "small separation of a few uHz (Sun: ~9)");
});

const powerNear = (sp, f0, halfWidth) => { let s = 0; for (let k = 0; k < sp.freq.length; k++) if (Math.abs(sp.freq[k] - f0) <= halfWidth) s += sp.power[k]; return s; };

test("the sound has energy only at the mode frequencies, not between them (tonal, not noise)", () => {
  const ms = Q.modes({ numax: 3090, dnu: 135.1, gamma: 1 });
  const s = Q.synth(ms, { seed: 5 }), sp = Q.spectrum(s.samples, s.fs);
  let tot = 0; for (let k = 1; k < sp.power.length; k++) tot += sp.power[k];
  let near = 0;
  for (let k = 1; k < sp.freq.length; k++) if (ms.some((m) => Math.abs(sp.freq[k] - m.nu * 1e-6 * Q.SPEEDUP) < 0.5)) near += sp.power[k];
  assert.ok(near / tot > 0.97, `${(near / tot).toFixed(3)} of the energy within 0.5 Hz of a mode`);
  // power density half-way between l=0 and l=1 modes near the peak is far below that at the modes
  const a = ms.find((m) => m.l === 0 && Math.abs(m.nu - 3090) < 70), b = ms.find((m) => m.l === 1 && m.n === a.n);
  const mid = (a.nu + b.nu) / 2 * 1e-6 * Q.SPEEDUP;
  // Real modes are Lorentzian lines, so a little power sits in their tails: expected ~5e-3 of a mode's power in the
  // same window half-way between neighbours (white noise would give ~1). Require at least 50x weaker.
  assert.ok(powerNear(sp, mid, 0.3) < 2e-2 * powerNear(sp, a.nu * 1e-6 * Q.SPEEDUP, 0.3));
});

test("the Sun's hum is centred near 126 Hz", () => {
  const s = Q.synth(Q.modes({ numax: 3090, dnu: 135.1, gamma: 1 }), { seed: 2 }), sp = Q.spectrum(s.samples, s.fs);
  let w = 0, fw = 0; for (let k = 0; k < sp.freq.length; k++) { w += sp.power[k]; fw += sp.power[k] * sp.freq[k]; }
  assert.ok(Math.abs(fw / w - 126) < 10, `centroid ${(fw / w).toFixed(1)} Hz`);
});

test("a wider line (larger Gamma) means a shorter-lived mode: its power spreads over more frequencies", () => {
  const one = (gamma) => {
    let frac = 0;
    for (const seed of [1, 2, 3, 4]) {
      const s = Q.synth([{ n: 0, l: 0, nu: 3000, height: 1, gamma }], { seed, log2n: 18 }), sp = Q.spectrum(s.samples, s.fs);
      let tot = 0; for (const p of sp.power) tot += p;
      frac += powerNear(sp, 126, 0.05) / tot / 4;
    }
    return frac;
  };
  assert.ok(one(0.3) > 1.5 * one(5), "narrow line keeps more power close to the mode");
});

test("the same seed gives the same sound; a different seed gives a different one", () => {
  const ms = Q.modes({ numax: 3090, dnu: 135.1, gamma: 1 });
  const a = Q.synth(ms, { seed: 9, log2n: 16 }).samples, b = Q.synth(ms, { seed: 9, log2n: 16 }).samples, c = Q.synth(ms, { seed: 10, log2n: 16 }).samples;
  assert.deepEqual(a, b);
  assert.notDeepEqual(a, c);
  assert.ok(Math.max(...a.map(Math.abs)) <= 0.85 + 1e-6, "normalised, no clipping");
  assert.equal(a[0], 0, "fades in from silence");
});

test("speed-up: 42,000x for audible stars; a labelled extra factor only when it would be inaudible", () => {
  assert.deepEqual(Q.speedupFor(3090).extra, 1);
  assert.equal(Q.speedupFor(1000).extra, 1, "Procyon-like stars stay at 42,000x");
  const rg = Q.speedupFor(50);                         // red giant
  assert.ok(rg.extra > 1 && rg.hz >= 30);
});

test("every star is labelled measured, published, predicted or none; hot stars get no sound", () => {
  assert.equal(Q.describe(INFO.sun, null).kind, "published");
  assert.equal(Q.describe(INFO.kic6106415, null).kind, "measured");
  assert.equal(Q.describe(INFO.hip87937, row("Barnard's Star")).kind, "predicted");
  assert.match(Q.describe(INFO.hip87937, row("Barnard's Star")).note, /never|none has been detected|prediction/i);
  const vega = Q.describe(null, row("Vega"));
  assert.equal(vega.kind, "none"); assert.match(vega.why, /convection/);
  assert.equal(Q.describe(null, row("Sirius")).kind, "none");
  assert.equal(Q.describe(INFO.wanderers_eps_indi_b, null).kind, "predicted");
  assert.equal(Q.describe(null, { name: "x", mag: 5 }).kind, "none", "unknown distance/temperature");
});

test("estimates from the catalogue are in the right range for well-known stars", () => {
  const ac = Q.describe(null, row("Rigil Kentaurus"));       // measured nu_max ~2300 uHz
  assert.ok(ac.numax > 1200 && ac.numax < 3500, String(ac.numax));
  const arc = Q.describe(null, row("Arcturus"));               // red giant, measured nu_max ~3.5 uHz
  assert.ok(arc.numax > 1 && arc.numax < 20, String(arc.numax));
  assert.ok(Q.teffFromBV(0.656) > 5700 && Q.teffFromBV(0.656) < 5800);
  assert.ok(Q.isGiant("K1.5IIIFe-0.5") && !Q.isGiant("G2V") && !Q.isGiant("F5IV-V"));
});

test("starquake_stars.json: every entry has a reference and sane values", () => {
  for (const [k, v] of Object.entries(INFO)) {
    if (k.startsWith("_")) continue;
    assert.ok(v.name, k);
    if (v.numax) { assert.ok(v.numax > 0 && v.dnu > 0, k); assert.ok(v.ref, `${k} needs a reference`); }
    if (v.M) assert.ok(v.params_ref || v.ref, `${k} needs a source for M, R, Teff`);
    if (v.recording) assert.ok(fs.existsSync(path.join(__dirname, "..", "app", v.recording)), `${k} recording exists`);
    if (v.published_dnu && v.dnu) assert.ok(Math.abs(v.dnu / v.published_dnu - 1) < 0.02, `${k}: measured dnu matches published`);
  }
});

test("WAV encoding: valid 16-bit mono header", () => {
  const buf = Q.wav(new Float32Array([0, 0.5, -0.5, 1]), 8000), v = new DataView(buf);
  assert.equal(String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3)), "RIFF");
  assert.equal(v.getUint32(24, true), 8000); assert.equal(v.getUint16(34, true), 16); assert.equal(buf.byteLength, 44 + 8);
  assert.equal(v.getInt16(44 + 2 * 3, true), 32767);
});

test("withProfile: measured radius/temperature replace catalogue guesses; literature and published values win", () => {
  const prof = { properties: { radius: { value: 0.162, source: "Gaia DR3 FLAME" }, teff: { value: 2829, source: "Gaia DR3 GSP-Phot" } } };
  const m = Q.withProfile(null, prof);
  assert.equal(m.R, 0.162); assert.equal(m.teff, 2829);
  assert.ok(Math.abs(m.M - Math.pow(0.162, 1.25)) < 1e-12); assert.match(m.params_ref, /mass–radius/);
  assert.equal(Q.withProfile(INFO.hip87937, prof), INFO.hip87937, "literature M and R win");
  assert.equal(Q.withProfile(INFO.sun, prof), INFO.sun, "published nu_max wins");
  assert.equal(Q.withProfile(null, { properties: { radius: { value: 25 }, teff: { value: 4300 } } }), null, "giants keep the catalogue estimate");
  // Proxima with its Gaia radius sounds like the other red dwarfs, not kilohertz-high
  const d = Q.describe(m, null);
  assert.ok(Q.speedupFor(d.numax).hz > 300 && Q.speedupFor(d.numax).hz < 1500, String(Q.speedupFor(d.numax).hz));
});
