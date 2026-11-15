// The SPHEREx 2025–26 parts of the Sky Survey page: the drawer section (verdict, offset, spectrum SVG with the
// methane band, indices in plain words), the "SPHEREx ✓" table badge, the "SPHEREx-confirmed only" filter (kept in
// the address) and the hero stat. node --test test/survey-spherex.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { openPage } = require("./fakepage");
const C = require("../app/survey.js");
const T = require("../app/surveytools.js");

const SUMMARY = { ...require("./fixtures/survey/summary.json"), spherex_checked: 40, spherex_confirmed: 7 };
const BASE = require("./fixtures/survey/leaderboard.json");
const UM = [0.79, 0.88, 0.97, 1.06, 1.17, 1.3, 1.43, 1.57, 1.74, 1.93, 2.11, 2.29, 2.61, 2.91, 3.25, 3.62, 3.9, 4.06, 4.2, 4.35, 4.5, 4.65, 4.79, 4.93];
const KEYS = ["checked", "detected", "confirmed", "snr", "offset_arcsec", "offset_err", "expected_offset", "at_predicted",
  "gone_from_2014", "old_snr", "w2_ratio", "epoch", "tile", "spectrum", "indices", "notes", "error"];
const sx = (o = {}) => ({ ...Object.fromEntries(KEYS.map((k) => [k, null])), checked: true, detected: true, confirmed: true, snr: 13.3,
  offset_arcsec: 3.83, offset_err: 3.16, expected_offset: 93.84, at_predicted: true, gone_from_2014: true, epoch: 2025.883, tile: 10226,
  spectrum: { um: UM, mjy: UM.map((u) => (u > 4 ? 0.6 : 0.1)), err: UM.map(() => 0.05) },
  indices: { w1w2: 2.26, w1w2_err: 0.3, w1w2_lim: false, ch4_depth: 0.4, ch4_err: 0.1, methane: true, peak_um: 4.5, hints: [] },
  notes: ["By 2025.9 it had moved into the neighbouring SPHEREx tile 10227"], error: null, ...o });
const CONFIRMED = ["10226-0001", "376-0001"];
function board() {
  const b = structuredClone(BASE);
  for (const m of b.candidates) {
    if (CONFIRMED.includes(m.id)) m.spherex = sx();
    else if (m.id === "9088-0001") m.spherex = sx({ confirmed: false, at_predicted: true, gone_from_2014: null, indices: null, notes: ["Too slow"] });
    else if (m.id === "4866-0002") m.spherex = sx({ checked: false, detected: null, confirmed: false, error: "network: timed out", spectrum: null, indices: null, notes: [] });
  }
  return b;
}
async function open(q = "", b = board()) {
  const p = openPage("survey.html", q, { files: { "data/survey/summary.json": SUMMARY, "data/survey/leaderboard.json": b } });
  await p.window.Survey.ready;
  return p;
}
const rowIds = (p) => [...p.$("candBody").innerHTML.matchAll(/<tr data-id="([^"]+)"/g)].map((m) => m[1]);
const check = (p, id, on) => { p.$(id).checked = on; p.fire(p.$(id), "change"); };
const target = (data) => ({ closest: () => ({ dataset: data }) });
const clickRow = (p, id) => p.$("candBody").dispatchEvent({ type: "click", target: target({ id }) });
const setVal = (p, id, v, ev = "change") => { p.$(id).value = v; p.fire(p.$(id), ev); };

// ---------- core helpers ----------
test("spherexConfirmed: only a checked, confirmed dict counts", () => {
  assert.equal(C.spherexConfirmed({ spherex: sx() }), true);
  assert.equal(C.spherexConfirmed({ spherex: sx({ confirmed: false }) }), false);
  assert.equal(C.spherexConfirmed({ spherex: sx({ checked: false }) }), false);
  assert.equal(C.spherexConfirmed({}), false);
  assert.equal(C.spherexConfirmed({ spherex: [1] }), false);
  assert.equal(C.spherexConfirmed(null), false);
});

test("spectrumSvg: one point and error bar per band, the methane band marked at 3.2–3.45 µm, axes 1–5 µm", () => {
  const svg = C.spectrumSvg(sx().spectrum);
  assert.equal((svg.match(/<circle class="sx-pt"/g) || []).length, 24);
  assert.equal((svg.match(/<line class="sx-err"/g) || []).length, 24);
  const rect = svg.match(/<rect class="sx-ch4" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"/);
  assert.ok(rect, "methane band");
  const X = (u) => 46 + ((u - 0.7) / (5.05 - 0.7)) * (400 - 46 - 10);
  assert.ok(Math.abs(Number(rect[1]) - X(3.2)) < 0.2 && Math.abs(Number(rect[2]) - (X(3.45) - X(3.2))) < 0.3);
  assert.match(svg, /CH₄/);
  for (const t of [1, 2, 3, 4, 5]) assert.match(svg, new RegExp(`text-anchor="middle">${t}</text>`));
  assert.match(svg, /role="img" aria-label="SPHEREx spectrum: 24 bands from 0\.79 to 4\.93 µm/);
  assert.doesNotMatch(svg, /NaN|undefined/);
});

test("spectrumSvg: gaps are skipped, fewer than two points draw nothing", () => {
  const sp = { um: [1, 2, 3, 4], mjy: [1, null, 2, "x"], err: [0.1, 0.1, null, 0.1] };
  const svg = C.spectrumSvg(sp);
  assert.equal((svg.match(/<circle/g) || []).length, 2);
  assert.equal((svg.match(/<line class="sx-err"/g) || []).length, 1);
  assert.equal(C.spectrumSvg({ um: [1], mjy: [1], err: [1] }), "");
  assert.equal(C.spectrumSvg(null), "");
  assert.doesNotMatch(C.spectrumSvg({ um: [1, 2], mjy: [-3, -3], err: [0, 0] }), /NaN/);
});

test("spherexHtml: confirmed — verdict, offset vs predicted, the 2014 spot, spectrum and indices in plain words", () => {
  const h = C.spherexHtml({ w1w2: 2.86, spherex: sx() });
  assert.match(h, /class="sx-verdict sx-ok">Seen again in 2025–26, where its NEOWISE motion predicts, and gone from its 2014 spot\./);
  assert.match(h, /3\.8″ ± 3\.2″/);
  assert.match(h, /Moved since 2014 \(predicted\)<\/dt><dd><span class="mono">93\.8″/);
  assert.match(h, /Its 2014 spot<\/dt><dd>empty now/);
  assert.match(h, /<svg class="d-spec"/);
  assert.match(h, /W1−W2 = 2\.3 ± 0\.3 \(NEOWISE: 2\.9\)/);
  assert.match(h, /Methane hint: the flux at 3\.3 µm sits 40 ± 10 % below/);
  assert.match(h, /brightest near 4\.5 µm, where cold brown dwarfs peak/);
  assert.match(h, /Hints, not a classification\./);
  assert.match(h, /moved into the neighbouring SPHEREx tile 10227/);
});

test("spherexHtml: the other verdicts, limits, and every unchecked reason", () => {
  assert.match(C.spherexHtml({ spherex: sx({ confirmed: false }) }), /sx-mid">A source is there, where predicted, but it moves too little/);
  assert.match(C.spherexHtml({ spherex: sx({ confirmed: false, at_predicted: false }) }), /sx-no">Not where its NEOWISE motion predicts/);
  assert.match(C.spherexHtml({ spherex: sx({ confirmed: false, at_predicted: null, detected: false, spectrum: null, indices: null }) }), /Not detected by SPHEREx/);
  const lim = C.spherexHtml({ spherex: sx({ indices: { w1w2: 2.6, w1w2_lim: true, ch4_depth: null, methane: null, peak_um: null } }) });
  assert.match(lim, /W1−W2 &gt; 2\.6\./);
  assert.match(C.spherexHtml({ spherex: sx({ checked: false, error: "network: timed out" }) }), /could not be reached for this candidate; it is tried again/);
  assert.match(C.spherexHtml({ spherex: sx({ checked: false, error: "time budget" }) }), /Still in the queue/);
  assert.match(C.spherexHtml({ spherex: sx({ checked: false, error: null, notes: ["Not looked up in SPHEREx: Gaia DR3 already explains it"] }) }), /Gaia DR3 already explains it/);
  assert.match(C.spherexHtml({}), /Not looked up in SPHEREx for this build\./);
});

test("spherexHtml escapes text from the results file", () => {
  const h = C.spherexHtml({ spherex: sx({ notes: ["<img src=x onerror=alert(1)>"] }) });
  assert.doesNotMatch(h, /<img/);
  assert.match(h, /&lt;img src=x/);
  assert.doesNotMatch(C.spherexHtml({ spherex: sx({ checked: false, error: "<b>x</b>" }) }), /<b>x/);
});

test("applyFilters: the spherex filter keeps confirmed rows only", () => {
  const rows = board().candidates;
  const f = { ...T.FILTER_DEFAULTS, spherex: true };
  assert.deepEqual(C.applyFilters(rows, f).map((m) => m.id).sort(), CONFIRMED.slice().sort());
  assert.equal(C.applyFilters(rows, { ...T.FILTER_DEFAULTS }).length, rows.length);
});

test("URL: spherex=1 is written and read back; nonsense is ignored", () => {
  assert.deepEqual(T.toParams({ ...T.FILTER_DEFAULTS, spherex: true }, null, {}), [["spherex", "1"]]);
  assert.equal(T.fromParams(new URLSearchParams("spherex=1"), {}).f.spherex, true);
  assert.equal(T.fromParams(new URLSearchParams("spherex=yes"), {}).f.spherex, false);
  assert.equal(T.FILTER_DEFAULTS.spherex, false);
});

// ---------- the page ----------
test("table: a SPHEREx ✓ badge on confirmed rows only", async () => {
  const p = await open();
  setVal(p, "pgSize", "1000");
  const html = p.$("candBody").innerHTML;
  const rows = html.split("<tr ").slice(1);
  const withBadge = rows.filter((r) => r.includes('class="badge b-sx"')).map((r) => r.match(/data-id="([^"]+)"/)[1]);
  assert.deepEqual(withBadge.sort(), CONFIRMED.slice().sort());
  assert.match(html, /<span class="badge b-sx" title="SPHEREx sees it in 2025–26 where its NEOWISE motion predicts">SPHEREx ✓<\/span>/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("filter: SPHEREx-confirmed only, kept in the address and restored from it", async () => {
  const p = await open();
  check(p, "fSpherex", true);
  assert.deepEqual(rowIds(p).sort(), CONFIRMED.slice().sort());
  assert.equal(new URLSearchParams(p.window.location.search).get("spherex"), "1");
  check(p, "fSpherex", false);
  assert.equal(new URLSearchParams(p.window.location.search).get("spherex"), null);
  p.close();
  const q = await open("?spherex=1");
  assert.equal(q.$("fSpherex").checked, true);
  assert.deepEqual(rowIds(q).sort(), CONFIRMED.slice().sort());
  q.$("fReset").click();
  assert.equal(q.$("fSpherex").checked, false);
  q.close();
});

test("drawer: the SPHEREx 2025–26 section follows the open candidate", async () => {
  const p = await open();
  clickRow(p, "10226-0001");
  assert.match(p.$("dSpherex").innerHTML, /Seen again in 2025–26/);
  assert.match(p.$("dSpherex").innerHTML, /<svg class="d-spec"/);
  clickRow(p, "4866-0002");
  assert.match(p.$("dSpherex").innerHTML, /could not be reached/);
  clickRow(p, BASE.candidates.find((m) => !m.spherex && !CONFIRMED.includes(m.id) && !["9088-0001", "4866-0002"].includes(m.id)).id);
  assert.match(p.$("dSpherex").innerHTML, /Not looked up in SPHEREx for this build/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("hero: confirmed count and how many were looked up; a dash before any check", async () => {
  const p = await open();
  assert.equal(p.$("statSpherex").innerHTML, '7<span class="sub">seen again in 2025–26 where predicted · 40 looked up</span>');
  p.close();
  const q = openPage("survey.html", "", { files: { "data/survey/summary.json": require("./fixtures/survey/summary.json"), "data/survey/leaderboard.json": BASE } });
  await q.window.Survey.ready;
  assert.match(q.$("statSpherex").innerHTML, /^—<span class="sub">SPHEREx check not run yet/);
  q.close();
});

test("html and css: ids exist once, the method says NEOWISE + SPHEREx, colours are tokens in all three theme places", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "app", "survey.html"), "utf8");
  for (const id of ["fSpherex", "dSpherex", "dSxH", "statSpherex"]) assert.equal((html.match(new RegExp(`\\bid="${id}"`, "g")) || []).length, 1, id);
  assert.match(html, /NEOWISE 2014–2024 \+ SPHEREx 2025–26/);
  assert.match(html, /SPHEREx has no source catalogue yet/);
  assert.match(html, /~13″ pixels confirm only fast motions/);
  const css = fs.readFileSync(path.join(__dirname, "..", "app", "survey.css"), "utf8");
  const light = css.match(/:root \{[^}]*\}/)[0], dark = css.match(/:root\[data-theme="dark"\] \{[^}]*\}/)[0];
  const auto = css.match(/@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme\]\) \{[^}]*\}/)[0];
  for (const block of [light, dark, auto]) for (const v of ["--sv-sx:", "--sv-sx-ch4:"]) assert.ok(block.includes(v), v);
  assert.match(css, /\.badge\.b-sx \{[^}]*var\(--sv-sx\)/);
  assert.match(css, /\.d-spec \{[^}]*max-width: 100%/);
});
