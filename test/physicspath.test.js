// Tests for app/physicspath.js (computed 1900-2100 paths for every star) and the bulk profiles behind it.
// Run from the repository root:  node --test test/physicspath.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const PP = require("../app/physicspath.js");
const SD = require("../app/stardb.js");
const C = require("../app/starcore.js");
const DATA = path.join(__dirname, "..", "app", "data");
const STARS = JSON.parse(fs.readFileSync(path.join(DATA, "stars", "index.json"), "utf8")).stars;
const shardOf = (key) => (/^hip\d+$/.test(key) ? String(parseInt(key.slice(3), 10) % 100) : "x");
const bulk = (key) => { const f = path.join(DATA, "stars", "profile_bulk", shardOf(key) + ".json"); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8"))[key] || null : null; };
const row = (k) => STARS.find((s) => s.key === k);

test("Barnard's Star: the computed path agrees with the independently learnt one within about a second of arc", () => {
  const learnt = JSON.parse(fs.readFileSync(path.join(DATA, "stars", "pred", "hip87937.json"), "utf8"));
  const p = PP.build(row("hip87937"), bulk("hip87937"), learnt.now);
  assert.equal(p.kind, "physics"); assert.match(p.basis, /^Gaia DR3/);
  for (const y of [1900, 2000, 2100]) {
    const a = p.path.rows.find((r) => r[0] === y), b = learnt.path.rows.find((r) => r[0] === y);
    const sep = C.separationArcsec({ ra: a[1], dec: a[2] }, { ra: b[1], dec: b[2] });
    assert.ok(sep < 1.5, `${y}: ${sep.toFixed(2)}"`);
  }
});

test("a computed path has the shape the chart, table and long-range views expect", () => {
  const p = PP.build(row("hip8102"), bulk("hip8102"));
  assert.equal(p.path.rows[0][0], 1900); assert.equal(p.path.rows[p.path.rows.length - 1][0], 2100);
  assert.equal(p.table.length, 6);
  const c = SD.chart(p);
  for (const q of c.past.concat(c.future)) assert.ok(q.every(Number.isFinite));
  const st = C.startState(p, row("hip8102"));
  assert.ok(st.star && st.star.plx > 200, "Tau Ceti is ~274 mas"); assert.match(st.sources.motion, /Gaia DR3/);
  assert.ok(p.path.rows.find((r) => r[0] === 2100)[5] > p.path.rows.find((r) => r[0] === 2016)[5], "uncertainty grows away from 2016");
});

test("without Gaia data the HYG catalogue is used, and stars with no distance get no path", () => {
  const p = PP.build({ key: "x", name: "X", ra: 10, dec: 20, pmra: 100, pmdec: -50, dist_pc: 10, rv: 0 }, null);
  assert.match(p.basis, /HYG/); assert.equal(p.rvKnown, false);
  assert.equal(PP.build({ key: "y", name: "Y", ra: 10, dec: 20, pmra: 100, pmdec: 0, dist_pc: null }, null), null);
});

test("every star in the database gets a path (except the few with no distance at all)", () => {
  let ok = 0, none = 0;
  for (const s of STARS) { if (PP.build(s, null)) ok++; else none++; }
  assert.ok(ok / STARS.length > 0.97, `${ok} of ${STARS.length} (${none} without a distance)`);
});

test("bulk profiles: summary is consistent and records carry sources", () => {
  const sum = JSON.parse(fs.readFileSync(path.join(DATA, "stars", "profile_bulk", "summary.json"), "utf8"));
  assert.equal(sum.stars, STARS.length);
  assert.ok(sum.with_measurements > 8000 && sum.with_gaia > 7000 && sum.with_abundances > 2500);
  const t = bulk("hip8102");
  assert.ok(t.bulk && t.chemistry.abundances.Fe.x_h < -0.3, "Tau Ceti metal-poor in the bulk data too");
  for (const v of Object.values(t.properties)) assert.ok(v.source);
});
