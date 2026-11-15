// Tests for app/starprofile.js (star profile maths) and the shipped app/data/stars/profile/*.json.
// Run from the repository root:  node --test test/starprofile.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const SP = require("../app/starprofile.js");
const Q = require("../app/starquake.js");
const DATA = path.join(__dirname, "..", "app", "data");
const STARS = JSON.parse(fs.readFileSync(path.join(DATA, "stars", "index.json"), "utf8")).stars;
const INFO = JSON.parse(fs.readFileSync(path.join(DATA, "starquake_stars.json"), "utf8"));

test("blackbody colours: cool stars red-orange, the Sun near white, hot stars blue-white", () => {
  const [r3, g3, b3] = SP.blackbodyRGB(3000), [rs, gs, bs] = SP.blackbodyRGB(5772), [r10, g10, b10] = SP.blackbodyRGB(10000);
  assert.ok(r3 === 255 && b3 < 120 && g3 < r3, `3000 K ${[r3, g3, b3]}`);
  assert.ok(rs >= 240 && gs >= 220 && bs >= 190, `Sun ${[rs, gs, bs]}`);        // a warm white, not yellow
  assert.ok(b10 === 255 && r10 < 230, `10000 K ${[r10, g10, b10]}`);
  assert.deepEqual(SP.blackbodyRGB(0), [128, 128, 128]);
});

test("the Sun compared with itself: every ratio is 1", () => {
  const P = { M: { value: 1 }, R: { value: 1 }, T: { value: 5772 }, L: { value: 1 }, age: { value: 4.57 } };
  const D = SP.derived(P);
  assert.ok(Math.abs(D.rho - 1.408) < 1e-9 && Math.abs(D.g - 274) < 1e-9);
  assert.ok(Math.abs(D.diamKm - 1391400) < 1);
  for (const [, r] of SP.ratios(P, D)) assert.ok(Math.abs(r - 1) < 1e-9);
  assert.ok(D.hzIn < 1 && D.hzOut > 1, "Earth's orbit is inside the Sun's habitable zone");
});

test("property sources: the profile wins, then literature, then the catalogue estimate (labelled)", () => {
  const row = STARS.find((s) => s.name === "Arcturus");
  const fromProfile = SP.properties({ properties: { radius: { value: 25.4, source: "X" } } }, row, null, Q);
  assert.equal(fromProfile.R.source, "X");
  const fromLit = SP.properties(null, row, { R: 26, params_ref: "lit" }, Q);
  assert.equal(fromLit.R.value, 26); assert.equal(fromLit.R.source, "lit");
  const est = SP.properties(null, row, null, Q);
  assert.match(est.R.source, /estimate/); assert.ok(est.R.value > 10, "a giant");
  assert.ok(est.L && est.dist, "luminosity and distance are always there for a catalogued star");
});

test("composition: the Sun is about 74% hydrogen, 25% helium, 1.3% metals, with oxygen the top metal", () => {
  const c = SP.composition(0, null);
  assert.ok(Math.abs(c.Z - 0.0134) < 1e-12);
  assert.ok(c.X > 0.72 && c.X < 0.75 && c.Y > 0.25 && c.Y < 0.27);
  const top = Object.entries(c.metals).sort((a, b) => b[1] - a[1]).map((x) => x[0]);
  assert.deepEqual(top.slice(0, 2), ["O", "C"]);
  assert.ok(Math.abs(Object.values(c.metals).reduce((a, b) => a + b, 0) - c.Z) < 1e-12);
  // a metal-poor star has ten times fewer metals at [Fe/H] = -1
  assert.ok(Math.abs(SP.composition(-1, null).Z / c.Z - 0.1) < 1e-9);
  // a measured over-abundance of iron raises iron's share of the metals
  const fe = SP.composition(0, { Fe: { x_h: 0.5 } });
  assert.ok(fe.metals.Fe / fe.Z > c.metals.Fe / c.Z * 2.5);
});

test("abundance colours: solar is white, below is blue, above is orange", () => {
  assert.equal(SP.abundColor(0), "rgb(255,255,255)");
  const [r1, , b1] = SP.abundColor(-0.6).match(/\d+/g).map(Number), [r2, , b2] = SP.abundColor(0.6).match(/\d+/g).map(Number);
  assert.ok(b1 > r1 && r2 > b2);
});

test("every element the pipeline asks Hypatia for has a place in the periodic table", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "pipeline", "star_profile.py"), "utf8");
  const els = JSON.parse(src.match(/ELEMENTS = (\[[^\]]+\])/s)[1].replace(/'/g, '"'));
  for (const e of els) assert.ok(SP.PT[e], e);
});

const PROF = path.join(DATA, "stars", "profile");
const ready = JSON.parse(fs.readFileSync(path.join(PROF, "index.json"), "utf8"));
test("shipped profiles: list matches files, every value has a source, abundances and spectra are sane", () => {
  const files = fs.readdirSync(PROF).filter((f) => f !== "index.json").map((f) => f.replace(/\.json$/, "")).sort();
  assert.deepEqual([...ready].sort(), files);
  for (const k of ready) {
    const p = JSON.parse(fs.readFileSync(path.join(PROF, k + ".json"), "utf8"));
    for (const [name, v] of Object.entries(p.properties)) assert.ok(Number.isFinite(v.value) && v.source, `${k} ${name}`);
    for (const [el, a] of Object.entries((p.chemistry || {}).abundances || {})) assert.ok(a.x_h > -3 && a.x_h < 2, `${k} ${el} ${a.x_h}`);
    if (p.spectrum) {
      assert.equal(p.spectrum.wavelength_nm.length, p.spectrum.flux.length);
      assert.ok(Math.max(...p.spectrum.flux) === 1, `${k} spectrum scaled to 1`);
    }
  }
});

test("well-known stars come out right", () => {
  const load = (k) => JSON.parse(fs.readFileSync(path.join(PROF, k + ".json"), "utf8"));
  assert.ok(load("hip71683").chemistry.abundances.Fe.x_h > 0.1, "Alpha Centauri A is metal-rich");
  assert.ok(load("hip8102").chemistry.abundances.Fe.x_h < -0.3, "Tau Ceti is metal-poor");
  assert.ok(load("hip8102").planets.length >= 3, "Tau Ceti has planets");
  assert.ok(load("hip57939").properties.metallicity.value < -1, "Groombridge 1830 is a metal-poor halo star");
  const bar = SP.properties(load("hip87937"), STARS.find((s) => s.key === "hip87937"), INFO.hip87937, Q);
  assert.ok(bar.R.value > 0.15 && bar.R.value < 0.25 && bar.M.value < 0.2, "Barnard's Star is a small red dwarf");
});

test("pre-made sounds exist for the default stars, and targets map to stars", () => {
  const made = JSON.parse(fs.readFileSync(path.join(DATA, "starquake", "model", "index.json"), "utf8"));
  assert.ok(made.includes("sun") && made.includes("hip87937") && made.length >= 15);
  for (const k of made) assert.ok(fs.existsSync(path.join(DATA, "starquake", "model", k + ".wav")), k);
  assert.ok(!made.includes("hip91262") && !made.includes("hip32349"), "Vega and Sirius have no starquakes");
  const map = JSON.parse(fs.readFileSync(path.join(DATA, "starquake", "targets.json"), "utf8"));
  assert.equal(map.barnard, "hip87937");
});
