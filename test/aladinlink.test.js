// Tests for app/aladinlink.js (link that opens a field in Aladin Lite).
// Run from the repository root:  node --test test/aladinlink.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const AL = require("../app/aladinlink.js");

const parts = (u) => { const x = new URL(u); return { origin: x.origin + x.pathname, ...Object.fromEntries(x.searchParams) }; };

test("builds the link for WISE 0855's field", () => {
  const p = parts(AL.url({ ra: 133.7951, dec: -7.2451, fovArcsec: 300 }));
  assert.equal(p.origin, "https://aladin.cds.unistra.fr/AladinLite/");
  assert.deepEqual([p.ra, p.dec, p.fov, p.hips], ["133.79510", "-7.24510", "0.0833", "P/allWISE/color"]);
});

test("field of view converts arcseconds to degrees for each size the page offers", () => {
  assert.equal(parts(AL.url({ ra: 1, dec: 1, fovArcsec: 120 })).fov, "0.0333");
  assert.equal(parts(AL.url({ ra: 1, dec: 1, fovArcsec: 300 })).fov, "0.0833");
  assert.equal(parts(AL.url({ ra: 1, dec: 1, fovArcsec: 600 })).fov, "0.1667");
});

test("values are brought into the ranges Aladin accepts", () => {
  assert.equal(parts(AL.url({ ra: -10, dec: 0, fovArcsec: 300 })).ra, "350.00000");
  assert.equal(parts(AL.url({ ra: 370, dec: 0, fovArcsec: 300 })).ra, "10.00000");
  assert.equal(parts(AL.url({ ra: 360, dec: 0, fovArcsec: 300 })).ra, "0.00000");
  assert.equal(parts(AL.url({ ra: 10, dec: 95, fovArcsec: 300 })).dec, "90.00000");
  assert.equal(parts(AL.url({ ra: 10, dec: -95, fovArcsec: 300 })).dec, "-90.00000");
  assert.equal(parts(AL.url({ ra: 10, dec: 0, fovArcsec: 10 ** 9 })).fov, "180");
  assert.ok(Number(parts(AL.url({ ra: 10, dec: 0, fovArcsec: 0 })).fov) > 0, "fov must stay above zero");
});

test("a different survey can be chosen", () => {
  assert.equal(parts(AL.url({ ra: 1, dec: 1, fovArcsec: 300, survey: "P/DSS2/color" })).hips, "P/DSS2/color");
});

test("missing or non-numeric values are rejected instead of making a broken link", () => {
  for (const bad of [{}, { ra: 1, dec: 1 }, { ra: "x", dec: 1, fovArcsec: 300 }, { ra: 1, dec: NaN, fovArcsec: 300 }, { ra: null, dec: 1, fovArcsec: 300 }, { ra: 1, dec: 1, fovArcsec: "" }])
    assert.throws(() => AL.url(bad), /must be a number/, JSON.stringify(bad));
  assert.throws(() => AL.url(), /must be a number/);
});

test("the link only carries the four sky parameters and goes to the CDS host", () => {
  const x = new URL(AL.url({ ra: 1, dec: 2, fovArcsec: 300 }));
  assert.equal(x.protocol, "https:");
  assert.equal(x.hostname, "aladin.cds.unistra.fr");
  assert.deepEqual([...x.searchParams.keys()].sort(), ["dec", "fov", "hips", "ra"]);
});

const dataDir = path.join(__dirname, "..", "app", "data"), indexFile = path.join(dataDir, "index.json");
test("real data: every committed target gives a link inside Aladin's ranges, centred on its field", { skip: !fs.existsSync(indexFile) && "data not present" }, () => {
  const ids = JSON.parse(fs.readFileSync(indexFile, "utf8")).map((e) => e.id);
  assert.ok(ids.length >= 5);
  for (const id of ids) {
    const g = JSON.parse(fs.readFileSync(path.join(dataDir, id, "target.json"), "utf8")).grid;
    const p = parts(AL.url({ ra: g.centre_ra, dec: g.centre_dec, fovArcsec: g.npix * g.arcsec_per_pix }));
    assert.ok(+p.ra >= 0 && +p.ra < 360 && +p.dec >= -90 && +p.dec <= 90 && +p.fov > 0 && +p.fov <= 180, id);
    assert.ok(Math.abs(+p.ra - g.centre_ra) < 1e-5 && Math.abs(+p.dec - g.centre_dec) < 1e-5, id);
    assert.equal(+p.fov, +(g.npix * g.arcsec_per_pix / 3600).toFixed(4), id);
  }
});
