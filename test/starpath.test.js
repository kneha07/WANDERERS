// Tests for app/starpath.js (predicted star path helpers).
// Run from the repository root:  node --test test/starpath.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const SP = require("../app/starpath.js");

const P = [[2010, 0, 0], [2011, 10, 20], [2012, 20, 20]];

test("at() interpolates between samples and is exact on them", () => {
  assert.deepEqual(SP.at(P, 2010), { x: 0, y: 0 });
  assert.deepEqual(SP.at(P, 2011.5), { x: 15, y: 20 });
  assert.deepEqual(SP.at(P, 2012), { x: 20, y: 20 });
});

test("at() is null outside the path or for bad input", () => {
  for (const y of [2009.9, 2012.1, NaN, undefined]) assert.equal(SP.at(P, y), null);
  assert.equal(SP.at([], 2010), null);
  assert.equal(SP.at(null, 2010), null);
});

test("between() clips to the path and adds exact end points", () => {
  assert.deepEqual(SP.between(P, 2010.5, 2011.5), [{ x: 5, y: 10 }, { x: 10, y: 20 }, { x: 15, y: 20 }]);
  assert.equal(SP.between(P, 2005, 2030).length, 3);
  assert.deepEqual(SP.between(P, 2020, 2030), []);
  assert.deepEqual(SP.between(P, 2011.5, 2010.5), SP.between(P, 2010.5, 2011.5));
});

test("summary() states rate, parallax, agreement and a forecast", () => {
  const s = SP.summary({ reference: { source: "Gaia DR3" }, proper_motion_arcsec_per_yr: 10.39, parallax_loop_arcsec: 0.55,
    summary: { n_measured: 6, rms_arcsec: 0.86 }, forecast: [{ year: 2027, ra: 1, dec: 2, in_field: true }, { year: 2030, ra: 269.4454, dec: 4.77965, in_field: false }] });
  assert.match(s, /Gaia DR3: 10\.39″\/yr plus a yearly parallax loop of ±0\.55″/);
  assert.match(s, /6 measured positions to 0\.86″ rms/);
  assert.match(s, /In 2030 .*RA 269\.44540°, Dec \+4\.77965°, outside this field\./);
  assert.equal(SP.summary(null), "");
});

test("summary() leaves out a parallax too small to matter", () => {
  const s = SP.summary({ reference: { source: "Gaia DR3" }, proper_motion_arcsec_per_yr: 0.02, parallax_loop_arcsec: 0.001, summary: {}, forecast: [] });
  assert.equal(s, "Predicted from Gaia DR3: 0.02″/yr.");
});

// Every committed trajectory.json must be readable by the page and line up with its target's frames.
const DATA = path.join(__dirname, "..", "app", "data");
for (const id of fs.readdirSync(DATA).filter((d) => fs.existsSync(path.join(DATA, d, "trajectory.json")))) {
  test(`committed trajectory: ${id}`, () => {
    const tr = JSON.parse(fs.readFileSync(path.join(DATA, id, "trajectory.json"), "utf8"));
    const t = JSON.parse(fs.readFileSync(path.join(DATA, id, "target.json"), "utf8"));
    assert.equal(tr.id, id);
    const p = tr.path.with_parallax;
    for (const ch of Object.keys(t.frames)) for (const f of t.frames[ch]) assert.ok(SP.at(p, f.year), `${id} ${f.png} inside path`);
    // analyze.py's proper-motion-only prediction for each measured position sits on our proper-motion-only path
    for (const m of t.track) {
      const q = SP.at(tr.path.proper_motion_only, m.year);
      assert.ok(Math.hypot(q.x - m.pred_x, q.y - m.pred_y) < 0.05, `${id} ${m.year}`);
    }
    assert.ok(SP.summary(tr).length > 20);
  });
}
