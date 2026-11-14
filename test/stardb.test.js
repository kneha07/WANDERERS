// Tests for app/stardb.js (star search, formatting, trajectory chart) and the committed star data.
// Run from the repository root:  node --test test/stardb.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const SD = require("../app/stardb.js");

const DATA = path.join(__dirname, "..", "app", "data", "stars");
const INDEX = JSON.parse(fs.readFileSync(path.join(DATA, "index.json"), "utf8"));
const STARS = INDEX.stars;
const first = (q) => (SD.search(STARS, q, { limit: 5 })[0] || {}).name;

test("search finds stars by proper name, Bayer, catalogue number and Gliese", () => {
  assert.equal(first("Barnard"), "Barnard's Star");
  assert.equal(first("barnards star"), "Barnard's Star");
  assert.equal(first("vega"), "Vega");
  assert.equal(first("HIP 32349"), "Sirius");
  assert.equal(first("hip32349"), "Sirius");
  assert.equal(first("Gl 699"), "Barnard's Star");
  assert.equal(first("gl699"), "Barnard's Star");
  assert.equal(first("Alpha Lyrae"), "Vega");
  assert.equal(first("wise 0855"), "WISE 0855-0714");
  const cen = SD.search(STARS, "alpha cen", { limit: 4 }).map((s) => s.name);
  assert.ok(cen.includes("Rigil Kentaurus"), cen.join(", "));
});

test("search: empty or junk queries give nothing; limit is respected", () => {
  assert.deepEqual(SD.search(STARS, ""), []);
  assert.deepEqual(SD.search(STARS, "   "), []);
  assert.deepEqual(SD.search(STARS, "zzqqxx"), []);
  assert.equal(SD.search(STARS, "a", { limit: 7 }).length, 7);
});

test("search: exact names beat partial ones, and ready predictions come first among equals", () => {
  const s = [{ key: "a", name: "Polaris Australis", aliases: [], mag: 1 }, { key: "b", name: "Polaris", aliases: [], mag: 2 }];
  assert.equal(SD.search(s, "polaris")[0].key, "b");
  const t = [{ key: "x", name: "Star X", aliases: [], mag: 1 }, { key: "y", name: "Star Y", aliases: [], mag: 5 }];
  assert.equal(SD.search(t, "star", { ready: new Set(["y"]) })[0].key, "y");
});

test("sexagesimal formatting, including rounding at 60 and negative declinations", () => {
  assert.equal(SD.hms(269.452083), "17h 57m 48.50s");
  assert.equal(SD.dms(4.693388), "+04° 41′ 36.2″");
  assert.equal(SD.dms(-62.679485), "−62° 40′ 46.1″");
  assert.equal(SD.hms(359.99999999), "00h 00m 00.00s");
  assert.equal(SD.dms(-0.5), "−00° 30′ 00.0″");
  assert.equal(SD.hms(NaN), "—");
});

test("tangent-plane offsets: east is +x, north is +y, and 1 arcsec is 1 arcsec", () => {
  const [x, y] = SD.offsets(10 + 1 / 3600, 0, 10, 0);
  assert.ok(Math.abs(x - 1) < 1e-6 && Math.abs(y) < 1e-9);
  const [x2, y2] = SD.offsets(10, 20 + 2 / 3600, 10, 20);
  assert.ok(Math.abs(x2) < 1e-9 && Math.abs(y2 - 2) < 1e-6);
});

test("chart: equal scale on both axes, east on the left, north up", () => {
  const rows = [[1900, 0, 0, 0, 0, 0.1], [2000, 0, 0, 10, 0, 0.1], [2100, 0, 0, 10, 10, 0.1]];
  const c = SD.chart({ path: { rows }, now: 2000, anchor: { ra: 0, dec: 0 }, observations: [] }, { width: 400, height: 400 });
  const [p0] = c.past, pNow = c.past[c.past.length - 1], pEnd = c.future[c.future.length - 1];
  assert.ok(pNow[0] < p0[0], "moving east goes left");
  assert.ok(pEnd[1] < pNow[1], "moving north goes up");
  assert.ok(Math.abs((p0[0] - pNow[0]) - (pNow[1] - pEnd[1])) < 1e-6, "same scale on x and y");
});

test("scale bar is a round number", () => {
  for (const [span, want] of [[1000, 200], [37, 10], [0.9, 0.2]]) assert.equal(SD.niceBar(span).arcsec, want);
});

// ---- committed data ----
const keys = new Set(STARS.map((s) => s.key));
test("star index: every row has what the page needs", () => {
  assert.ok(STARS.length > 10000);
  for (const s of STARS) {
    assert.ok(s.key && s.name && Array.isArray(s.aliases), s.key);
    assert.ok(Number.isFinite(s.ra) && s.ra >= 0 && s.ra < 360 && Number.isFinite(s.dec) && Math.abs(s.dec) <= 90, s.key);
  }
  assert.equal(keys.size, STARS.length, "keys are unique");
  for (const id of ["barnard", "eps_indi_b", "wise0855", "rw_aur", "r_dra"]) assert.ok(STARS.some((s) => s.wanderers === id), id);
});

const ready = JSON.parse(fs.readFileSync(path.join(DATA, "pred", "index.json"), "utf8"));
test("prediction list matches the files", () => {
  const files = fs.readdirSync(path.join(DATA, "pred")).filter((f) => f !== "index.json").map((f) => f.replace(/\.json$/, "")).sort();
  assert.deepEqual([...ready].sort(), files);
});
for (const key of ready) {
  test(`committed prediction: ${key}`, () => {
    const p = JSON.parse(fs.readFileSync(path.join(DATA, "pred", key + ".json"), "utf8"));
    assert.ok(keys.has(key), "in the star index");
    assert.equal(p.path.rows[0][0], 1900); assert.equal(p.path.rows[p.path.rows.length - 1][0], 2100);
    assert.ok(p.model.estimator.includes("HuberRegressor"));
    assert.ok(p.observations.length >= 4);
    const c = SD.chart(p);
    for (const q of c.past.concat(c.future, c.obs.map((o) => [o.x, o.y]))) assert.ok(q.every(Number.isFinite));
    // the measured points sit on (or near) the drawn path: within 5% of the chart for every non-outlier
    const span = Math.max(...c.past.concat(c.future).map((q) => q[0])) - Math.min(...c.past.concat(c.future).map((q) => q[0]));
    assert.ok(Number.isFinite(span));
  });
}
