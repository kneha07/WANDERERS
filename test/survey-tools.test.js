// Sky Survey tools (app/surveytools.js and the new helpers in app/survey.js): positions moved to any date, links to
// other archives at the right date, CSV/JSON export, the URL form of the filters and the high-confidence preset.
// node --test test/survey-tools.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../app/surveytools.js");
const C = require("../app/survey.js");
const AladinLink = require("../app/aladinlink.js");

const WISE0855 = { id: "10226-0001", k5: 10226, ra: 133.781801, dec: -7.243522, epoch: 2019.02, pmra: -8121.8, pmdec: 676, pm: 8149.9,
  pm_err: 20.4, pm_snr: 399.5, n_visits: 19, span_yr: 10.5, w1: null, w2: 14, w1w2: null, class: "unexplained", score: 4.1, rank: 1,
  gaia: { checked: true, match: false, source_id: null, sep_arcsec: null }, flags: ["fast_search"] };
const KAPTEYN = { id: "8545-0003", k5: 8545, ra: 77.95994, dec: -45.04381, epoch: 2016.0, pmra: 6491.2, pmdec: -5708.6, pm: 8644.0, pm_err: 4.1,
  class: "known (Gaia)", gaia: { checked: true, match: true, source_id: "4810594479418041856", sep_arcsec: 0.4 } };
const NOW = 2026.5;
const close = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ""} ${a} vs ${b} (±${tol})`);
const q = (href) => new URL(href).searchParams;

// ---------- dates and positions ----------
test("decimal years: New Year, mid-year and the last moment of a leap year", () => {
  assert.equal(T.decimalYear(new Date(Date.UTC(2026, 0, 1))), 2026);
  close(T.decimalYear(new Date(Date.UTC(2026, 6, 2, 12))), 2026.5, 0.001);
  close(T.decimalYear(new Date(Date.UTC(2024, 11, 31, 23, 59, 59))), 2025, 1e-6);
  close(T.decimalYear(), 2026, 30, "now");
});

test("propagation: Kapteyn's Star from Gaia's 2016.0 back to J2000 matches the tangent-plane offsets", () => {
  const p = T.propagate(KAPTEYN.ra, KAPTEYN.dec, KAPTEYN.pmra, KAPTEYN.pmdec, -16);
  close((p.dec - KAPTEYN.dec) * 3600, 5708.6 * 16 / 1000, 0.05, "Dec moved 91.3″ north");
  close((p.ra - KAPTEYN.ra) * 3600 * Math.cos(KAPTEYN.dec * Math.PI / 180), -6491.2 * 16 / 1000, 0.1, "RA moved 103.9″ west");
  const back = T.propagate(p.ra, p.dec, KAPTEYN.pmra, KAPTEYN.pmdec, 16);
  close(T.sepArcsec(back, KAPTEYN), 0, 0.15, "and forward again (the motion frame turns slightly along the way)");
});

test("propagation wraps RA through 0/360 both ways", () => {
  const e = T.propagate(359.9999, 10, 1000, 0, 1);
  assert.ok(e.ra >= 0 && e.ra < 0.001, `east across 0h: ${e.ra}`);
  close(T.sepArcsec(e, { ra: 359.9999, dec: 10 }), 1, 1e-4);
  const w = T.propagate(0.0001, -10, -1000, 0, 1);
  assert.ok(w.ra > 359.999 && w.ra < 360, `west across 0h: ${w.ra}`);
});

test("propagation over a pole flips RA by 180° and never leaves ±90°", () => {
  const p = T.propagate(30, 89.99995, 0, 1000, 0.36);
  close(p.ra, 210, 1e-6); close(p.dec, 90 - 0.18 / 3600, 1e-8);
  const s = T.propagate(100, -89.9999, 0, -2000, 1);
  assert.ok(s.dec >= -90 && s.dec < -89.999 && Math.abs(s.ra - 280) < 1e-6);
});

test("positionAt: moved with the motion, uncertainty from pm_err; motionless or dateless rows stay put", () => {
  const p = T.positionAt(WISE0855, NOW);
  assert.equal(p.moved, true); close(p.dt, NOW - 2019.02, 1e-9); close(p.err, (NOW - 2019.02) * 20.4 / 1000, 1e-9);
  close(T.sepArcsec(p, WISE0855), 8149.9 * (NOW - 2019.02) / 1000, 0.05, "8.15″/yr for 7.5 years");
  assert.ok(p.ra < WISE0855.ra, "it moves west");
  const still = T.positionAt({ ra: 370, dec: 5 }, NOW);
  assert.deepEqual([still.ra, still.dec, still.moved, still.err], [10, 5, false, null]);
  assert.equal(T.positionAt({ ...WISE0855, pm_err: null }, NOW).err, null);
  assert.equal(T.positionAt({ dec: 5 }, NOW), null);
});

test("timeline: measured, J2000, Gaia 2016.0, today and 2030, in that order", () => {
  const rows = T.timeline(WISE0855, NOW);
  assert.deepEqual(rows.map((r) => r.key), ["neowise", "j2000", "gaia", "now", "later"]);
  assert.deepEqual(rows.map((r) => r.epoch), [2019.02, 2000, 2016, NOW, 2030]);
  assert.equal(rows[0].ra, WISE0855.ra); assert.equal(rows[0].dec, WISE0855.dec);
  close(T.sepArcsec(rows[1], rows[4]), 8149.9 * 30 / 1000, 0.5, "30 years of motion between J2000 and 2030");
  assert.ok(rows[4].err > rows[3].err, "further from the measurement, larger uncertainty");
});

// ---------- investigate links ----------
test("sky viewers use today's position, catalogues J2000, the Gaia search 2016.0", () => {
  const A = T.archiveLinks(WISE0855, { now: NOW });
  const now = T.positionAt(WISE0855, NOW), j = T.positionAt(WISE0855, 2000), g = T.positionAt(WISE0855, 2016);
  const by = Object.fromEntries(A.links.map((l) => [l.key, l]));
  assert.deepEqual(Object.keys(by), ["finder", "aladin", "legacy", "simbad", "vizier", "gaia"]);
  const [fra, fdec] = q(by.finder.href).get("UserTargetWorldPt").split(";");
  close(+fra, now.ra, 1e-6); close(+fdec, now.dec, 1e-6);
  close(+q(by.aladin.href).get("ra"), now.ra, 1e-5); close(+q(by.legacy.href).get("dec"), now.dec, 1e-6);
  const coord = q(by.simbad.href).get("Coord").split(" ").map(Number);
  close(coord[0], j.ra, 1e-6); close(coord[1], j.dec, 1e-6);
  const vc = q(by.vizier.href).get("-c").split(" ").map(Number), gc = q(by.gaia.href).get("-c").split(" ").map(Number);
  close(vc[0], j.ra, 1e-6); close(gc[0], g.ra, 1e-6); close(gc[1], g.dec, 1e-6);
  assert.ok(T.sepArcsec(j, now) > 200, "the two dates are minutes of arc apart for a fast mover");
  for (const l of A.links) assert.ok(l.when && l.note && l.label, l.key);
  assert.match(by.finder.when, /^today \(2026\.50\)$/); assert.match(by.simbad.when, /^J2000, \d+″ radius$/); assert.match(by.gaia.when, /^2016\.0/);
});

test("IRSA Finder Chart link: the documented getResult form, size in degrees, DSS to WISE", () => {
  const still = { ra: 10.5, dec: -20.25, pm: 0 };
  assert.equal(T.archiveLinks(still, { now: NOW }).links[0].href,
    "https://irsa.ipac.caltech.edu/applications/finderchart/servlet/api?mode=getResult&UserTargetWorldPt=10.500000;-20.250000;EQ_J2000&subsize=0.0333&survey=DSS,SDSS,2MASS,WISE");
  assert.equal(q(T.archiveLinks(WISE0855, { now: NOW }).links[0].href).get("subsize"), "0.1000", "a fast mover gets the widest (6′) chart");
});

test("Legacy Surveys link: ra, dec, DR10 layer, a mark on the spot, zoom by speed", () => {
  const href = T.archiveLinks({ ra: 150.1, dec: 2.2, pm: 0 }, { now: NOW }).links.find((l) => l.key === "legacy").href;
  assert.equal(href, "https://www.legacysurvey.org/viewer?ra=150.100000&dec=2.200000&layer=ls-dr10&zoom=16&mark=150.100000,2.200000");
  const zoom = (pm) => q(T.archiveLinks({ ra: 1, dec: 1, epoch: 2019, pmra: pm, pmdec: 0, pm }, { now: NOW }).links.find((l) => l.key === "legacy").href).get("zoom");
  assert.deepEqual([zoom(200), zoom(2000), zoom(9000)], ["16", "15", "14"]);
});

test("Aladin Lite link comes from the shared aladinlink.js helper, AllWISE colour, path-sized field", () => {
  const A = T.archiveLinks(WISE0855, { now: NOW }), now = T.positionAt(WISE0855, NOW);
  const fov = Math.round(2 * 8.1499 * (NOW - 2010) + 60);
  assert.equal(A.links.find((l) => l.key === "aladin").href, AladinLink.url({ ra: now.ra, dec: now.dec, fovArcsec: fov, survey: "P/allWISE/color" }));
  assert.equal(q(T.archiveLinks({ ra: 5, dec: 5 }, { now: NOW }).links[1].href).get("fov"), "0.0167", "a motionless one: 1′");
});

test("SIMBAD and VizieR: a + sign is encoded, a − sign is not; the radius covers the move's uncertainty", () => {
  const north = T.archiveLinks({ ra: 10, dec: 5, pm: 0 }, { now: NOW }).links;
  const simbad = north.find((l) => l.key === "simbad").href;
  assert.equal(simbad, "https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=10.000000%20%2B5.000000&CooFrame=ICRS&CooEpoch=2000&CooEqui=2000&Radius=5&Radius.unit=arcsec");
  assert.equal(north.find((l) => l.key === "vizier").href,
    "https://vizier.cds.unistra.fr/viz-bin/VizieR?-c=10.000000%20%2B5.000000&-c.eq=J2000&-c.rs=5&-out.add=_r&-sort=_r");
  assert.match(north.find((l) => l.key === "gaia").href, /^https:\/\/vizier\.cds\.unistra\.fr\/viz-bin\/VizieR-4\?-source=I\/355\/gaiadr3&-c=10\.000000%20%2B5\.000000&/);
  const south = T.archiveLinks(WISE0855, { now: NOW }).links.find((l) => l.key === "simbad").href;
  assert.match(south, /Coord=\d+\.\d{6}%20-7\.\d{6}&/);
  const r = +q(south).get("Radius");
  assert.equal(r, Math.ceil(5 + 3 * (2019.02 - 2000) * 20.4 / 1000 + 8.1499), "5″ + 3σ of 19 years × 20.4 mas/yr + a year of motion");
  assert.equal(T.coneArcsec({ err: 500 }), 120); assert.equal(T.coneArcsec(null), 5); assert.equal(T.coneArcsec({ err: 1 }, 2.5), 11);
});

test("links across RA 0h use the wrapped RA, never 360 or a negative number", () => {
  const m = { ra: 359.9999, dec: 1, epoch: 2019, pmra: 3000, pmdec: 0, pm: 3000, pm_err: 5 };
  const A = T.archiveLinks(m, { now: NOW });
  assert.ok(A.now.ra < 0.01, `today: ${A.now.ra}`);
  for (const l of A.links.filter((x) => x.at === "now")) assert.doesNotMatch(l.href, /ra=(-|359\.|360)|WorldPt=(-|359\.|360)/, l.key);
  assert.match(A.links.find((l) => l.key === "simbad").href, /Coord=359\.\d{6}%20/, "in 2000 it was still west of 0h");
});

test("every link is https, has no raw spaces or plus signs, and is null-safe", () => {
  for (const m of [WISE0855, KAPTEYN, { ra: 0, dec: -90 }, { ra: 180, dec: 90, epoch: 2019, pmra: 100, pmdec: 100 }]) {
    for (const l of T.archiveLinks(m, { now: NOW }).links) {
      assert.match(l.href, /^https:\/\//, l.key); assert.doesNotMatch(l.href, /[ +]/, l.key);
    }
  }
  assert.equal(T.archiveLinks({ id: "x" }, { now: NOW }), null);
});

test("the drawer's archive list opens each link in a new tab, safely, with escaped text", () => {
  const html = C.archiveListHtml(WISE0855, NOW);
  const links = [...html.matchAll(/<a href="([^"]+)" target="_blank" rel="noopener noreferrer">/g)];
  assert.equal(links.length, 6);
  for (const [, href] of links) assert.doesNotMatch(href, /&(?!amp;)/, "ampersands are escaped in the attribute");
  assert.match(html, /IRSA Finder Chart ↗<\/a><small>today \(2026\.50\) · /);
  assert.equal(C.archiveListHtml({ id: "no position" }, NOW), "<li>No position in the results file.</li>");
});

test("the drawer's year-by-year list: five dates, uncertainty after the move, sexagesimal too", () => {
  const html = C.whenHtml(WISE0855, NOW);
  assert.deepEqual([...html.matchAll(/data-when="(\w+)"/g)].map((m) => m[1]), ["neowise", "j2000", "gaia", "now", "later"]);
  assert.match(html, /<dt>Today \(predicted\) <small>2026\.50<\/small><\/dt>/);
  assert.match(html, /<dt>NEOWISE \(measured\) <small>2019\.02<\/small><\/dt><dd><span class="mono">RA 133\.78180°, Dec -7\.24352°/);
  assert.doesNotMatch(html.split('data-when="j2000"')[0], /±/, "no uncertainty on the measured position");
  assert.match(html, /data-when="later">.*± 0\.22″/, "11 years × 20.4 mas/yr");
});

test("promote command: the candidate id, nothing a shell could run", () => {
  assert.equal(C.promoteCommand("10226-0001"), "python pipeline/survey/promote.py --id 10226-0001");
  assert.equal(C.promoteCommand("1-1; rm -rf ~ `x` $(y)"), "python pipeline/survey/promote.py --id 1-1rm-rfxy");
});

// ---------- export ----------
const ROWS = [
  { ...WISE0855, duplicates: ["10227-0004"] },
  { ...KAPTEYN, rank: 2, score: 0.9, n_visits: 21, flags: ["saturated", "tile_edge"] },
  { id: '=HYPERLINK("x"),1', ra: 1, dec: -2, class: "likely artefact", flags: "crowded", gaia: { checked: false } },
  { id: "line\nbreak", rank: null, ra: NaN, dec: Infinity, class: "", gaia: null, flags: [] },
];

test("CSV: the agreed columns, one line per candidate, CRLF line ends", () => {
  const csv = T.toCSV(ROWS), lines = csv.split("\r\n");
  assert.equal(lines[0], "rank,id,k5,ra,dec,epoch,pm,pmra,pmdec,pm_err,pm_snr,w1,w2,w1w2,n_visits,span_yr,class,gaia_checked,gaia_match,gaia_source_id,gaia_sep_arcsec,score,flags,duplicates");
  assert.equal(lines[1], "1,10226-0001,10226,133.781801,-7.243522,2019.02,8149.9,-8121.8,676,20.4,399.5,,14,,19,10.5,unexplained,true,false,,,4.1,fast_search,10227-0004");
  assert.equal(lines[2], "2,8545-0003,8545,77.95994,-45.04381,2016,8644,6491.2,-5708.6,4.1,,,,,21,,known (Gaia),true,true,4810594479418041856,0.4,0.9,saturated;tile_edge,");
  assert.ok(csv.endsWith("\r\n")); assert.equal(lines.length, ROWS.length + 2);
});

test("CSV escaping: quotes doubled, commas and line breaks quoted, formulas defused, bad numbers empty", () => {
  const lines = T.toCSV(ROWS).split("\r\n");
  assert.equal(lines[3], `,"'=HYPERLINK(""x""),1",,1,-2,,,,,,,,,,,,likely artefact,false,,,,,crowded,`);
  assert.ok(T.toCSV([ROWS[3]]).includes(',"line\nbreak",,,,'), "a line break inside a field is quoted");
  assert.equal(T.csvCell("+1 555"), "'+1 555"); assert.equal(T.csvCell("@SUM(A1)"), "'@SUM(A1)"); assert.equal(T.csvCell(-7.5), "-7.5");
  assert.equal(T.csvCell('say "hi"'), '"say ""hi"""'); assert.equal(T.csvCell(null), ""); assert.equal(T.csvCell(NaN), "");
  assert.equal(T.csvCell(["a", "b,c"]), '"a;b,c"');
});

test("JSON export: metadata, the same columns, arrays kept as arrays, nulls for missing numbers", () => {
  const data = JSON.parse(T.toJSON(ROWS, { generated: "2026-11-15T08:42:10Z", filters: { cls: "all" }, sort: { key: "rank", dir: 1 }, url: "http://x/survey.html?red=1", exported: "2026-11-16T00:00:00Z" }));
  assert.equal(data.count, 4); assert.deepEqual(data.columns, T.EXPORT_COLUMNS);
  assert.equal(data.generated, "2026-11-15T08:42:10Z"); assert.equal(data.exported, "2026-11-16T00:00:00Z"); assert.equal(data.url, "http://x/survey.html?red=1");
  assert.deepEqual(Object.keys(data.candidates[0]), T.EXPORT_COLUMNS);
  assert.deepEqual(data.candidates[1].flags, ["saturated", "tile_edge"]); assert.deepEqual(data.candidates[0].duplicates, ["10227-0004"]);
  assert.equal(data.candidates[0].gaia_match, false); assert.equal(data.candidates[1].gaia_source_id, "4810594479418041856");
  assert.deepEqual([data.candidates[3].ra, data.candidates[3].dec, data.candidates[3].rank, data.candidates[3].class], [null, null, null, "not checked"]);
  assert.deepEqual(data.candidates[2].flags, ["crowded"]); assert.equal(data.candidates[2].gaia_checked, false);
  assert.match(T.toJSON([], {}), /"count": 0/);
});

test("export file names carry the results date and the number of rows", () => {
  assert.equal(T.exportName("csv", "2026-11-15T08:42:10Z", 12), "wanderers-survey-candidates-20261115-12.csv");
  assert.equal(T.exportName("json", undefined, 0), "wanderers-survey-candidates-0.json");
});

// ---------- filters ----------
test("flags: tile edge, crowded, saturated, and the likely-artefact class", () => {
  assert.equal(T.hasFlag({ flags: ["tile_edge"] }, "edge"), true); assert.equal(T.hasFlag({ flags: ["Edge of tile"] }, "edge"), true);
  assert.equal(T.hasFlag({ flags: ["crowded"] }, "crowded"), true); assert.equal(T.hasFlag({ flags: ["saturated"] }, "crowded"), false);
  assert.equal(T.hasFlag({ flags: ["saturated"] }, "saturated"), true); assert.equal(T.hasFlag({ flags: null }, "saturated"), false);
  assert.equal(T.hasFlag({ class: "likely artefact" }, "artefact"), true); assert.equal(T.hasFlag({ class: "unexplained" }, "artefact"), false);
});

test("applyFilters: min visits, min S/N and hidden flags narrow the list, combined with the old filters", () => {
  const rows = [
    { id: "a", class: "unexplained", pm: 500, n_visits: 20, pm_snr: 50, flags: [] },
    { id: "b", class: "unexplained", pm: 500, n_visits: 8, pm_snr: 50, flags: [] },
    { id: "c", class: "unexplained", pm: 500, n_visits: 20, pm_snr: 6, flags: [] },
    { id: "d", class: "known (Gaia)", pm: 500, n_visits: 20, pm_snr: 50, flags: ["tile_edge"] },
    { id: "e", class: "likely artefact", pm: 500, n_visits: 20, pm_snr: 50, flags: ["crowded", "saturated"] },
    { id: "f", class: "unexplained", pm: 500, n_visits: null, pm_snr: null, flags: [] },
  ];
  const f = { ...T.FILTER_DEFAULTS };
  const ids = (x) => C.applyFilters(rows, { ...f, ...x }).map((m) => m.id);
  assert.deepEqual(ids({}), ["a", "b", "c", "d", "e", "f"]);
  assert.deepEqual(ids({ minVisits: 12 }), ["a", "c", "d", "e"], "missing visits fail a minimum");
  assert.deepEqual(ids({ minSnr: 10 }), ["a", "b", "d", "e"]);
  assert.deepEqual(ids({ hide: ["edge"] }), ["a", "b", "c", "e", "f"]);
  assert.deepEqual(ids({ hide: ["crowded"] }), ["a", "b", "c", "d", "f"]);
  assert.deepEqual(ids({ hide: ["artefact"] }), ["a", "b", "c", "d", "f"]);
  assert.deepEqual(ids({ ...T.PRESETS.high, cls: "unexplained" }), ["a"]);
});

test("sorting by motion S/N, clearest first, missing last", () => {
  const rows = [{ id: "x", rank: 1, pm_snr: 5 }, { id: "y", rank: 2, pm_snr: null }, { id: "z", rank: 3, pm_snr: 80 }];
  assert.deepEqual(C.sortRows(rows, "snr").map((m) => m.id), ["z", "x", "y"]);
  assert.equal(C.sortDefaults().snr, -1); assert.equal(C.sortDefaults().rank, 1);
});

test("high-confidence preset: switches on, is recognised, switches off without touching other filters", () => {
  const f = { ...T.FILTER_DEFAULTS, cls: "unexplained", red: true, hide: [] };
  const on = T.togglePreset(f, "high");
  assert.deepEqual([on.minVisits, on.minSnr, on.hide], [12, 10, ["edge", "crowded", "saturated", "artefact"]]);
  assert.equal(on.cls, "unexplained"); assert.equal(on.red, true); assert.equal(T.isPreset(on, "high"), true);
  assert.equal(T.isPreset({ ...on, minVisits: 15 }, "high"), true, "stricter still counts");
  assert.equal(T.isPreset({ ...on, hide: ["edge"] }, "high"), false);
  const off = T.togglePreset(on, "high");
  assert.deepEqual([off.minVisits, off.minSnr, off.hide, off.cls], [0, 0, [], "unexplained"]);
  assert.notEqual(on.hide, T.PRESETS.high.hide, "the preset's own list is never shared");
});

test("URL round trip: every filter and the sort come back the same", () => {
  const f = { cls: "unexplained", minPm: 0.5, red: true, q: "8545-", tile: 8545, minVisits: 12, minSnr: 7.5, hide: ["saturated", "edge"] };
  const sorts = C.sortDefaults();
  for (const sort of [{ key: "snr", dir: -1 }, { key: "w1w2", dir: 1 }, { key: "rank", dir: -1 }, { key: "rank", dir: 1 }]) {
    const params = new URLSearchParams(T.toParams(f, sort, sorts));
    const back = T.fromParams(params, { classes: C.CLASSES, sorts, nTiles: 12288 });
    assert.deepEqual(back.f, { ...f, hide: ["edge", "saturated"] });
    assert.deepEqual(back.sort, sort.key === "rank" && sort.dir === 1 ? null : sort, JSON.stringify(sort));
  }
  assert.equal(new URLSearchParams(T.toParams(f, { key: "snr", dir: -1 }, sorts)).toString(),
    "class=unexplained&minpm=0.5&red=1&visits=12&snr=7.5&hide=edge%2Csaturated&q=8545-&tile=8545&sort=snr");
  assert.deepEqual(T.toParams({ ...T.FILTER_DEFAULTS }, { key: "rank", dir: 1 }, sorts), [], "defaults leave the address clean");
});

test("URL parameters: nonsense is ignored, a preset link expands, explicit values win", () => {
  const read = (s) => T.fromParams(new URLSearchParams(s), { classes: C.CLASSES, sorts: C.sortDefaults(), nTiles: 12288 });
  const bad = read("class=constructor&minpm=abc&visits=-3&snr=NaN&hide=bogus,__proto__&tile=99999&sort=toString&dir=up");
  assert.deepEqual(bad.f, { ...T.FILTER_DEFAULTS, hide: [] }); assert.equal(bad.sort, null);
  const p = read("preset=high");
  assert.deepEqual([p.f.minVisits, p.f.minSnr, p.f.hide.length], [12, 10, 4]);
  assert.equal(read("preset=high&visits=15").f.minVisits, 15);
  assert.deepEqual(read("preset=high&hide=").f.hide, [], "an explicit empty hide list wins");
  assert.equal(read("preset=nope").f.minVisits, 0);
  assert.deepEqual(read("sort=pm").sort, { key: "pm", dir: -1 }); assert.deepEqual(read("sort=pm&dir=asc").sort, { key: "pm", dir: 1 });
});
