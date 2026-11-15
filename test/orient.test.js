// Sky Compass orientation engine (app/orient.js): edge cases of the sensor input.
// The full noisy-sensor simulation is tests/orient.sim.js.  node --test test/orient.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const O = require("../app/orient.js");

const D2R = Math.PI / 180;
const vec = (az, alt) => [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
// Euler angles of a phone whose back camera points at az/alt (screen upright, no roll)
function euler(az, alt) {
  const f = vec(az, alt), n = Math.hypot(-f[2] * f[0], -f[2] * f[1], 1 - f[2] * f[2]);
  const up = [-f[2] * f[0] / n, -f[2] * f[1] / n, (1 - f[2] * f[2]) / n], x = cross(f, up);
  return O.eulerFromMat([[x[0], up[0], -f[0]], [x[1], up[1], -f[1]], [x[2], up[2], -f[2]]]);
}
const GYRO_OFFSET = 137;   // the gyro frame's arbitrary north
// Android: a relative (gyro) event and an absolute (compass) event per tick
function android(F, az, alt, ticks, { from = 0, absFirst = false, absAlpha } = {}) {
  const e = euler(az, alt);
  for (let i = from; i < from + ticks; i++) {
    const t = i * 16, rel = { alpha: O.wrap360(e.alpha + GYRO_OFFSET), beta: e.beta, gamma: e.gamma, t };
    const abs = { alpha: absAlpha ? absAlpha(i, e.alpha) : e.alpha, beta: e.beta, gamma: e.gamma, absolute: true, t };
    for (const ev of absFirst ? [abs, rel] : [rel, abs]) F.feed(ev);
  }
}
const azErr = (F, az) => Math.abs(O.wrap180(F.pointing().az - az));

test("Android: north is right whichever stream's first event arrives first", () => {
  for (const absFirst of [false, true]) {
    const F = new O.Fusion();
    android(F, 120, 30, 300, { absFirst });
    assert.ok(azErr(F, 120) < 0.5, `absFirst=${absFirst}: az ${F.pointing().az.toFixed(1)}`);
    assert.ok(Math.abs(F.pointing().alt - 30) < 0.5);
  }
});

test("a NaN tilt in one event does not break the pointing for good", () => {
  const F = new O.Fusion(), e = euler(200, 20);
  const ios = (i, over = {}) => F.feed({ alpha: e.alpha, beta: e.beta, gamma: e.gamma, webkitCompassHeading: 200, t: i * 16, ...over });
  for (let i = 0; i < 100; i++) ios(i);
  ios(100, { beta: NaN });
  ios(101, { gamma: NaN });
  for (let i = 102; i < 300; i++) ios(i);
  const p = F.pointing();
  assert.ok(Number.isFinite(p.az) && Number.isFinite(p.alt), `az ${p.az}, alt ${p.alt}`);
  assert.ok(azErr(F, 200) < 1 && Math.abs(p.alt - 20) < 1);
});

test("an absolute event without a compass angle (alpha null) does not set north", () => {
  const F = new O.Fusion();
  android(F, 120, 30, 300, { absAlpha: (i, a) => (i === 0 ? null : a) });
  assert.ok(azErr(F, 120) < 0.5, `az ${F.pointing().az.toFixed(1)}`);
});

test("fine-tune across north (0/360) and clearing it", () => {
  const F = new O.Fusion();
  android(F, 2, 40, 200);
  const before = F.pointing().az;
  const r = F.fineTune(355, null);            // the true object is 7 deg to the left, across north
  assert.ok(Math.abs(r.dAz + 7) < 0.5, `dAz ${r.dAz}`);
  assert.equal(F.compassFrozen, true);
  android(F, 2, 40, 200, { from: 200 });
  assert.ok(azErr(F, 355) < 0.5, `after fine-tune az ${F.pointing().az.toFixed(2)}`);
  F.clearFineTune();
  assert.equal(F.compassFrozen, false);
  android(F, 2, 40, 200, { from: 400 });
  assert.ok(Math.abs(O.wrap180(F.pointing().az - before)) < 0.5);
});
