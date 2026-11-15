// Tests for app/chartlayout.js (spectrum chart width and band-name placement).
// Run from the repository root:  node --test test/chartlayout.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const CL = require("../app/chartlayout.js");

const L = 60, R = 20;
const xFor = (W) => (l) => L + ((l - 0.75) / (5.0 - 0.75)) * (W - L - R);   // same mapping the chart uses
const bandsFile = path.join(__dirname, "..", "app", "data", "wise0855", "target.json");
const realBands = fs.existsSync(bandsFile) ? JSON.parse(fs.readFileSync(bandsFile, "utf8")).bands : null;

test("chart width: real width within limits, 900 when unknown", () => {
  assert.equal(CL.chartWidth(342.4), 342);
  assert.equal(CL.chartWidth(100), CL.MIN_W);
  assert.equal(CL.chartWidth(5000), CL.MAX_W);
  for (const bad of [0, -5, NaN, undefined, null, "abc", Infinity * 0]) assert.equal(CL.chartWidth(bad), 900, String(bad));
  assert.equal(CL.chartWidth("640"), 640);
});

test("chart height is shorter on narrow screens", () => {
  assert.equal(CL.chartHeight(390), 230);
  assert.equal(CL.chartHeight(519), 230);
  assert.equal(CL.chartHeight(520), 260);
  assert.equal(CL.chartHeight(1000), 260);
});

test("names use subscripts", () => {
  assert.equal(CL.prettyName("H2O"), "H₂O");
  assert.equal(CL.prettyName("CH4"), "CH₄");
  assert.equal(CL.prettyName("CO2"), "CO₂");
  assert.equal(CL.prettyName("CO"), "CO");
});

test("well-separated bands all stay on the first row", () => {
  const bands = [{ name: "H2O", lo: 1, hi: 1.2 }, { name: "CH4", lo: 3, hi: 3.2 }, { name: "CO", lo: 4.5, hi: 4.8 }];
  const out = CL.placeLabels(bands, xFor(900));
  assert.equal(out.length, 3);
  assert.ok(out.every((o) => o.row === 0));
});

test("crowded bands move to the second row, and the input is not reordered", () => {
  const bands = [{ name: "CH4", lo: 1.30, hi: 1.34 }, { name: "H2O", lo: 1.25, hi: 1.29 }];   // out of order and touching
  const copy = JSON.stringify(bands);
  const out = CL.placeLabels(bands, xFor(340));
  assert.equal(JSON.stringify(bands), copy, "input unchanged");
  assert.deepEqual(out.map((o) => o.name), ["H₂O", "CH₄"], "sorted left to right");
  assert.deepEqual(out.map((o) => o.row), [0, 1]);
});

test("a name with no room on either row is left out, not drawn on top of another", () => {
  const bands = ["H2O", "CH4", "CO2", "CO"].map((name, i) => ({ name, lo: 2 + i * 0.01, hi: 2.005 + i * 0.01 }));
  const out = CL.placeLabels(bands, xFor(340));
  assert.ok(out.length < bands.length);
  for (const row of [0, 1]) {
    const r = out.filter((o) => o.row === row);
    for (let i = 1; i < r.length; i++) assert.ok(r[i].left >= r[i - 1].right, `row ${row} overlaps`);
  }
});

test("no band list gives no labels", () => assert.deepEqual(CL.placeLabels([], xFor(900)), []));

test("real bands: labels never overlap within a row at any width from a small phone to a wide screen", { skip: !realBands && "data not present" }, () => {
  assert.ok(realBands.length >= 4);
  for (let W = 260; W <= 1400; W += 20) {
    const out = CL.placeLabels(realBands, xFor(W));
    for (const row of [0, 1]) {
      const r = out.filter((o) => o.row === row);
      for (let i = 1; i < r.length; i++) assert.ok(r[i].left >= r[i - 1].right, `width ${W}, row ${row}: ${r[i - 1].name} / ${r[i].name}`);
    }
    for (const o of out) assert.ok(o.left >= 0 && o.right <= W, `width ${W}: ${o.name} inside the chart`);
  }
});

test("real bands: on a wide chart every band gets a name; on a phone most do", { skip: !realBands && "data not present" }, () => {
  assert.equal(CL.placeLabels(realBands, xFor(1000)).length, realBands.length);
  const phone = CL.placeLabels(realBands, xFor(342)).length;
  assert.ok(phone >= realBands.length - 2, `phone shows ${phone} of ${realBands.length}`);
});
