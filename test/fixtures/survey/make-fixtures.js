// Builds the SAMPLE survey results used by the page tests (test/fixtures/survey/) and shown on app/survey.html,
// with a "sample data" banner, until a real run of pipeline/survey/run.py writes app/data/survey/.
// Shapes follow docs/survey-contract.md. Deterministic: running it again gives the same files.
//   node test/fixtures/survey/make-fixtures.js --write          writes the fixtures
//   node test/fixtures/survey/make-fixtures.js --write --app    also copies them to app/data/survey/ if no results are there yet
// Without --write it only prints what it would make (node --test runs every .js file under test/, and must not rewrite them).
// Everything here is made up except the three real stars it borrows positions and motions from (as given in the
// contract: Kapteyn's Star, WISE 0855-0714, Barnard's Star), so the page has recognisable rows to show.
"use strict";
const fs = require("node:fs"), path = require("node:path");
const C = require("../../../app/survey.js");

let seed = 20261115;
const rnd = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const gauss = () => Math.sqrt(-2 * Math.log(1 - rnd())) * Math.cos(2 * Math.PI * rnd());
const poisson = (lam) => { let k = 0, p = 1; const L = Math.exp(-lam); do { k++; p *= rnd(); } while (p > L); return k - 1; };
const r = (v, d) => Math.round(v * 10 ** d) / 10 ** d;
const D2R = Math.PI / 180;

// galactic latitude of an RA/Dec (to make the Milky Way plane busier)
function galB(ra, dec) {
  const v = [Math.cos(dec * D2R) * Math.cos(ra * D2R), Math.cos(dec * D2R) * Math.sin(ra * D2R), Math.sin(dec * D2R)];
  return Math.asin(-0.867666149 * v[0] - 0.1980763734 * v[1] + 0.4559837762 * v[2]) / D2R;
}

// ---------- tiles: the nine validation tiles plus a random sample of the sky ----------
const VALIDATION = { 7945: "Barnard's Star", 8545: "Kapteyn's Star", 10226: "WISE 0855-0714", 9509: "Luhman 16", 6865: "Wolf 359",
  1355: "Lalande 21185", 10397: "Proxima Centauri", 3325: "61 Cygni", 11391: "Epsilon Indi" };
const N_TILES = 640;
const chosen = new Set(Object.keys(VALIDATION).map(Number));
while (chosen.size < N_TILES) chosen.add(Math.floor(rnd() * C.N_TILES));
const tiles = [...chosen].sort((a, b) => a - b).map((k5) => {
  const c = C.pix2ang(k5), b = Math.abs(galB(c.ra, c.dec)), dens = 1 + Math.exp(-b / 10);
  const det = Math.round(11e6 * dens * (0.9 + 0.2 * rnd()));
  const good = Math.round(det * (0.68 + 0.06 * rnd()));
  const vs = Math.round(good / (5.5 + rnd())), tracks = Math.round(vs / (14 + 4 * rnd()));
  let movers = poisson(11 * (1 + 0.4 * Math.exp(-b / 15))), unex = Math.min(movers, poisson(0.18));
  if (k5 === 10226) { movers = Math.max(movers, 3); unex = Math.max(unex, 1); }   // WISE 0855's tile
  if (VALIDATION[k5]) movers = Math.max(movers, 1);
  return { k5, det, good, vs, tracks, movers, unex };
});

// ---------- one mover ----------
let gaiaId = 4.1e18;
function epochs(n) {
  const phase = rnd() * 0.5, all = [];
  for (let i = 0; i < 22; i++) { const t = 2013.95 + phase + 0.5 * i + 0.02 * gauss(); if (t < 2024.6) all.push(t); }
  while (all.length > n) all.splice(Math.floor(rnd() * all.length), 1);
  return all;
}
function mover({ id, k5, ra, dec, refEpoch, pmra, pmdec, w1, w2, nVisits, cls, gaia, chi2r, flags = [] }) {
  const ts = epochs(nVisits), sig = 0.08 + 0.06 * 10 ** (0.25 * (w2 - 12));   // arcsec per visit
  const cd = Math.cos(dec * D2R);
  const track = ts.map((t) => [r(t, 3), r(ra + ((pmra * (t - refEpoch)) / 3.6e6 + (sig * gauss()) / 3600) / cd, 6), r(dec + (pmdec * (t - refEpoch)) / 3.6e6 + (sig * gauss()) / 3600, 6)]);
  if (cls === "likely artefact") track.forEach((p, i) => { if (i % 3 === 1) { p[1] = r(p[1] + (1.5 * gauss()) / 3600 / cd, 6); p[2] = r(p[2] + (1.5 * gauss()) / 3600, 6); } });
  const e0 = ts.reduce((a, b) => a + b, 0) / ts.length, span = ts[ts.length - 1] - ts[0];
  const pmErr = Math.max(0.8, ((sig * Math.sqrt(12)) / (span * Math.sqrt(ts.length))) * 1000);
  const m = {
    id, k5, ra: r(ra + (pmra * (e0 - refEpoch)) / 3.6e6 / cd, 6), dec: r(dec + (pmdec * (e0 - refEpoch)) / 3.6e6, 6), epoch: r(e0, 2),
    pmra: r(pmra + pmErr * gauss() * 0.7, 1), pmdec: r(pmdec + pmErr * gauss() * 0.7, 1), pm: 0, pm_err: r(pmErr, 1), pm_snr: 0,
    chi2r: r(chi2r, 2), n_visits: ts.length, span_yr: r(span, 1), w1: w1 === null ? null : r(w1, 2), w2: r(w2, 2),
    w1w2: w1 === null ? null : r(w1 - w2, 2), plx: null, plx_err: null, track, flags, gaia,
  };
  m.pm = r(Math.hypot(m.pmra, m.pmdec), 1);
  m.pm_snr = r(m.pm / m.pm_err, 1);
  return m;
}
function scoreOf(m, cls) {
  const g = m.gaia, reasons = [];
  let s = 0;
  if (g.checked === false) reasons.push("Gaia not checked: the archive did not answer during the run");
  else if (g.match) { s -= 1.5; reasons.push(`Matches Gaia DR3 ${g.source_id} (${g.sep_arcsec.toFixed(1)}″ away): a known star`); }
  else { s += 1.5; reasons.push("No Gaia DR3 source within 3″ of where it should be"); }
  s += 0.4 * Math.log10(Math.max(1, m.pm_snr));
  reasons.push(`Moves ${(m.pm / 1000).toFixed(m.pm < 1000 ? 3 : 2)}″/yr, ${Math.round(m.pm_snr)} times its uncertainty`);
  if (m.w1w2 === null) { s += 0.8; reasons.push("Not detected in W1: redder than W1 can measure"); }
  else if (m.w1w2 >= 2) { s += 1.2; reasons.push(`Extremely red: W1−W2 = ${m.w1w2.toFixed(2)}`); }
  else if (m.w1w2 >= 0.5) { s += 0.7; reasons.push(`Red: W1−W2 = ${m.w1w2.toFixed(2)}, the colour of a cold brown dwarf`); }
  s += 0.04 * m.n_visits + 0.05 * m.span_yr;
  reasons.push(`Seen in ${m.n_visits} visits over ${m.span_yr.toFixed(1)} years`);
  if (m.chi2r > 3) { s -= 0.3 * (m.chi2r - 1.5); reasons.push(`Poor straight-line fit (χ²ᵣ ${m.chi2r.toFixed(1)})`); }
  else reasons.push(`Clean straight-line fit (χ²ᵣ ${m.chi2r.toFixed(2)})`);
  if (m.w2 < 6) { s -= 0.8; reasons.push(`Very bright (W2 ${m.w2.toFixed(1)}): may be saturated`); }
  if (cls === "likely artefact") { s -= 1.5; reasons.push("Track runs along the NEOWISE scan direction, like a detector artefact"); }
  return { score: r(s, 2), reasons };
}

const cands = [];
const counter = new Map();
const nextId = (k5) => { const n = (counter.get(k5) || 0) + 1; counter.set(k5, n); return `${k5}-${String(n).padStart(4, "0")}`; };
const inside = (k5) => C.tilePoint(k5, 0.08 + 0.84 * rnd(), 0.08 + 0.84 * rnd());

// real stars (positions and motions as given in docs/survey-contract.md)
counter.set(8545, 2);
cands.push(["known (Gaia)", mover({ id: nextId(8545), k5: 8545, ra: 77.95994, dec: -45.04381, refEpoch: 2016.0, pmra: 6491.2, pmdec: -5708.6, w1: 6.1, w2: 5.8, nVisits: 21, cls: "known (Gaia)", chi2r: 1.3,
  gaia: { checked: true, match: true, source_id: "4810594479418041856", sep_arcsec: 0.4, pm: 8644.0, g: 8.06 } })]);
cands.push(["unexplained", mover({ id: nextId(10226), k5: 10226, ra: 133.7864, dec: -7.2439, refEpoch: 2017.0, pmra: -8123, pmdec: 673, w1: null, w2: 14.0, nVisits: 19, cls: "unexplained", chi2r: 1.1,
  gaia: { checked: true, match: false, source_id: null, sep_arcsec: null, pm: null, g: null } })]);
cands.push(["known (Gaia)", mover({ id: nextId(7945), k5: 7945, ra: 269.4485, dec: 4.7394, refEpoch: 2016.0, pmra: -801.6, pmdec: 10362.4, w1: 4.0, w2: 3.9, nVisits: 20, cls: "known (Gaia)", chi2r: 2.1,
  gaia: { checked: true, match: true, source_id: "4472832130942575872", sep_arcsec: 0.6, pm: 10393.3, g: 8.19 } })]);

// made-up movers
const pmDraw = (lo, hi) => lo * (hi / lo) ** rnd();
for (const t of tiles) {
  const need = t.unex - cands.filter(([c, m]) => c === "unexplained" && m.k5 === t.k5).length;
  for (let i = 0; i < need; i++) {
    const p = inside(t.k5), pm = pmDraw(150, 1800), pa = rnd() * 2 * Math.PI, w2 = 12.5 + 3 * rnd();
    const color = rnd() < 0.2 ? null : rnd() < 0.55 ? 0.5 + 2.2 * rnd() : 0.05 + 0.45 * rnd();
    cands.push(["unexplained", mover({ id: nextId(t.k5), k5: t.k5, ra: p.ra, dec: p.dec, refEpoch: 2019.3, pmra: pm * Math.sin(pa), pmdec: pm * Math.cos(pa),
      w1: color === null ? null : w2 + color, w2, nVisits: 8 + Math.floor(rnd() * 14), cls: "unexplained", chi2r: 0.8 + 0.9 * rnd(),
      gaia: { checked: true, match: false, source_id: null, sep_arcsec: null, pm: null, g: null } })]);
  }
}
const withMovers = tiles.filter((t) => t.movers > 0);
const extra = (cls, n, make) => { for (let i = 0; i < n; i++) { const t = withMovers[Math.floor(rnd() * withMovers.length)]; cands.push([cls, make(t)]); } };
extra("known (Gaia)", 110, (t) => {
  const p = inside(t.k5), pm = pmDraw(150, 3000), pa = rnd() * 2 * Math.PI, w2 = 6.5 + 6 * rnd(), w1w2 = 0.02 + 0.3 * rnd();
  gaiaId += Math.floor(rnd() * 1e15);
  return mover({ id: nextId(t.k5), k5: t.k5, ra: p.ra, dec: p.dec, refEpoch: 2019.3, pmra: pm * Math.sin(pa), pmdec: pm * Math.cos(pa), w1: w2 + w1w2, w2,
    nVisits: 14 + Math.floor(rnd() * 8), cls: "known (Gaia)", chi2r: 0.8 + 0.8 * rnd(),
    gaia: { checked: true, match: true, source_id: String(gaiaId), sep_arcsec: r(0.1 + 1.2 * rnd(), 2), pm: r(pm * (1 + 0.01 * gauss()), 1), g: r(w2 + 1.2 + 1.5 * rnd(), 2) } });
});
extra("likely artefact", 12, (t) => {
  const p = inside(t.k5), pm = pmDraw(400, 6000), pa = rnd() * 2 * Math.PI, w2 = 9 + 5 * rnd();
  return mover({ id: nextId(t.k5), k5: t.k5, ra: p.ra, dec: p.dec, refEpoch: 2019.3, pmra: pm * Math.sin(pa), pmdec: pm * Math.cos(pa), w1: w2 + 0.4 * rnd(), w2,
    nVisits: 6 + Math.floor(rnd() * 3), cls: "likely artefact", chi2r: 8 + 30 * rnd(), flags: ["scan-aligned", "high chi2r"],
    gaia: { checked: true, match: false, source_id: null, sep_arcsec: null, pm: null, g: null } });
});
extra("not checked", 8, (t) => {
  const p = inside(t.k5), pm = pmDraw(150, 2000), pa = rnd() * 2 * Math.PI, w2 = 8 + 6 * rnd();
  return mover({ id: nextId(t.k5), k5: t.k5, ra: p.ra, dec: p.dec, refEpoch: 2019.3, pmra: pm * Math.sin(pa), pmdec: pm * Math.cos(pa), w1: w2 + 0.6 * rnd(), w2,
    nVisits: 10 + Math.floor(rnd() * 10), cls: "not checked", chi2r: 0.9 + 0.8 * rnd(), gaia: { checked: false, match: false, source_id: null, sep_arcsec: null, pm: null, g: null } });
});

// rank: score, reasons, class, rank (contract order of keys after the mover's own)
const ranked = cands.map(([cls, m]) => ({ ...m, ...scoreOf(m, cls), class: cls })).sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
ranked.forEach((m, i) => (m.rank = i + 1));

// ---------- summary ----------
const sum = (k) => tiles.reduce((a, t) => a + t[k], 0);
const unexplained = ranked.filter((m) => m.class === "unexplained").length;
const perTile = new Map();
for (const m of ranked) if (m.class === "unexplained") perTile.set(m.k5, (perTile.get(m.k5) || 0) + 1);
const rowsIn = new Map();
for (const m of ranked) rowsIn.set(m.k5, (rowsIn.get(m.k5) || 0) + 1);
for (const t of tiles) { t.unex = perTile.get(t.k5) || 0; t.movers = Math.max(t.movers, rowsIn.get(t.k5) || 0); }
const tph = 78, hours = N_TILES / tph, detections = sum("det");
const pmBins = [[150, 300, 0.55], [300, 600, 0.84], [600, 1200, 0.92], [1200, 3000, 0.95], [3000, 6000, 0.93], [6000, 12000, 0.81]];
const magBins = [[6, 9, 0.7], [9, 11, 0.98], [11, 12.5, 0.97], [12.5, 13.5, 0.93], [13.5, 14.5, 0.84], [14.5, 15.5, 0.58]];
const known = [
  ["Barnard's Star", 10393, true], ["Kapteyn's Star", 8644, true], ["WISE 0855-0714", 8151, true], ["Luhman 16", 2790, true], ["Wolf 359", 4696, true],
  ["Lalande 21185", 4807, true], ["Proxima Centauri", 3859, true], ["61 Cygni A", 5281, false], ["Epsilon Indi A", 4704, true],
];
const summary = {
  demo: true,
  generated: "2026-11-15T08:42:10Z",
  status: "done",
  tiles_done: N_TILES, tiles_total: N_TILES,
  sky_fraction: r(N_TILES / C.N_TILES, 6), sky_deg2: r(N_TILES * C.TILE_AREA_DEG2, 1),
  detections, good_detections: sum("good"), visit_sources: sum("vs"), tracks: sum("tracks"), movers: sum("movers"), unexplained,
  runtime_hours: r(hours, 2), tiles_per_hour: tph, detections_per_second: Math.round(detections / (hours * 3600)), min_pm: 150,
  tiles: tiles.map((t) => [t.k5, t.movers, t.unex]),
  validation: {
    injection: {
      n_injected: 2400, n_recovered: 2000, pm_error_median: 5.2, pm_rel_error_median: 0.011,
      by_pm: pmBins.map(([lo, hi, c]) => ({ lo, hi, n: 400, recovered: Math.round(400 * c), completeness: c })),
      by_mag: magBins.map(([lo, hi, c]) => ({ lo, hi, n: 400, recovered: Math.round(400 * c), completeness: c })),
    },
    false_positives: { n: 2, tiles: 8, note: "Real tiles with the visit dates shuffled, so nothing truly moves" },
    known: known.map(([name, pm, found]) => ({ name, recovered: found, pm_true: pm, pm_measured: found ? r(pm * (1 + 0.004 * gauss()), 1) : null,
      note: found ? "" : "Saturated (W2 about 2.4): removed by the bright-star cut" })),
  },
  method: "Each HEALPix order-5 tile is read year by year from the NEOWISE-R single-exposure source table. Quality cuts remove "
    + "artefact-flagged and low signal-to-noise detections. Detections are grouped into visits (one every six months), averaged per "
    + "source per visit, and linked across visits into tracks: slow sources by position, fast ones (up to 12″ a year) by searching "
    + "for straight-line motion. A weighted straight-line fit gives each track's motion; tracks moving at least 0.15″ a year, at five "
    + "times their uncertainty or more, over at least six visits are movers. Movers are compared with Gaia DR3 stars moved to the "
    + "same date, then scored and ranked.",
  limits: [
    "Motions slower than 0.15″ a year are not searched for: single NEOWISE positions are too coarse to measure them over ten years.",
    "Objects faster than about 12″ a year move too far between visits to be linked.",
    "Sources fainter than about W2 = 15.5 are rarely detected in single NEOWISE exposures, so the coldest, faintest objects are missed.",
    "Stars brighter than about W2 = 6 saturate; their positions are less reliable.",
    "Crowded fields near the Milky Way plane cause more false links.",
    "The Gaia check uses a 3″ radius after moving Gaia's stars to the same date; a star with a poor Gaia motion can look unexplained.",
  ],
};
const leaderboard = { demo: true, generated: summary.generated, n_candidates: summary.movers, candidates: ranked };

// ---------- write ----------
const lines = (o, key) => {   // one array element per line, so diffs stay readable
  const head = JSON.stringify({ ...o, [key]: "@@" }, null, 1).replace(/\n\s*/g, " ");
  return head.replace('"@@"', "[\n" + o[key].map((x) => JSON.stringify(x)).join(",\n") + "\n]") + "\n";
};
const here = __dirname, app = path.join(here, "..", "..", "..", "app", "data", "survey");
if (process.argv.includes("--write")) {
  fs.writeFileSync(path.join(here, "summary.json"), lines(summary, "tiles"));
  fs.writeFileSync(path.join(here, "leaderboard.json"), lines(leaderboard, "candidates"));
}
if (process.argv.includes("--write") && process.argv.includes("--app")) {
  fs.mkdirSync(app, { recursive: true });
  for (const f of ["summary.json", "leaderboard.json"]) {
    const to = path.join(app, f);
    if (fs.existsSync(to)) console.log(`kept ${to} (already there)`);
    else { fs.copyFileSync(path.join(here, f), to); console.log(`wrote ${to}`); }
  }
}
console.log(`${N_TILES} tiles, ${summary.movers} movers, ${ranked.length} candidates (${unexplained} unexplained), ${detections.toLocaleString("en-US")} detections`);
