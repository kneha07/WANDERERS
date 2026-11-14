// Tests for app/starcore.js (long-range 3D star motion).
// Run from the repository root:  node --test test/starcore.test.js
// The reference values in test/fixtures/starcore_astropy.json come from astropy's SkyCoord.apply_space_motion.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const C = require("../app/starcore.js");
const FX = require("./fixtures/starcore_astropy.json");

for (const c of FX.cases) {
  test(`matches astropy over tens of thousands of years: ${c.star.name}`, () => {
    const today = C.propagate(c.star, 2026);
    for (const r of c.astropy) {
      const p = C.propagate(c.star, r.year);
      const travelled = C.separationArcsec(today, p);
      // astropy/ERFA also applies light-travel time; allow 1 part in 10,000 of the distance travelled
      assert.ok(C.separationArcsec(p, r) < 0.5 + 1e-4 * travelled, `${r.year}: ${C.separationArcsec(p, r).toFixed(2)}"`);
      assert.ok(Math.abs(p.distLy - r.dist_ly) < 0.01, `${r.year}: distance`);
    }
  });
}

test("zero time gives the input back, including the motion", () => {
  const s = FX.cases[0].star, p = C.propagate(s, s.epoch);
  assert.ok(Math.abs(p.ra - s.ra) < 1e-9 && Math.abs(p.dec - s.dec) < 1e-9);
  assert.ok(Math.abs(p.pmdec - s.pmdec) < 1e-6 && Math.abs(p.rv - s.rv) < 1e-9 && Math.abs(p.plx - s.plx) < 1e-9);
});

test("Barnard's Star: closest approach about 11,800 CE at about 3.8 light-years, and it speeds up on the way", () => {
  const s = FX.cases[0].star, ca = C.closestApproach(s);
  assert.ok(ca.year > 11500 && ca.year < 12000, String(ca.year));
  assert.ok(ca.distLy > 3.6 && ca.distLy < 3.9, String(ca.distLy));
  const mu = (y) => { const p = C.propagate(s, y); return Math.hypot(p.pmra, p.pmdec); };
  assert.ok(mu(ca.year) > 2.5 * mu(2026), "sky motion grows as it approaches");
  assert.ok(mu(30000) < mu(ca.year), "and slows as it recedes");
  assert.ok(Math.abs(C.propagate(s, ca.year).rv) < 1e-6, "radial velocity is zero at closest approach");
});

test("the sky track curves: it is a great circle, not a straight line in RA/Dec", () => {
  const s = FX.cases[0].star, a = C.propagate(s, -8000), m = C.propagate(s, 12000), b = C.propagate(s, 30000);
  const lin = { ra: a.ra + (b.ra - a.ra) * (12000 + 8000) / 38000, dec: a.dec + (b.dec - a.dec) * (12000 + 8000) / 38000 };
  assert.ok(C.separationArcsec(m, lin) > 3600, "far from the straight RA/Dec line between the ends");
});

test("starting state from a learnt prediction uses the learnt motion and Gaia's radial velocity", () => {
  const p = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app", "data", "stars", "pred", "hip87937.json"), "utf8"));
  const s = C.startState(p, { mag: 9.54, rv: -111 });
  assert.equal(s.star.pmdec, p.learnt.pmdec_2016);
  assert.equal(s.sources.rv, "Gaia DR3");
  assert.ok(Math.abs(s.star.rv - p.gaia_dr3.radial_velocity) < 1e-9);
  assert.equal(s.sources.parallax, "Gaia DR3");                    // not resolved by the learnt model for Barnard
  assert.deepEqual(s.warnings, []);
});

test("starting state without a prediction uses catalogue values and warns about what is missing", () => {
  const s = C.startState(null, { name: "X", ra: 10, dec: 20, pmra: 100, pmdec: -50, dist_pc: 10, rv: 0 });
  assert.equal(s.star.plx, 100);
  assert.match(s.sources.motion, /catalogue/);
  assert.ok(s.warnings.some((w) => /radial velocity/.test(w)));
  assert.equal(C.startState(null, { name: "Y", ra: 1, dec: 1, pmra: 0, pmdec: 0, dist_pc: null }).star, null);
});

test("Monte Carlo cloud grows with time and is reproducible", () => {
  const s = C.startState(null, { name: "X", ra: 10, dec: 20, pmra: 1000, pmdec: -500, dist_pc: 5, rv: 20 });
  const a = C.samples(s.star, s.err, 200, 3), b = C.samples(s.star, s.err, 200, 3);
  assert.deepEqual(a, b);
  assert.ok(C.spreadAt(a, 5000).sky68 > C.spreadAt(a, 2100).sky68);
});

test("magnitude follows the inverse-square law", () => {
  assert.ok(Math.abs(C.magAt(9.54, 6, 3) - (9.54 - 5 * Math.log10(2))) < 1e-12);
  assert.equal(C.magAt(null, 6, 3), null);
});

test("orthographic projection: east left, north up, back side flagged", () => {
  const e = C.ortho(11, 0, 10, 0), n = C.ortho(10, 1, 10, 0), back = C.ortho(190, 0, 10, 0);
  assert.ok(e.x < 0 && Math.abs(e.y) < 1e-9 && n.y > 0 && Math.abs(n.x) < 1e-9 && !back.front);
});

test("year labels", () => {
  assert.equal(C.fmtYear(2026), "2026 CE");
  assert.equal(C.fmtYear(0), "1 BCE");
  assert.equal(C.fmtYear(-7999), "8000 BCE");
});
