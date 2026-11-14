// Tests for app/framemath.js (add and subtract sky frames). No browser needed.
// Run from the repository root:  node --test test/framemath.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const FM = require("../app/framemath.js");

const N = 60;
// A fake sky: 80 fixed "stars" of different brightness on a dark background, plus an optional moving dot.
const STARS = (() => {
  let s = 11; const r = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const seen = new Set(), out = [];
  while (out.length < 80) { const x = Math.floor(r() * N), y = Math.floor(r() * N); if (!seen.has(y * N + x)) { seen.add(y * N + x); out.push([x, y, 40 + r() * 160]); } }
  return out;
})();
function sky({ dotAt = null, gain = 1, offset = 0 } = {}) {
  const v = new Float32Array(N * N).fill(10);
  for (const [x, y, b] of STARS) v[y * N + x] = b;
  if (dotAt) v[dotAt[1] * N + dotAt[0]] = 220;
  return v.map((p) => Math.min(255, Math.max(0, p * gain + offset)));
}

test("luminance from RGBA", () => {
  const l = FM.lumFromRGBA(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255, 255, 0, 0, 255]));
  assert.ok(Math.abs(l[0] - 255) < 1e-3);
  assert.equal(l[1], 0);
  assert.ok(Math.abs(l[2] - 0.299 * 255) < 1e-3);
});

test("percentile", () => {
  assert.equal(FM.percentile([1, 2, 3, 4, 5], 50), 3);
  assert.equal(FM.percentile([1, 2, 3, 4, 5], 0), 1);
  assert.equal(FM.percentile([1, 2, 3, 4, 5], 100), 5);
  assert.equal(FM.percentile([NaN, 4], 50), 4);
  assert.equal(FM.percentile([], 50), 0);
});

test("add averages frames", () => {
  const out = FM.add([Float32Array.from([0, 10, 20]), Float32Array.from([10, 10, 40])]);
  assert.deepEqual(Array.from(out), [5, 10, 30]);
});

test("add rejects an empty set and mismatched sizes", () => {
  assert.throws(() => FM.add([]), /at least one/);
  assert.throws(() => FM.add([new Float32Array(3), new Float32Array(4)]), /same size/);
});

test("adding frames lowers random noise", () => {
  let seed = 3; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  const frames = Array.from({ length: 8 }, () => Float32Array.from({ length: 2000 }, () => 100 + rnd() * 20));
  const sd = (a) => { const m = a.reduce((s, x) => s + x, 0) / a.length; return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length); };
  assert.ok(sd(FM.add(frames)) < sd(frames[0]) / 2);
});

test("matchBrightness recovers gain and offset", () => {
  const a = sky(), b = sky({ gain: 0.5, offset: 20 });
  const { gain, offset } = FM.matchBrightness(a, b);
  assert.ok(Math.abs(gain - 0.5) < 0.01, `gain ${gain}`);
  assert.ok(Math.abs(offset - 20) < 1, `offset ${offset}`);
});

test("subtract cancels static stars even when frames differ in brightness", () => {
  const { diff } = FM.subtract(sky(), sky({ gain: 0.6, offset: 15 }));
  assert.ok(Math.max(...diff.map(Math.abs)) < 3, "static sky should cancel");
});

test("subtract shows a moving dot: positive where it is now, negative where it was", () => {
  const before = sky({ dotAt: [10, 20] }), after = sky({ dotAt: [20, 22], gain: 0.8, offset: 5 });
  const { diff } = FM.subtract(before, after);
  const now = diff[22 * N + 20], was = diff[20 * N + 10];
  assert.ok(now > 80, `now ${now}`);
  assert.ok(was < -80, `was ${was}`);
  // and nothing else is large
  let big = 0; diff.forEach((d, i) => { if (Math.abs(d) > 40 && i !== 22 * N + 20 && i !== 20 * N + 10) big++; });
  assert.equal(big, 0);
});

test("subtract of identical frames is zero and does not divide by zero on flat frames", () => {
  const f = sky();
  assert.ok(FM.subtract(f, f).diff.every((d) => Math.abs(d) < 1e-3));
  const flat = new Float32Array(25).fill(7);
  const r = FM.subtract(flat, flat);
  assert.ok(Number.isFinite(r.gain) && r.diff.every(Number.isFinite));
});

test("autoScale has a floor so noise is not blown up", () => {
  assert.equal(FM.autoScale(new Float32Array(100).fill(0.2)), 6);
  assert.ok(FM.autoScale(Float32Array.from({ length: 1000 }, (_, i) => (i === 0 ? 200 : 1))) >= 6);
});

test("diffToRGBA colours: green for now, pink for before, grey for small", () => {
  const base = new Float32Array([100, 100, 100]), d = Float32Array.from([100, -100, 1]);
  const px = FM.diffToRGBA(d, base, 100);
  const [g, p, s] = [0, 1, 2].map((i) => px.slice(4 * i, 4 * i + 4));
  assert.ok(g[1] > g[0] && g[1] > 200, "positive is green");
  assert.ok(p[0] > p[1] && p[0] > 200, "negative is pink");
  assert.ok(Math.abs(s[0] - s[1]) < 1 && Math.abs(s[1] - s[2]) < 1, "small is grey");
  assert.ok([g, p, s].every((c) => c[3] === 255));
});

test("grayToRGBA", () => {
  assert.deepEqual(Array.from(FM.grayToRGBA(Float32Array.from([0, 128, 255]))), [0, 0, 0, 255, 128, 128, 128, 255, 255, 255, 255, 255]);
});

test("smooth keeps a flat frame flat, lowers noise, and radius 0 is a copy", () => {
  const flat = new Float32Array(25).fill(9);
  assert.ok(FM.smooth(flat, 5, 5, 1).every((x) => Math.abs(x - 9) < 1e-4));
  let seed = 5; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  const noisy = Float32Array.from({ length: 40 * 40 }, () => 100 + rnd() * 40);
  const sd = (a) => { const m = a.reduce((s, x) => s + x, 0) / a.length; return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length); };
  assert.ok(sd(FM.smooth(noisy, 40, 40, 1)) < sd(noisy) / 2);
  const copy = FM.smooth(noisy, 40, 40, 0);
  assert.deepEqual(Array.from(copy), Array.from(noisy));
  assert.notEqual(copy, noisy);
  assert.throws(() => FM.smooth(new Float32Array(10), 3, 3, 1), /Size/);
});

test("diffToRGBA threshold hides faint differences", () => {
  const base = new Float32Array([100, 100]), d = Float32Array.from([50, 90]);
  const lo = FM.diffToRGBA(d, base, 100, 0.25), hi = FM.diffToRGBA(d, base, 100, 0.7);
  const grey = (px, i) => Math.abs(px[4 * i] - px[4 * i + 1]) < 1 && Math.abs(px[4 * i + 1] - px[4 * i + 2]) < 1;
  assert.ok(!grey(lo, 0) && !grey(lo, 1), "both coloured at a low threshold");
  assert.ok(grey(hi, 0) && !grey(hi, 1), "only the strong one coloured at a high threshold");
});

// Real data: WISE 0855 moves about 8"/yr. Subtracting WISE 2010 from SPHEREx 2026 should put a strong
// positive signal where the pipeline measured it in 2026 and a negative one where it was in 2010.
const fs = require("node:fs"), path = require("node:path");
const dataDir = path.join(__dirname, "..", "app", "data", "wise0855");
test("real data: WISE 0855 mover shows up in the difference", { skip: !fs.existsSync(path.join(dataDir, "target.json")) && "data not present" }, () => {
  const { readPng } = require("./png.js");
  const t = JSON.parse(fs.readFileSync(path.join(dataDir, "target.json"), "utf8"));
  const track = t.track.filter((p) => (p.ch || "w2") === "w2").sort((a, b) => a.year - b.year);
  const a = readPng(path.join(dataDir, "w2_wise2010.png")), b = readPng(path.join(dataDir, "w2_spherex_v3.png"));
  const { width: w, height: h } = a;
  const { diff } = FM.subtract(FM.smooth(a.lum, w, h, 1), FM.smooth(b.lum, w, h, 1));
  const scale = FM.autoScale(diff);
  const near = (p, pick) => { // PNG rows run top to bottom; pipeline y runs bottom to top
    let v = null;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
      const q = diff[(h - 1 - (Math.round(p.y) + dy)) * w + Math.round(p.x) + dx];
      v = v === null ? q : pick(v, q);
    }
    return v;
  };
  const now = near(track[track.length - 1], Math.max), was = near(track[0], Math.min);
  assert.ok(now > 0.7 * scale, `now ${now.toFixed(0)} vs scale ${scale.toFixed(0)}`);
  assert.ok(was < 0, `was ${was.toFixed(0)}`);
});

test("sparse sky with one moving star: the old position still shows as negative", () => {
  const n = 50, a = new Float32Array(n * n), b = new Float32Array(n * n);
  a[10 * n + 10] = 200;      // the star in the earlier frame
  b[40 * n + 35] = 150;      // the same star, moved, a bit fainter
  const { diff, gain } = FM.subtract(a, b);
  assert.ok(gain >= 0.3 && gain <= 3, `gain ${gain}`);
  assert.ok(diff[10 * n + 10] < -100, "old position is negative");
  assert.ok(diff[40 * n + 35] > 100, "new position is positive");
});

test("real data: Barnard's Star shows both its old and new position", { skip: !fs.existsSync(path.join(__dirname, "..", "app", "data", "barnard", "target.json")) && "data not present" }, () => {
  const { readPng } = require("./png.js");
  const dir = path.join(__dirname, "..", "app", "data", "barnard");
  const t = JSON.parse(fs.readFileSync(path.join(dir, "target.json"), "utf8"));
  const track = t.track.filter((p) => (p.ch || "w2") === "w2").sort((x, y) => x.year - y.year);
  const a = readPng(path.join(dir, "w2_wise2010.png")), b = readPng(path.join(dir, "w2_spherex_v2.png"));
  const { diff } = FM.subtract(a.lum, b.lum);
  const { width: w, height: h } = a, at = (p) => diff[(h - 1 - Math.round(p.y)) * w + Math.round(p.x)];
  assert.ok(at(track[0]) < -40, `2010 position ${at(track[0]).toFixed(0)}`);
  assert.ok(at(track[track.length - 1]) > 40, `2026 position ${at(track[track.length - 1]).toFixed(0)}`);
});
