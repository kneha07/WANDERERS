// Sky layer helpers, checked against the shipped star catalogue. Run: node --test test/skyview.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const V = require("../app/skyview.js");
const Sky = require("../app/sky.js");
const DB = JSON.parse(fs.readFileSync(path.join(__dirname, "../app/data/skystars.json"), "utf8")), stars = DB.stars;
const INDEX = JSON.parse(fs.readFileSync(path.join(__dirname, "../app/data/stars/index.json"), "utf8")).stars;

test("the projection is stereographic: the rim is at 1, half-way is nearer than half", () => {
  assert.equal(V.radial(0, 60), 0);
  assert.ok(Math.abs(V.radial(60, 60) - 1) < 1e-12);
  assert.ok(Math.abs(V.radial(30, 60) - Math.tan(Math.PI / 12) / Math.tan(Math.PI / 6)) < 1e-12);
  assert.ok(V.radial(30, 60) < 0.5);
  assert.equal(V.radial(179, 60), Infinity);
});

test("the catalogue is sorted bright to faint, in range, and Sirius leads it", () => {
  assert.ok(stars.length > 8500);
  for (let i = 1; i < stars.length; i++) assert.ok(stars[i][2] >= stars[i - 1][2], `row ${i}`);
  for (const [ra, dec] of stars) assert.ok(ra >= 0 && ra < 360 && dec >= -90 && dec <= 90);
  assert.deepEqual(stars[0].slice(0, 3), [101.287, -16.716, -1.44]);
  assert.equal(stars[0][7], "Sirius");
});

test("the compass stars are the star database's naked-eye stars, one for one", () => {
  const want = INDEX.filter((s) => s.mag != null && s.mag <= 6.5);
  assert.equal(stars.length, want.length);
  const byKey = new Map(INDEX.map((s) => [s.key, s]));
  for (const row of stars.slice(0, 300)) {
    const rec = byKey.get(typeof row[4] === "number" ? `hip${row[4]}` : row[4]);
    assert.ok(rec, `no database record for ${row[4]}`);
    assert.ok(Math.abs(rec.ra - row[0]) < 0.001 && Math.abs(rec.dec - row[1]) < 0.001, String(row[4]));
    assert.equal(DB.meta.cons[row[6]], rec.con || "");
  }
});

test("a darker sky shows more stars: city < suburb < dark", () => {
  const n = (k) => V.countToLimit(stars, V.limitMag(k));
  assert.ok(n("city") > 100 && n("city") < 250, String(n("city")));
  assert.ok(n("suburb") > 700 && n("suburb") < 1100, String(n("suburb")));
  assert.ok(n("dark") > 4500 && n("dark") < 5500, String(n("dark")));
  assert.equal(V.countToLimit(stars, 99), stars.length);
  assert.equal(V.countToLimit(stars, -9), 0);
  assert.equal(stars[n("city") - 1][2] <= 3.0 && stars[n("city")][2] > 3.0, true);
});

// The 16 stars the radar already names (compass.js): each must be in the catalogue at the same place,
// so a name and its dot land on the same pixel (0.02 degree is 0.1 pixel on the 720-pixel radar).
const NAMED = [["Polaris", 37.95, 89.26], ["Vega", 279.23, 38.78], ["Arcturus", 213.92, 19.18], ["Capella", 79.17, 46.00],
  ["Sirius", 101.29, -16.72], ["Betelgeuse", 88.79, 7.41], ["Rigel", 78.63, -8.20], ["Aldebaran", 68.98, 16.51],
  ["Altair", 297.70, 8.87], ["Deneb", 310.36, 45.28], ["Spica", 201.30, -11.16], ["Antares", 247.35, -26.43],
  ["Procyon", 114.83, 5.22], ["Pollux", 116.33, 28.03], ["Regulus", 152.09, 11.97], ["Fomalhaut", 344.41, -29.62]];
test("every named star has its catalogue dot on the same spot of the sky", () => {
  const date = new Date("2026-11-15T06:00:00Z");
  for (const [name, ra, dec] of NAMED) {
    const a = Sky.observe({ ra, dec }, date, 47.6, -122.3);
    let best = 99;
    for (const s of stars.slice(0, V.countToLimit(stars, 3.0))) {
      const b = Sky.observe({ ra: s[0], dec: s[1] }, date, 47.6, -122.3);
      best = Math.min(best, Math.hypot((a.az - b.az) * Math.cos(a.alt * Math.PI / 180), a.alt - b.alt));
    }
    assert.ok(best < 0.02, `${name}: nearest catalogue star is ${best.toFixed(3)} deg away`);
  }
});

test("bright stars are drawn larger and more solid, and colour follows B-V", () => {
  assert.ok(V.starRadius(-1.46) > V.starRadius(2) && V.starRadius(2) > V.starRadius(6));
  assert.ok(V.starRadius(6) >= 0.9 && V.starAlpha(6) >= 0.25);
  assert.ok(V.starRadius(2, 15) > V.starRadius(2, 60));
  assert.equal(V.starAlpha(-1), 1);
  assert.ok(V.starAlpha(6) < V.starAlpha(3));
  assert.deepEqual(["B", "A", "G", "M", " ", undefined].map(V.starColour), ["#b8ccff", "#ffffff", "#fff0c8", "#ffc890", "#ffffff", "#ffffff"]);
});

test("screenRoll: level is 0, top to the right is +90, and the screen's own rotation cancels it", () => {
  const near = (x, want) => Math.abs(((x - want + 540) % 360) - 180) < 1e-6;
  assert.ok(near(V.screenRoll(0, 90, 0), 0));                   // upright, facing north
  assert.ok(near(V.screenRoll(123, 60, 0), 0));                 // leaning back, any heading: still level
  // phone turned so its top points east while the camera looks north along the horizon (X down, Y east, Z south)
  assert.ok(near(V.screenRoll(270, 0, 90), 90), String(V.screenRoll(270, 0, 90)));
  assert.ok(near(V.screenRoll(270, 0, 90, 270), 0));            // the page rotated with it: level again
  // top pointing west instead
  assert.ok(near(V.screenRoll(90, 0, -90), -90), String(V.screenRoll(90, 0, -90)));
  assert.ok(near(V.screenRoll(90, 0, -90, 90), 0));
  assert.ok(Number.isFinite(V.screenRoll(40, 0, 0)));           // flat on a table, camera at the ground
});

test("a star's card gives its name, constellation, distance and database key", () => {
  const c = V.starCard(stars[0], DB.meta.cons);
  assert.equal(c.title, "Sirius");
  assert.equal(c.key, "hip32349");
  assert.match(c.lines[0], /Magnitude -1\.4 · in Canis Major/);
  assert.match(c.lines[1], /8\.6 light-years away.*about 9 years ago/);
  const far = V.starCard([1, 2, 5.5, "K", 84431, 565, 0], ["X"]);
  assert.equal(far.title, "HIP 84431");
  assert.match(far.lines[1], /565 light-years/);
  assert.match(V.starCard([1, 2, 5.5, "K", 1, 0, 0], ["X"]).lines[1], /not measured/);
});

test("the pointing note is honest about the compass", () => {
  assert.deepEqual(V.pointing({ haveSensor: false }), { text: "No motion sensors: drag to aim", needsCal: false });
  assert.equal(V.pointing({ haveSensor: true, accuracy: null, calibrated: false }).deg, 10);
  assert.equal(V.pointing({ haveSensor: true, accuracy: null, calibrated: false }).needsCal, true);
  assert.equal(V.pointing({ haveSensor: true, accuracy: null, calibrated: true }).deg, 3);
  assert.equal(V.pointing({ haveSensor: true, accuracy: 14.6, calibrated: true }).text, "Direction good to about ±15°");
});

test("labels say what each view is not", () => {
  assert.match(V.LABELS.eye, /Not a photograph/);
  assert.match(V.LABELS.deep, /Not a live view/);
  assert.equal(V.fmtBytes(9.5 * 1048576), "9.5 MB");
  assert.equal(V.fmtBytes(38 * 1048576), "38 MB");
  assert.equal(V.fmtBytes(54011), "53 KB");
  assert.equal(V.fmtBytes(10240 * 1048576), "10.0 GB");
  assert.equal(V.fmtLat(47.6), "48° N");
  assert.equal(V.fmtLat(-33.9), "34° S");
});
