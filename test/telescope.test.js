// "See it through Webb" frame lookups (app/telescope.js) against a brute-force scan of app/data/webb.json.
// node --test test/telescope.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = path.join(__dirname, "..", "app");
const fetchFile = async (u) => {
  const p = path.join(APP, String(u));
  return fs.existsSync(p) ? { ok: true, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) } : { ok: false, json: async () => ({}) };
};
const win = {};
new Function("window", "fetch", fs.readFileSync(path.join(APP, "telescope.js"), "utf8"))(win, fetchFile);
const W = win.Webb;

test("near() finds every Webb frame inside the circle, for big circles and circles over a pole", async () => {
  const DB = await W.load("data/");
  // the Sky Compass asks for 40 deg around the crosshair (gold squares) and 4.5 deg for the chip
  const centres = [[200, 60], [10, 40], [83, -5], [270, 70], [80, -69], [150, 2], [359.9, -45], [0.1, 85], [45, -88]];
  for (const rad of [40, 4.5]) for (const [ra, dec] of centres) {
    const got = new Set(W.near(ra, dec, rad, 1e9).map((p) => p.obs));
    const want = DB.p.filter((p) => W.sep(ra, dec, p.ra, p.dec) <= rad);
    const missed = want.filter((p) => !got.has(p.obs));
    assert.equal(missed.length, 0, `r=${rad} at ${ra},${dec}: missed ${missed.length} of ${want.length}, e.g. ${missed[0] && [missed[0].ra, missed[0].dec]}`);
    assert.equal(got.size, want.length);
  }
});

test("framesAt() matches a brute-force footprint test", async () => {
  const DB = await W.load("data/");
  for (const p of DB.p.filter((_, i) => i % 97 === 0)) {
    const brute = DB.p.filter((q) => W.sep(p.ra, p.dec, q.ra, q.dec) <= q.r * 1.01 && W.inside(q, p.ra, p.dec)).map((q) => q.obs).sort();
    assert.deepEqual(W.framesAt(p.ra, p.dec).map((q) => q.obs).sort(), brute, p.obs);
  }
});
