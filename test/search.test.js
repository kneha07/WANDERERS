// Tests for app/search.js (name search and star card shared by the console and the Sky Compass).
// Run from the repository root:  node --test test/search.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");

globalThis.window = globalThis;
require("../app/search.js");
const S = globalThis.StarSearch;
const kind = (spect) => S.describe({ spect })[0];

test("star card: giants and bright giants are not called supergiants", () => {
  for (const sp of ["K1.5III", "G8III", "M5III", "G8IIIb", "K0III-IV", "K3II-III"]) assert.match(kind(sp), /: a giant /, sp);
  assert.match(kind("A0II"), /: a bright giant /);
  for (const sp of ["M2Iab", "B8Ia", "F5Ib-II", "M1.5Iab-Ib", "A2I"]) assert.match(kind(sp), /: a supergiant /, sp);
  assert.match(kind("K0IV"), /: a subgiant /);
  for (const sp of ["G2V", "M3.5V", "M0.5Ve"]) assert.match(kind(sp), /: a main-sequence star/, sp);
  assert.match(kind("sdM4"), /: a subdwarf/);
});

test("star card: a white dwarf is named as one", () => {
  assert.equal(kind("DA2"), "Spectral type DA2: a white dwarf (the leftover core of a dead star).");
  assert.equal(kind("XYZ"), "Spectral type XYZ.");
});

test("hms/dms never show 60 seconds or 24 hours", () => {
  const sec = (h, m, s) => 15 * (h + m / 60 + s / 3600), arc = (d, m, s) => d + m / 60 + s / 3600;
  assert.equal(S.hms(sec(10, 59, 59.96)), "11h00m00.0s");
  assert.equal(S.hms(sec(23, 59, 59.97)), "00h00m00.0s");
  assert.equal(S.hms(360), "00h00m00.0s");
  assert.equal(S.hms(sec(17, 57, 48.5)), "17h57m48.5s");
  assert.equal(S.hms(0), "00h00m00.0s");
  assert.equal(S.dms(arc(4, 59, 59.6)), "+05d00m00s");
  assert.equal(S.dms(-arc(10, 0, 59.99)), "-10d01m00s");
  assert.equal(S.dms(arc(89, 59, 59.9)), "+90d00m00s");
  assert.equal(S.dms(-arc(7, 14, 42.5)), "-07d14m43s");
  assert.equal(S.dms(4.693), "+04d41m35s");
});

test("hms/dms of every catalogue star are well formed", () => {
  const rows = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app", "data", "stars.json"), "utf8"));
  for (const r of rows) {
    assert.match(S.hms(r[2]), /^([01]\d|2[0-3])h[0-5]\dm[0-5]\d\.\ds$/, `${r[0]} ${r[2]}`);
    assert.match(S.dms(r[3]), /^[+-]([0-8]\d|90)d[0-5]\dm[0-5]\ds$/, `${r[0]} ${r[3]}`);
  }
});
