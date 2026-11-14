/* Simulated-sensor test of the Sky Compass orientation engine.
 *   node tests/orient.sim.js
 * A known "true" pointing path is turned into realistic phone sensor streams (gyro drift, compass noise,
 * accelerometer tilt bias, magnetic declination, indoor magnetic distortion, Android compass spikes), then fed
 * to (a) the OLD engine (compass-driven, as shipped before) and (b) the NEW fusion engine (app/orient.js).
 * Reports pointing error and jitter while holding still, and error while panning. Exits non-zero if the new
 * engine misses its targets. Deterministic (seeded random numbers). */
const O = require("../app/orient.js");
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

let seed = 12345;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
const gauss = (s) => { const u = Math.max(1e-12, rnd()), v = rnd(); return s * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };

// ---------- geometry helpers ----------
const vec = (az, alt) => [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (v) => { const n = Math.hypot(...v); return v.map((x) => x / n); };
function poseMatrix(az, alt, roll) {         // device->earth for a camera pointing at az/alt with roll
  const f = vec(az, alt);
  let up = [0, 0, 1].map((z, i) => z - f[2] * f[i]);
  up = Math.hypot(...up) < 1e-6 ? [Math.sin(az * D2R), Math.cos(az * D2R), 0] : norm(up);
  const r0 = cross(f, up);
  const c = Math.cos(roll * D2R), s = Math.sin(roll * D2R);
  const u = norm(up.map((x, i) => x * c - r0[i] * s)), x = cross(f, u), z = f.map((q) => -q);
  return [[x[0], u[0], z[0]], [x[1], u[1], z[1]], [x[2], u[2], z[2]]];
}
// quaternion slerp between rotation matrices (for smooth "pick up the phone" transitions)
function quat(R) {
  const t = R[0][0] + R[1][1] + R[2][2];
  let q;
  if (t > 0) { const s = Math.sqrt(t + 1) * 2; q = [0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s, (R[1][0] - R[0][1]) / s]; }
  else if (R[0][0] > R[1][1] && R[0][0] > R[2][2]) { const s = Math.sqrt(1 + R[0][0] - R[1][1] - R[2][2]) * 2; q = [(R[2][1] - R[1][2]) / s, 0.25 * s, (R[0][1] + R[1][0]) / s, (R[0][2] + R[2][0]) / s]; }
  else if (R[1][1] > R[2][2]) { const s = Math.sqrt(1 + R[1][1] - R[0][0] - R[2][2]) * 2; q = [(R[0][2] - R[2][0]) / s, (R[0][1] + R[1][0]) / s, 0.25 * s, (R[1][2] + R[2][1]) / s]; }
  else { const s = Math.sqrt(1 + R[2][2] - R[0][0] - R[1][1]) * 2; q = [(R[1][0] - R[0][1]) / s, (R[0][2] + R[2][0]) / s, (R[1][2] + R[2][1]) / s, 0.25 * s]; }
  return q;
}
function matFromQuat([w, x, y, z]) {
  return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
}
function slerp(A, B, k) {
  let a = quat(A), b = quat(B), d = a.reduce((s, x, i) => s + x * b[i], 0);
  if (d < 0) { b = b.map((x) => -x); d = -d; }
  if (d > 0.9995) return matFromQuat(norm(a.map((x, i) => x + (b[i] - x) * k)));
  const th = Math.acos(d), s = Math.sin(th);
  return matFromQuat(a.map((x, i) => (Math.sin((1 - k) * th) * x + Math.sin(k * th) * b[i]) / s));
}
const smooth = (k) => k * k * (3 - 2 * k);

// ---------- the true motion: 50 seconds at 60 Hz ----------
const TABLE_YAW = 30;
let TILT_SWEEP = false;
function truth(t) {
  if (TILT_SWEEP && t >= 7 && t < 20) {        // tilt the camera between 33 and 57 deg up, as in the recording
    return { R: poseMatrix(170, 45 + 12 * Math.sin(2 * Math.PI * (t - 7) / 4), 3), phase: "holdA" };
  }
  const flat = O.matFromEuler(TABLE_YAW, 0, 0);
  const A = poseMatrix(120, 40, 5), B = poseMatrix(300, 60, -8);
  const tremor = (R) => O.mul(R, O.matFromEuler(0.15 * Math.sin(2 * Math.PI * 0.8 * t), 0.15 * Math.sin(2 * Math.PI * 1.3 * t + 1),
                                                0.1 * Math.sin(2 * Math.PI * 1.6 * t + 2)));
  if (t < 4) return { R: flat, phase: "flat" };
  if (t < 7) return { R: slerp(flat, A, smooth((t - 4) / 3)), phase: "pickup" };
  if (t < 20) return { R: tremor(A), phase: "holdA" };
  if (t < 30) {   // pan across north and through the horizon (gimbal-lock zone for Euler angles)
    const k = smooth((t - 20) / 10);
    return { R: poseMatrix(120 + k * 180, 40 - 50 * Math.sin(Math.PI * k) + 20 * k, 5 - 13 * k), phase: "pan" };
  }
  return { R: tremor(B), phase: "holdB" };
}

// ---------- sensor models ----------
const DECL = 15;                          // magnetic declination (east)
const BIAS = O.matFromEuler(0, 1.2, -0.8); // accelerometer tilt bias, device frame
function sensors(R, t, sc) {
  const out = [];
  const Rm = O.mul(O.matFromEuler(DECL, 0, 0), R);          // magnetic frame: alpha_mag = alpha_true + decl
  const Rrel = O.mul(O.matFromEuler(137 + sc.gyroDrift * t, 0, 0), O.mul(R, BIAS));
  const er = O.eulerFromMat(Rrel);
  const relEvt = { alpha: er.alpha + gauss(0.05), beta: er.beta + gauss(0.05), gamma: er.gamma + gauss(0.05), t: t * 1000 };
  const disturb = sc.indoor ? 8 : 0;
  if (sc.platform === "ios") {
    const em = O.eulerFromMat(Rm);
    const f = [-Rm[0][2], -Rm[1][2], -Rm[2][2]];
    // iOS (confirmed by a real recording): heading follows the phone TOP when the top is within 45 deg of
    // horizontal, otherwise the CAMERA; so it flips 180 deg when the camera passes 45 deg up.
    const topElev = Math.asin(Rm[2][1]) * R2D, top = [Rm[0][1], Rm[1][1], Rm[2][1]];
    let heading = Math.abs(topElev) < 45 ? O.azAlt(top).az : O.azAlt(f).az;
    heading = O.wrap360(heading + disturb + gauss(sc.compassNoise));
    out.push({ ...relEvt, webkitCompassHeading: heading, webkitCompassAccuracy: sc.compassNoise * 2 });
  } else {
    out.push({ ...relEvt, absolute: false });
    const em = O.eulerFromMat(O.mul(Rm, BIAS));
    let spike = rnd() < sc.spikeRate ? 25 * (rnd() < 0.5 ? -1 : 1) : 0;
    out.push({ alpha: O.wrap360(em.alpha + disturb + gauss(sc.compassNoise) + spike), beta: em.beta + gauss(0.3), gamma: em.gamma + gauss(0.3), absolute: true, t: t * 1000 });
  }
  return out;
}

// ---------- OLD engine (what shipped before: compass drives everything, per-event low-pass) ----------
function oldEngine() {
  let az = null, alt = null;
  const cam = (a, b, g) => {
    const R = O.matFromEuler(a, b, g);
    return O.azAlt([-R[0][2], -R[1][2], -R[2][2]]);
  };
  return {
    feed(e) {
      let alpha;
      if (typeof e.webkitCompassHeading === "number") alpha = 360 - e.webkitCompassHeading;
      else if (e.absolute) alpha = e.alpha; else return;
      const c = cam(alpha, e.beta, e.gamma); c.az = O.wrap360(c.az + DECL);
      if (az == null) { az = c.az; alt = c.alt; return; }
      az = O.wrap360(az + O.wrap180(c.az - az) * 0.25); alt += (c.alt - alt) * 0.25;
    },
    pointing: () => (az == null ? null : { forward: [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)] }),
  };
}

// ---------- run ----------
function run(sc) {
  seed = sc.seed; TILT_SWEEP = !!sc.tiltSweep;
  const engines = { old: oldEngine(), neu: new O.Fusion() };
  engines.neu.decl = DECL;
  const stats = { old: {}, neu: {} };
  const add = (who, phase, err) => { (stats[who][phase] = stats[who][phase] || []).push(err); };
  let calResult = null, calDone = null;
  engines.neu.onCalibrated = (r) => { calResult = r; };
  for (let i = 0; i <= 50 * 60; i++) {
    const t = i / 60, tr = truth(t);
    if (i === 30 && !sc.skipCalibration) engines.neu.startFlatCalibration();
    if (sc.fineTuneAt && Math.abs(t - sc.fineTuneAt) < 1e-9) {
      const f = [-tr.R[0][2], -tr.R[1][2], -tr.R[2][2]], a = O.azAlt(f);
      calDone = engines.neu.fineTune(a.az, a.alt);    // user aims at a known landmark / star
    }
    for (const e of sensors(tr.R, t, sc)) { engines.old.feed(e); engines.neu.feed(e); }
    const fTrue = [-tr.R[0][2], -tr.R[1][2], -tr.R[2][2]];
    for (const who of ["old", "neu"]) {
      const p = engines[who].pointing();
      if (!p) continue;
      const settle = (tr.phase === "holdA" && t < 9) || (tr.phase === "holdB" && t < 32) || (sc.fineTuneAt && Math.abs(t - sc.fineTuneAt) < 1);
      const phase = tr.phase === "holdA" && sc.fineTuneAt && t > sc.fineTuneAt ? "holdA+" : tr.phase;
      if (tr.phase !== "flat" && tr.phase !== "pickup" && !settle) add(who, phase, { e: O.angle(p.forward, fTrue), f: p.forward, ft: fTrue });
    }
  }
  const summary = {};
  for (const who of ["old", "neu"]) {
    summary[who] = {};
    for (const [ph, list] of Object.entries(stats[who])) {
      const errs = list.map((x) => x.e);
      const mean = errs.reduce((s, x) => s + x, 0) / errs.length;
      // jitter: how much the pointer wobbles around its average error (degrees, RMS)
      const res = list.map((x) => { const a = O.azAlt(x.f), b = O.azAlt(x.ft);
        return [O.wrap180(a.az - b.az) * Math.cos(b.alt * D2R), a.alt - b.alt]; });
      const m0 = res.reduce((s, r) => s + r[0], 0) / res.length, m1 = res.reduce((s, r) => s + r[1], 0) / res.length;
      const jit = Math.sqrt(res.reduce((s, r) => s + (r[0] - m0) ** 2 + (r[1] - m1) ** 2, 0) / res.length);
      summary[who][ph] = { meanErr: mean, maxErr: Math.max(...errs), jitter: jit };
    }
  }
  return { summary, calResult, calDone };
}

// ---------- scenarios ----------
const scenarios = [
  { name: "iPhone, outdoors", platform: "ios", compassNoise: 4, gyroDrift: 0.03, indoor: false, seed: 1 },
  { name: "iPhone, indoors (metal nearby)", platform: "ios", compassNoise: 6, gyroDrift: 0.03, indoor: true, seed: 2 },
  { name: "iPhone, indoors + landmark fine-tune", platform: "ios", compassNoise: 6, gyroDrift: 0.03, indoor: true, fineTuneAt: 15, seed: 3 },
  { name: "iPhone, tilting across 45 deg (the recorded bug), calibrated", platform: "ios", compassNoise: 4, gyroDrift: 0.03, indoor: false, tiltSweep: true, seed: 7 },
  { name: "iPhone, tilting across 45 deg, NOT calibrated", platform: "ios", compassNoise: 4, gyroDrift: 0.03, indoor: false, tiltSweep: true, skipCalibration: true, seed: 8 },
  { name: "iPhone, user skips calibration", platform: "ios", compassNoise: 4, gyroDrift: 0.03, indoor: false, skipCalibration: true, seed: 6 },
  { name: "Android, outdoors", platform: "android", compassNoise: 3, gyroDrift: 0.01, indoor: false, spikeRate: 0, seed: 4 },
  { name: "Android, compass spikes", platform: "android", compassNoise: 3, gyroDrift: 0.01, indoor: false, spikeRate: 0.02, seed: 5 },
];

// unit checks first
let worst = 0;
for (let k = 0; k < 2000; k++) {
  const a = rnd() * 360, b = rnd() * 340 - 170, g = rnd() * 178 - 89;
  const R1 = O.matFromEuler(a, b, g), e = O.eulerFromMat(R1), R2 = O.matFromEuler(e.alpha, e.beta, e.gamma);
  worst = Math.max(worst, ...R1.flat().map((x, i) => Math.abs(x - R2.flat()[i])));
}
console.log(`Euler round-trip, 2000 random orientations: max matrix error ${worst.toExponential(1)} ${worst < 1e-9 ? "PASS" : "FAIL"}`);

let fail = worst >= 1e-9;
const fmt = (x) => x.toFixed(2).padStart(6);
for (const sc of scenarios) {
  const { summary, calResult } = run(sc);
  console.log(`\n${sc.name}  (calibration: ${calResult ? `${calResult.quality}, compass scatter ±${calResult.compassScatter?.toFixed(1)}°` : "none"})`);
  console.log("  phase    engine   mean err   max err   wobble (RMS)");
  for (const ph of ["holdA", "holdA+", "pan", "holdB"]) {
    for (const who of ["old", "neu"]) {
      const s = summary[who][ph];
      if (s) console.log(`  ${ph.padEnd(8)} ${who === "old" ? "OLD" : "NEW"}     ${fmt(s.meanErr)}°   ${fmt(s.maxErr)}°   ${fmt(s.jitter)}`);
    }
  }
  const n = summary.neu;
  // Targets: outdoors < 1.5 deg error; indoors the magnetic distortion can only be removed by a fine-tune,
  // so before it we only require < 10 deg; after a fine-tune < 1.5 deg. Wobble < 0.5 deg everywhere.
  const checks = sc.fineTuneAt ? [["holdA+", 1.5], ["holdB", 1.5]] : sc.indoor ? [["holdA", 10], ["holdB", 10]]
    : sc.skipCalibration ? [["holdA", 3], ["holdB", 3]] : [["holdA", 1.5], ["holdB", 1.5]];
  for (const [ph, okErr] of checks) {
    if (!(n[ph].meanErr < okErr && n[ph].jitter < 0.5)) { fail = true; console.log(`  -> FAIL: ${ph} error ${n[ph].meanErr.toFixed(2)}°, wobble ${n[ph].jitter.toFixed(2)}°`); }
  }
}
console.log(fail ? "\nRESULT: FAIL" : "\nRESULT: PASS");
process.exit(fail ? 1 : 0);
