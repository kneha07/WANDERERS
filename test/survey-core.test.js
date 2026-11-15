// Sky Survey page helpers (app/survey.js, used as SurveyCore): HEALPix tiles, the all-sky projection, number
// formatting, filters, sorting, the track plot and the tolerant reading of validation results. No browser needed.
// node --test test/survey-core.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../app/survey.js");
const Hips = require("../app/hips.js");

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b} (±${tol})`);
const raNear = (a, b, tol, msg) => near(((a - b + 540) % 360) - 180, 0, tol, msg);

// ---------- HEALPix: centres and corners against astropy_healpix 2.0.1 (HEALPix(nside=32, order="nested")) ----------
// computed with: HEALPix(nside=32, order="nested", frame=ICRS()).healpix_to_lonlat(k)
const ASTROPY_CENTRES = [[0, 45.0, 1.193748], [1, 46.40625, 2.388015], [2, 43.59375, 2.388015], [3, 45.0, 3.583322], [100, 53.4375, 18.209957],
  [1023, 45.0, 88.538029], [1024, 135.0, 1.193748], [2047, 135.0, 88.538029], [3000, 190.384615, 70.906667], [4095, 315.0, 88.538029],
  [4096, 0.0, -40.228185], [5000, 345.9375, 13.248015], [6143, 90.0, 40.228185], [6144, 180.0, -40.228185], [7000, 194.0625, 18.209957],
  [8191, 270.0, 40.228185], [8192, 45.0, -88.538029], [8545, 76.5, -44.99388], [10000, 140.625, -34.228866], [12287, 315.0, -1.193748]];
// the tile holding each validation target: lonlat_to_healpix(ra, dec), then its centre
const ASTROPY_TARGETS = { "Barnard's Star": [7945, 268.59375, 4.780192], "Kapteyn's Star": [8545, 76.5, -44.99388], "WISE 0855": [10226, 133.59375, -7.180756],
  "Luhman 16": [9509, 163.125, -54.340912], "Wolf 359": [6865, 164.53125, 7.180756], "Lalande 21185": [1355, 165.9375, 37.1689],
  "Proxima": [10397, 217.5, -63.448284], "61 Cygni": [3325, 316.40625, 38.682187], "Epsilon Indi": [11391, 330.652174, -55.87335] };
// boundaries_lonlat(k, step=1): north, west, south, east
const ASTROPY_CORNERS = { 0: [[45.0, 2.38802], [43.59375, 1.19375], [45.0, 0.0], [46.40625, 1.19375]], 1023: [[0.0, 90.0], [0.0, 88.53803], [45.0, 87.07582], [90.0, 88.53803]],
  4096: [[0.0, -38.68219], [358.59375, -40.22818], [0.0, -41.81031], [1.40625, -40.22818]], 8545: [[75.48387, -43.40686], [75.0, -44.99388], [77.58621, -46.57185], [78.0, -44.99388]],
  10226: [[133.59375, -5.97916], [132.1875, -7.18076], [133.59375, -8.38554], [135.0, -7.18076]], 12287: [[315.0, 0.0], [313.59375, -1.19375], [315.0, -2.38802], [316.40625, -1.19375]] };

test("pix2ang (nested, nside 32) matches astropy_healpix in the equatorial belt", () => {
  for (const [k, ra, dec] of ASTROPY_CENTRES.filter(([, , d]) => Math.abs(d) < 41.9)) {
    const c = C.pix2ang(k);
    raNear(c.ra, ra, 1e-5, `k5 ${k} RA`); near(c.dec, dec, 1e-5, `k5 ${k} Dec`);
  }
});

test("pix2ang matches astropy_healpix in both polar caps", () => {
  const caps = ASTROPY_CENTRES.filter(([, , d]) => Math.abs(d) >= 41.9);
  assert.ok(caps.length >= 6);
  for (const [k, ra, dec] of caps) {
    const c = C.pix2ang(k);
    raNear(c.ra, ra, 1e-5, `k5 ${k} RA`); near(c.dec, dec, 1e-5, `k5 ${k} Dec`);
  }
});

test("the tiles holding the nine validation targets have astropy's centres", () => {
  for (const [name, [k, ra, dec]] of Object.entries(ASTROPY_TARGETS)) {
    const c = C.pix2ang(k);
    raNear(c.ra, ra, 1e-5, name); near(c.dec, dec, 1e-5, name);
  }
});

test("tile corners match astropy's boundaries (north, west, south, east)", () => {
  for (const [k, want] of Object.entries(ASTROPY_CORNERS)) {
    const got = C.corners(+k);
    assert.equal(got.length, 4);
    want.forEach(([ra, dec], i) => {
      near(got[i].dec, dec, 1e-4, `k5 ${k} corner ${i} Dec`);
      if (Math.abs(dec) < 89.9999) raNear(got[i].ra, ra, 1e-4, `k5 ${k} corner ${i} RA`);   // at a pole RA means nothing
    });
  }
});

test("all 12,288 tile centres agree with the site's independent HiPS code and are distinct", () => {
  const seen = new Set();
  for (let k = 0; k < C.N_TILES; k++) {
    const a = C.pix2ang(k), b = Hips.centre(5, k);
    raNear(a.ra, b.ra, 1e-9, `k5 ${k} RA`); near(a.dec, b.dec, 1e-9, `k5 ${k} Dec`);
    assert.equal(Hips.pixel(5, a.ra, a.dec), k, `centre of ${k} lies in ${k}`);
    seen.add(`${a.ra.toFixed(6)} ${a.dec.toFixed(6)}`);
  }
  assert.equal(seen.size, 12288);
  near(C.TILE_AREA_DEG2, 3.357174580844667, 1e-9, "tile area (astropy: 3.357174580844667 deg2)");
});

test("tilePoint stays inside its tile", () => {
  for (const k of [0, 1023, 4096, 8545, 10226, 12287]) for (const [fx, fy] of [[0.1, 0.1], [0.9, 0.2], [0.5, 0.95], [0.05, 0.6]]) {
    const p = C.tilePoint(k, fx, fy);
    assert.equal(Hips.pixel(5, p.ra, p.dec), k, `k5 ${k} at ${fx},${fy}`);
  }
});

// ---------- the map projection ----------
test("Hammer projection: RA 0h in the middle, east to the left, north up, poles on the edge", () => {
  assert.deepEqual(C.project(0, 0), [500, 250]);
  const [xe] = C.project(90, 0), [xw] = C.project(270, 0);
  assert.ok(xe < 500 && xw > 500, "RA 6h (east) left of centre, 18h right");
  near(xe + xw, 1000, 1e-9, "symmetric");
  assert.ok(C.project(0, 60)[1] < 250 && C.project(0, -60)[1] > 250, "north up");
  near(C.project(123, 90)[1], 5, 1e-9, "north pole at the top of the ellipse");
  near(C.project(0, -90)[1], 495, 1e-9, "south pole at the bottom");
  near(C.project(180.0001, 0)[0], 990, 0.01, "RA 12h on the right edge");
  near(C.project(179.9999, 0)[0], 10, 0.01, "and on the left edge");
});

test("Hammer projection is equal-area: the formula and the ellipse agree for known points", () => {
  // independent: x = 2√2 cosφ sin(λ/2)/√(1+cosφ cos(λ/2)), y = √2 sinφ/√(1+cosφ cos(λ/2)), λ = -RA (east left)
  for (const [ra, dec] of [[76.5, -44.99388], [268.59375, 4.780192], [133.59375, -7.180756], [30, 60], [330, -20]]) {
    const l = -(((ra + 180) % 360) - 180) * Math.PI / 180, b = dec * Math.PI / 180, d = Math.sqrt(1 + Math.cos(b) * Math.cos(l / 2));
    const X = 2 * Math.SQRT2 * Math.cos(b) * Math.sin(l / 2) / d, Y = Math.SQRT2 * Math.sin(b) / d;
    const [px, py] = C.project(ra, dec);
    near(px, 500 + 490 * X / (2 * Math.SQRT2), 1e-9, `x ${ra},${dec}`);
    near(py, 250 - 245 * Y / Math.SQRT2, 1e-9, `y ${ra},${dec}`);
    assert.ok(((px - 500) / 490) ** 2 + ((py - 250) / 245) ** 2 <= 1 + 1e-12, "inside the ellipse");
  }
});

test("a tile on the RA 12h edge is drawn as one small polygon, not stretched across the map", () => {
  for (const k of [6144, 1024 * 6 + 5, 5461]) {
    const { centre, poly } = C.tilePolygon(k);
    for (const [x, y] of poly) assert.ok(Math.hypot(x - centre[0], y - centre[1]) < 40, `k5 ${k}: corner ${x},${y} near centre ${centre}`);
  }
  const c = C.pix2ang(8545), { centre } = C.tilePolygon(8545), [x, y] = C.project(c.ra, c.dec);
  near(centre[0], x, 1e-9, "x"); near(centre[1], y, 1e-9, "y");
});

test("Milky Way plane and ecliptic lines pass through the right places", () => {
  const gc = C.galToEq(0, 0);   // Galactic centre: RA 266.40, Dec −28.94
  near(gc.ra, 266.405, 0.01, "GC RA"); near(gc.dec, -28.936, 0.01, "GC Dec");
  const ngp = C.galToEq(0, 90); near(ngp.ra, 192.859, 0.01, "NGP RA"); near(ngp.dec, 27.128, 0.01, "NGP Dec");
  const sol = C.eclToEq(90); near(sol.ra, 90, 1e-9, "summer solstice RA"); near(sol.dec, 23.4393, 1e-9, "obliquity");
  const d = C.skyPath(Array.from({ length: 361 }, (_, i) => C.galToEq(i, 0)));
  assert.match(d, /^M/); assert.doesNotMatch(d, /NaN/);
  assert.ok((d.match(/M/g) || []).length <= 3, "breaks only at the map edge");
});

// ---------- formatting ----------
test("whole numbers get thousands separators, including billions", () => {
  assert.equal(C.fmtInt(8116540408), "8,116,540,408");
  assert.equal(C.fmtInt(2400000000), "2,400,000,000");
  assert.equal(C.fmtInt(1234567), "1,234,567");
  assert.equal(C.fmtInt(999), "999");
  assert.equal(C.fmtInt(0), "0");
  assert.equal(C.fmtInt(12.6), "13");
  assert.equal(C.fmtInt(null), "—");
  assert.equal(C.fmtInt("x"), "—");
});

test("big numbers in words: billions, millions, trillions", () => {
  assert.equal(C.fmtBig(2.4e9), "2.4 billion");
  assert.equal(C.fmtBig(12463118207), "12.5 billion");
  assert.equal(C.fmtBig(8116540408), "8.12 billion");
  assert.equal(C.fmtBig(1.5e11), "150 billion");
  assert.equal(C.fmtBig(418e6), "418 million");
  assert.equal(C.fmtBig(1.2e12), "1.2 trillion");
  assert.equal(C.fmtBig(7853), "7,853");
  assert.equal(C.fmtBig(undefined), "—");
});

test("sky percentages and run times read naturally", () => {
  assert.equal(C.fmtPct(0.052083), "5.2%");
  assert.equal(C.fmtPct(0.0098), "0.98%");
  assert.equal(C.fmtPct(1), "100%");
  assert.equal(C.fmtPct(0), "0%");
  assert.equal(C.fmtHours(1.6), "1.6 hours");
  assert.equal(C.fmtHours(0.25), "15 minutes");
  assert.equal(C.fmtHours(72), "3 days");
  assert.equal(C.fmtPm(8641.2), "8.64");
  assert.equal(C.fmtPm(152), "0.152");
});

test("sexagesimal coordinates: Kapteyn's Star and WISE 0855", () => {
  assert.deepEqual([C.sexa(77.95994, -45.04381).ra, C.sexa(77.95994, -45.04381).dec], ["05h11m50.39s", "-45d02m37.7s"]);
  const w = C.sexa(133.7864, -7.2439);
  assert.equal(w.ra, "08h55m08.74s"); assert.equal(w.dec, "-07d14m38.0s");
  assert.match(C.sexa(77.95994, -45.04381).pretty, /^05ʰ 11ᵐ 50\.39ˢ {2}−45° 02′ 37\.7″$/);
});

test("sexagesimal rounding carries instead of printing 60 seconds", () => {
  assert.equal(C.sexa(359.9999999, 0).ra, "00h00m00.00s");
  assert.equal(C.sexa(14.99999999, 0).ra, "01h00m00.00s");
  assert.equal(C.sexa(0, 89.99999999).dec, "+90d00m00.0s");
  assert.equal(C.sexa(0, -0.000001).dec, "+00d00m00.0s", "no negative zero");
  assert.equal(C.sexa(-15, 10.5).ra, "23h00m00.00s");
});

test("direction of motion: position angle east of north and compass point", () => {
  near(C.posAngle(0, 100), 0, 1e-9, "north"); near(C.posAngle(100, 0), 90, 1e-9, "east");
  near(C.posAngle(-100, 0), 270, 1e-9, "west"); near(C.posAngle(0, -100), 180, 1e-9, "south");
  near(C.posAngle(6491.2, -5708.6), 131.33, 0.01, "Kapteyn's Star");
  assert.equal(C.compass(131.33), "SE"); assert.equal(C.compass(355), "N"); assert.equal(C.compass(274.7), "W");
});

test("HTML from the data is escaped", () => {
  assert.equal(C.esc(`<img src=x onerror="a('b')">&`), "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;");
  assert.equal(C.esc(null), "");
});

// ---------- candidates ----------
const rows = [
  { id: "1-0001", rank: 1, k5: 1, class: "unexplained", pm: 1263, pmra: -912, pmdec: -873, w1: 16.5, w2: 14.4, w1w2: 2.14, n_visits: 20, score: 4.7, gaia: { checked: true, match: false } },
  { id: "8545-0003", rank: 2, k5: 8545, class: "known (Gaia)", pm: 8641, pmra: 6490, pmdec: -5705, w1: 6.1, w2: 5.8, w1w2: 0.3, n_visits: 21, score: 0.3, gaia: { checked: true, match: true, source_id: "4810594479418041856", sep_arcsec: 0.4 } },
  { id: "10226-0001", rank: 3, k5: 10226, class: "unexplained", pm: 8150, pmra: -8123, pmdec: 673, w1: null, w2: 14, w1w2: null, n_visits: 19, score: 4.6, gaia: { checked: true, match: false } },
  { id: "77-0002", rank: 4, k5: 77, class: "likely artefact", pm: 400, pmra: 0, pmdec: 400, w1: 12.2, w2: 12, w1w2: 0.2, n_visits: 6, score: -1, gaia: { checked: true, match: false } },
  { id: "78-0001", rank: 5, k5: 78, class: "not checked", pm: 160, pmra: 160, pmdec: 0, w1: 11.6, w2: 11, w1w2: 0.6, n_visits: 12, score: 1.2, gaia: { checked: false } },
];
const base = { cls: "all", minPm: 0, red: false, q: "", tile: null };
const ids = (xs) => xs.map((m) => m.id);

test("red means W1−W2 ≥ 0.5, or seen in W2 but not in W1", () => {
  assert.deepEqual(rows.filter(C.isRed).map((m) => m.id), ["1-0001", "10226-0001", "78-0001"]);
  assert.equal(C.isRed({ w1w2: 0.5 }), true);
  assert.equal(C.isRed({ w1w2: 0.49 }), false);
  assert.equal(C.isRed({ w1: null, w2: null }), false, "nothing measured is not red");
});

test("filters: class, minimum motion, red, tile and search each narrow the list", () => {
  assert.equal(C.applyFilters(rows, base).length, 5);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, cls: "unexplained" })), ["1-0001", "10226-0001"]);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, minPm: 1.5 })), ["8545-0003", "10226-0001"]);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, red: true, cls: "unexplained", minPm: 5 })), ["10226-0001"]);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, tile: 8545 })), ["8545-0003"]);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, q: " 10226-" })), ["10226-0001"]);
  assert.deepEqual(ids(C.applyFilters(rows, { ...base, q: "481059447941" })), ["8545-0003"], "search also finds a Gaia source id");
  assert.deepEqual(C.applyFilters(rows, { ...base, q: "nothing" }), []);
});

test("sorting: every column, both directions, missing values last", () => {
  assert.deepEqual(ids(C.sortRows(rows, "pm", -1)), ["8545-0003", "10226-0001", "1-0001", "77-0002", "78-0001"]);
  assert.deepEqual(ids(C.sortRows(rows, "pm", 1)), ["78-0001", "77-0002", "1-0001", "10226-0001", "8545-0003"]);
  assert.deepEqual(ids(C.sortRows(rows, "w1w2", -1)), ["1-0001", "78-0001", "8545-0003", "77-0002", "10226-0001"], "no colour sorts last");
  assert.deepEqual(ids(C.sortRows(rows, "w1w2", 1)).at(-1), "10226-0001", "... in both directions");
  assert.deepEqual(ids(C.sortRows(rows, "class", 1)), ["1-0001", "10226-0001", "8545-0003", "77-0002", "78-0001"]);
  assert.deepEqual(ids(C.sortRows(rows, "gaia", 1)), ["1-0001", "10226-0001", "77-0002", "8545-0003", "78-0001"], "no match, match, not checked");
  assert.deepEqual(ids(C.sortRows(rows, "score", -1)), ["1-0001", "10226-0001", "78-0001", "8545-0003", "77-0002"]);
  assert.deepEqual(ids(C.sortRows(rows, "visits", -1)).slice(0, 2), ["8545-0003", "1-0001"]);
  assert.deepEqual(ids(C.sortRows(rows, "id", 1)), ["1-0001", "10226-0001", "77-0002", "78-0001", "8545-0003"]);
  assert.deepEqual(ids(C.sortRows(rows, "pa", 1)), ["77-0002", "78-0001", "8545-0003", "1-0001", "10226-0001"]);
  assert.deepEqual(ids(C.sortRows(rows, "nonsense")), ids(rows), "unknown key: rank order");
  assert.deepEqual(ids(rows), ["1-0001", "8545-0003", "10226-0001", "77-0002", "78-0001"], "the input is not changed");
});

test("Gaia result in words", () => {
  assert.equal(C.gaiaText(rows[1].gaia), "Match · 0.4″");
  assert.equal(C.gaiaText(rows[0].gaia), "No match");
  assert.equal(C.gaiaText(rows[4].gaia), "Not checked");
  assert.equal(C.gaiaText(undefined), "Not checked");
});

// ---------- the track ----------
const line = (n, vx, vy, noise = 0) => {   // vx, vy in arcsec/yr; RA/Dec around (100, -30)
  const cd = Math.cos(-30 * Math.PI / 180);
  return { ra: 100, dec: -30, track: Array.from({ length: n }, (_, i) => { const t = 2014 + 0.5 * i, e = noise * (i % 2 ? 1 : -1); return [t, 100 + (vx * (t - 2019) + e) / 3600 / cd, -30 + (vy * (t - 2019) + e) / 3600]; }) };
};

test("straight-line fit recovers the motion of a clean track", () => {
  const m = line(21, -8.123, 0.673), { xs, ys, ts } = C.trackOffsets(C.trackPoints(m)), f = C.fitLine(ts, xs, ys);
  near(f.vx, -8.123, 1e-6, "east motion"); near(f.vy, 0.673, 1e-6, "north motion"); near(f.rms, 0, 1e-6, "no scatter");
  assert.equal(C.fitLine([2020], [0], [0]), null);
  assert.equal(C.fitLine([2020, 2020], [0, 1], [0, 1]), null, "all at one epoch: no line");
});

test("the track plot has one dot per visit, year labels, a fit line, and east on the left", () => {
  const m = line(19, 3, 0, 0.2), out = C.trackSvg(m);
  assert.equal(out.n, 19);
  assert.equal((out.svg.match(/<circle class="tp"/g) || []).length, 19);
  assert.match(out.svg, />2014\.0</); assert.match(out.svg, />2023\.0</);
  assert.match(out.svg, /class="fit"/); assert.match(out.svg, /east/);
  assert.doesNotMatch(out.svg, /NaN|Infinity/);
  assert.ok(out.points[18].x < out.points[0].x, "moving east (RA increasing) goes left");
  near(out.fit.rms, 0.2 * Math.SQRT2, 0.005, "scatter of ±0.2″ in both axes");
  const shuffled = { ...m, track: m.track.slice().reverse() };
  assert.equal(C.trackSvg(shuffled).svg, out.svg, "points are sorted by epoch first");
  assert.equal(C.trackSvg({ track: [[2014, 1, 1]] }).svg, "");
  assert.equal(C.trackSvg({}).n, 0);
});

test("a track across RA 0h is not torn apart", () => {
  const m = { ra: 0, dec: 10, track: [[2014, 359.9999, 10], [2019, 0.0001, 10], [2024, 0.0003, 10]] };
  const { xs } = C.trackOffsets(C.trackPoints(m));
  assert.ok(Math.max(...xs) - Math.min(...xs) < 1.5, `span ${Math.max(...xs) - Math.min(...xs)}″`);
});

// ---------- validation results, whatever the exact field names ----------
test("validation: the contract-style shape", () => {
  const v = C.normValidation(require("./fixtures/survey/summary.json").validation);
  assert.equal(v.byPm.length, 6); assert.equal(v.byMag.length, 6);
  assert.equal(v.byPm[0].label, "0.15–0.3"); near(v.byPm[0].completeness, 0.55, 1e-9, "first bin");
  near(v.overall, 2000 / 2400, 1e-9, "overall");
  assert.equal(v.fp.n, 2); assert.equal(v.fp.tiles, 8);
  assert.equal(v.known.length, 9);
  assert.deepEqual(v.known.filter((k) => !k.recovered).map((k) => k.name), ["61 Cygni A"]);
});

test("validation: other likely shapes (bins with counts only, known movers split into recovered/missed)", () => {
  const v = C.normValidation({
    completeness_vs_pm: [{ pm_min: 150, pm_max: 500, n_injected: 50, n_recovered: 20 }, { pm: 2000, fraction: 0.9 }],
    completeness_vs_mag: [{ mag_min: 10, mag_max: 12, injected: 10, recovered: 9 }],
    false_positives: 3,
    known_movers: { recovered: [{ name: "Barnard's Star", pm_expected: 10393, pm_meas: 10380 }], missed: [{ name: "Proxima", reason: "saturated" }] },
  });
  assert.deepEqual(v.byPm.map((b) => [b.label, b.completeness]), [["0.15–0.5", 0.4], ["2", 0.9]]);
  assert.deepEqual(v.byMag.map((b) => [b.label, b.completeness]), [["10–12", 0.9]]);
  assert.equal(v.fp.n, 3);
  assert.deepEqual(v.known.map((k) => [k.name, k.recovered, k.note]), [["Barnard's Star", true, ""], ["Proxima", false, "saturated"]]);
  assert.equal(C.normValidation(null), null);
  assert.equal(C.normValidation("x"), null);
});

test("tiles list: arrays or objects, bad entries dropped", () => {
  assert.deepEqual(C.normTiles([[8545, 12, 0], { k5: 10226, movers: 3, unexplained: 1 }, [99999, 1, 1], ["x"], null, { k5: 5, n_movers: 2 }]),
    [{ k5: 8545, movers: 12, unexplained: 0 }, { k5: 10226, movers: 3, unexplained: 1 }, { k5: 5, movers: 2, unexplained: 0 }]);
  assert.deepEqual(C.normTiles(undefined), []);
});

// ---------- investigate links ----------
test("investigate links carry the candidate's coordinates", () => {
  const L = C.links({ ra: 133.781801, dec: -7.243522, pm: 8150 });
  assert.equal(L.map, "observatory.html?ra=133.78180&dec=-7.24352");
  assert.equal(L.webb, L.map, "the console has no Webb deep link: same sky map");
  assert.equal(L.byw, "https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9");
  assert.equal(L.radiusArcmin, 5, "26 years at 8.15″/yr is 3.5′, rounded up with margin");
  assert.equal(L.simbad, "https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=133.78180%20-7.24352&Radius=5&Radius.unit=arcmin");
  assert.match(C.links({ ra: 10, dec: 5, pm: 200 }).simbad, /Coord=10\.00000%20%2B5\.00000&Radius=1&/);
  assert.equal(C.copyText({ ra: 77.95994, dec: -45.04381 }), "05h11m50.39s -45d02m37.7s (RA 77.95994°, Dec -45.04381°)");
});
