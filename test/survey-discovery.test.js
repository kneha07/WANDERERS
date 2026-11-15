// Sky Survey page, from the ranked list to a person investigating: the discovery filters (min visits, min S/N, hide
// flagged, high-confidence preset, sort), their place in the address, the CSV/JSON download of the filtered list,
// and the candidate drawer's links to other archives at the right date, its year-by-year positions, merged
// duplicates and the promote command. Runs in the fake browser against the sample results; no network.
// node --test test/survey-discovery.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { openPage } = require("./fakepage");
const T = require("../app/surveytools.js");

const SUMMARY = require("./fixtures/survey/summary.json");
const BASE = require("./fixtures/survey/leaderboard.json");
// the sample with some flags and a merged duplicate, so every filter has something to do
function board() {
  const b = structuredClone(BASE);
  b.candidates.forEach((m, i) => {
    if (i % 7 === 1) m.flags = [...m.flags, "tile_edge"];
    if (i % 11 === 2) m.flags = [...m.flags, "crowded"];
    if (i % 13 === 3) m.flags = [...m.flags, "saturated"];
  });
  b.candidates.find((m) => m.id === "10226-0001").duplicates = ["10227-0002"];
  return b;
}
const BOARD = board();
const byRank = BOARD.candidates.slice().sort((a, b) => a.rank - b.rank);
async function open(q = "", b = BOARD) {
  const p = openPage("survey.html", q, { files: { "data/survey/summary.json": SUMMARY, "data/survey/leaderboard.json": b } });
  await p.window.Survey.ready;
  return p;
}
const rowIds = (p) => [...p.$("candBody").innerHTML.matchAll(/<tr data-id="([^"]+)"/g)].map((m) => m[1]);
const setVal = (p, id, v, ev = "change") => { p.$(id).value = v; p.fire(p.$(id), ev); };
const check = (p, id, on) => { p.$(id).checked = on; p.fire(p.$(id), "change"); };
const params = (p) => new URLSearchParams(p.window.location.search);
const allRows = (p) => { setVal(p, "pgSize", "1000"); return rowIds(p); };
// Blob downloads: capture what the page hands to URL.createObjectURL and the <a download> it clicks
function capture(p) {
  const got = { blobs: [], anchors: [], revoked: [] };
  p.window.Blob = Blob;
  p.window.URL = class extends URL {
    static createObjectURL(b) { got.blobs.push(b); return `blob:http://localhost/${got.blobs.length}`; }
    static revokeObjectURL(u) { got.revoked.push(u); }
  };
  const make = p.document.createElement;
  p.document.createElement = (t) => { const e = make(t); if (t === "a") got.anchors.push(e); return e; };
  return got;
}

// ---------- filters ----------
test("min visits and min S/N narrow the table and go into the address", async () => {
  const p = await open();
  setVal(p, "fMinVis", "15", "input");
  setVal(p, "fMinSnr", "40", "input");
  assert.deepEqual(allRows(p), byRank.filter((m) => m.n_visits >= 15 && m.pm_snr >= 40).map((m) => m.id));
  assert.deepEqual([params(p).get("visits"), params(p).get("snr")], ["15", "40"]);
  setVal(p, "fMinVis", "-2", "input"); setVal(p, "fMinSnr", "", "input");
  assert.equal(rowIds(p).length, 260, "nonsense and empty mean no minimum");
  assert.equal(params(p).get("visits"), null);
  p.close();
});

test("hide tile-edge, crowded, saturated and likely-artefact rows, each on its own", async () => {
  const p = await open();
  setVal(p, "pgSize", "1000");
  const keep = (pred) => byRank.filter((m) => !pred(m)).map((m) => m.id);
  check(p, "fHideEdge", true);
  assert.deepEqual(rowIds(p), keep((m) => m.flags.includes("tile_edge")));
  check(p, "fHideCrowded", true); check(p, "fHideSat", true); check(p, "fHideArt", true);
  assert.deepEqual(rowIds(p), keep((m) => m.flags.some((f) => ["tile_edge", "crowded", "saturated"].includes(f)) || m.class === "likely artefact"));
  assert.equal(params(p).get("hide"), "edge,crowded,saturated,artefact");
  check(p, "fHideEdge", false);
  assert.equal(params(p).get("hide"), "crowded,saturated,artefact");
  assert.ok(rowIds(p).some((id) => BOARD.candidates.find((m) => m.id === id).flags.includes("tile_edge")));
  p.close();
});

test("high-confidence preset: one button sets the filters, shows it is on, and switches them off again", async () => {
  const p = await open();
  setVal(p, "fClass", "unexplained");
  p.$("fHigh").click();
  assert.equal(p.$("fHigh").getAttribute("aria-pressed"), "true");
  assert.deepEqual([p.$("fMinVis").value, p.$("fMinSnr").value], ["12", "10"]);
  for (const id of ["fHideEdge", "fHideCrowded", "fHideSat", "fHideArt"]) assert.equal(p.$(id).checked, true, id);
  const want = byRank.filter((m) => m.class === "unexplained" && m.n_visits >= 12 && m.pm_snr >= 10
    && !m.flags.some((f) => ["tile_edge", "crowded", "saturated"].includes(f))).map((m) => m.id);
  assert.ok(want.length > 10);
  assert.deepEqual(allRows(p), want);
  assert.equal(p.$("fClass").value, "unexplained", "the class filter is left alone");
  setVal(p, "fMinVis", "11", "input");
  assert.equal(p.$("fHigh").getAttribute("aria-pressed"), "false", "loosening a preset filter turns the button off");
  setVal(p, "fMinVis", "12", "input");
  p.$("fHigh").click();
  assert.equal(p.$("fHigh").getAttribute("aria-pressed"), "false");
  assert.deepEqual([p.$("fMinVis").value, p.$("fMinSnr").value, p.$("fHideEdge").checked], ["0", "0", false]);
  assert.equal(rowIds(p).length, byRank.filter((m) => m.class === "unexplained").length);
  p.close();
});

test("a shared ?preset=high link opens with the preset on", async () => {
  const p = await open("?preset=high&class=unexplained");
  assert.equal(p.$("fHigh").getAttribute("aria-pressed"), "true");
  assert.equal(p.$("fMinVis").value, "12"); assert.equal(p.$("fHideSat").checked, true);
  assert.ok(rowIds(p).every((id) => BOARD.candidates.find((m) => m.id === id).n_visits >= 12));
  p.close();
});

test("sort by: the select sorts the whole list, the column headers keep it in step, the address keeps it", async () => {
  const p = await open();
  setVal(p, "fSort", "snr");
  assert.deepEqual(allRows(p), byRank.slice().sort((a, b) => b.pm_snr - a.pm_snr || a.rank - b.rank).map((m) => m.id));
  assert.equal(params(p).get("sort"), "snr"); assert.equal(params(p).get("dir"), null);
  p.$("candHead").dispatchEvent({ type: "click", target: { closest: () => ({ dataset: { sort: "pm" } }) } });
  assert.equal(p.$("fSort").value, "pm"); assert.equal(params(p).get("sort"), "pm");
  p.$("candHead").dispatchEvent({ type: "click", target: { closest: () => ({ dataset: { sort: "pm" } }) } });
  assert.equal(params(p).get("dir"), "asc", "reversed: slowest first");
  setVal(p, "fSort", "evil");
  assert.equal(params(p).get("sort"), "pm", "unknown keys are ignored");
  p.close();
});

test("the address reproduces the list: every filter and the sort, in a fresh page", async () => {
  const p = await open();
  setVal(p, "fClass", "unexplained"); setVal(p, "fMinPm", "0.3", "input"); check(p, "fRed", true);
  setVal(p, "fMinVis", "10", "input"); setVal(p, "fMinSnr", "8", "input"); check(p, "fHideEdge", true);
  setVal(p, "fSort", "w1w2");
  const shown = allRows(p), search = p.window.location.search;
  assert.ok(shown.length > 3 && shown.length < 100);
  p.close();
  const again = await open(search);
  assert.deepEqual(allRows(again), shown);
  assert.deepEqual([again.$("fClass").value, again.$("fMinPm").value, again.$("fRed").checked, again.$("fMinVis").value, again.$("fMinSnr").value,
    again.$("fHideEdge").checked, again.$("fHideCrowded").checked, again.$("fSort").value], ["unexplained", "0.3", true, "10", "8", true, false, "w1w2"]);
  again.close();
});

test("Reset clears the new filters too (the sort stays)", async () => {
  const p = await open("?visits=14&snr=20&hide=edge,crowded&preset=high&sort=snr");
  p.$("fReset").click();
  assert.deepEqual([p.$("fMinVis").value, p.$("fMinSnr").value, p.$("fHideEdge").checked, p.$("fHideArt").checked], ["0", "0", false, false]);
  assert.equal(p.$("fHigh").getAttribute("aria-pressed"), "false");
  assert.equal(rowIds(p).length, 50);
  assert.deepEqual([...params(p).keys()], ["sort"]);
  p.close();
});

// ---------- export ----------
test("CSV download: every filtered row (not just this page), in table order, as a Blob file", async () => {
  const p = await open();
  const got = capture(p);
  setVal(p, "fClass", "unexplained"); setVal(p, "fSort", "pm");
  const want = byRank.filter((m) => m.class === "unexplained").sort((a, b) => b.pm - a.pm || a.rank - b.rank);
  assert.ok(want.length > 50, "more than one page");
  p.$("xCsv").click();
  assert.equal(got.blobs.length, 1); assert.equal(got.blobs[0].type, "text/csv;charset=utf-8");
  const lines = (await got.blobs[0].text()).trim().split("\r\n");
  assert.equal(lines[0], T.EXPORT_COLUMNS.join(","));
  assert.deepEqual(lines.slice(1).map((l) => l.split(",")[1]), want.map((m) => m.id));
  const a = got.anchors[0];
  assert.equal(a.download, `wanderers-survey-candidates-20261115-${want.length}.csv`);
  assert.equal(a.href, "blob:http://localhost/1"); assert.equal(a.rel, "noopener");
  assert.match(p.$("xMsg").textContent, new RegExp(`^Saved wanderers-survey-candidates-20261115-${want.length}\\.csv: ${want.length} candidates`));
  await p.settle(1100);
  assert.deepEqual(got.revoked, ["blob:http://localhost/1"], "the object URL is released afterwards");
  p.close();
});

test("JSON download: the filtered rows plus the filters, sort and link that made them", async () => {
  const p = await open();
  const got = capture(p);
  check(p, "fRed", true); setVal(p, "fMinVis", "12", "input");
  p.$("xJson").click();
  const data = JSON.parse(await got.blobs[0].text());
  const want = byRank.filter((m) => (m.w1w2 !== null ? m.w1w2 >= 0.5 : m.w1 === null) && m.n_visits >= 12);
  assert.equal(got.blobs[0].type, "application/json");
  assert.equal(data.count, want.length); assert.deepEqual(data.candidates.map((c) => c.id), want.map((m) => m.id));
  assert.equal(data.generated, BOARD.generated); assert.equal(data.filters.red, true); assert.equal(data.filters.minVisits, 12);
  assert.deepEqual(data.sort, { key: "rank", dir: 1 }); assert.match(data.url, /red=1/);
  const w = data.candidates.find((c) => c.id === "10226-0001");
  assert.deepEqual(w.duplicates, ["10227-0002"]); assert.equal(w.gaia_match, false);
  assert.equal(got.anchors[0].download, `wanderers-survey-candidates-20261115-${want.length}.json`);
  p.close();
});

test("download buttons are off when nothing is listed, and a browser without Blob gets a message", async () => {
  const p = await open();
  assert.equal(p.$("xCsv").disabled, false);
  setVal(p, "fSearch", "no-such-thing", "input");
  assert.equal(p.$("xCsv").disabled, true); assert.equal(p.$("xJson").disabled, true);
  assert.equal(p.window.Survey.exportList("csv"), null);
  setVal(p, "fSearch", "", "input");
  p.window.Blob = undefined;
  const r = p.window.Survey.exportList("csv");
  assert.equal(r.ok, false); assert.match(r.text, /^rank,id,/);
  assert.equal(p.$("xMsg").textContent, "This browser cannot save a file from the page.");
  p.close();
  const empty = openPage("survey.html", "", { files: { "data/survey/summary.json": SUMMARY, "data/survey/leaderboard.json": { ...BOARD, candidates: [] } } });
  await empty.window.Survey.ready;
  assert.equal(empty.$("xCsv").disabled, true);
  empty.close();
});

// ---------- the candidate drawer ----------
test("drawer: links to other archives, in a new tab, at today's position or J2000/2016.0", async () => {
  const p = await open();
  p.window.Survey.setNow(2026.5);
  p.window.Survey.openCandidate("10226-0001");
  const m = BOARD.candidates.find((x) => x.id === "10226-0001"), html = p.$("dArch").innerHTML;
  const hrefs = [...html.matchAll(/<a href="([^"]+)" target="_blank" rel="noopener noreferrer">([^<]+)<\/a>/g)].map((x) => [x[2], x[1].replace(/&amp;/g, "&")]);
  assert.deepEqual(hrefs.map((h) => h[0]), ["IRSA Finder Chart ↗", "Aladin Lite ↗", "Legacy Surveys viewer ↗", "SIMBAD ↗", "VizieR, all catalogues ↗", "Gaia DR3 in VizieR ↗"]);
  const now = T.positionAt(m, 2026.5), j2000 = T.positionAt(m, 2000);
  assert.ok(hrefs[2][1].includes(`ra=${now.ra.toFixed(6)}&dec=${now.dec.toFixed(6)}`), "Legacy Surveys at today's position");
  assert.ok(hrefs[3][1].includes(`Coord=${j2000.ra.toFixed(6)}%20${j2000.dec.toFixed(6)}`), "SIMBAD at J2000");
  assert.match(html, /today \(2026\.50\)/); assert.match(html, /J2000, \d+″ radius/); assert.match(html, /2016\.0, \d+″ radius/);
  p.close();
});

test("drawer: where it is in 2000, 2016, today and 2030, with the uncertainty of each move", async () => {
  const p = await open();
  p.window.Survey.setNow(2026.5);
  p.window.Survey.openCandidate("8545-0003");
  const html = p.$("dWhen").innerHTML, m = BOARD.candidates.find((x) => x.id === "8545-0003");
  assert.deepEqual([...html.matchAll(/data-when="(\w+)"/g)].map((x) => x[1]), ["neowise", "j2000", "gaia", "now", "later"]);
  const later = T.positionAt(m, 2030);
  assert.match(html, new RegExp(`data-when="later"><dt>2030 \\(predicted\\)</dt><dd><span class="mono">RA ${later.ra.toFixed(5)}°, Dec ${later.dec.toFixed(5)}°`));
  assert.match(html, /<dt>Today \(predicted\) <small>2026\.50<\/small>/);
  assert.equal((html.match(/± /g) || []).length, 4, "every predicted date has its uncertainty");
  p.close();
});

test("drawer: a merged duplicate is listed, and the promote command names the candidate", async () => {
  const p = await open();
  p.window.Survey.openCandidate("10226-0001");
  assert.match(p.$("dNums").innerHTML, /<dt>Also found<\/dt><dd><span class="mono">10227-0002<\/span><small>the same source seen from a neighbouring tile/);
  assert.match(p.$("dPromote").innerHTML, /<code>python pipeline\/survey\/promote\.py --id 10226-0001<\/code>/);
  assert.match(p.$("dPromote").innerHTML, /<code>--run<\/code>/);
  p.window.Survey.closeDrawer();
  p.window.Survey.openCandidate("8545-0003");
  assert.doesNotMatch(p.$("dNums").innerHTML, /Also found/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("drawer text from the data is escaped in the new parts too", async () => {
  const b = structuredClone(BOARD);
  Object.assign(b.candidates[0], { id: '<img src=x onerror="1">', duplicates: ["<b>dup</b>"] });
  const p = await open("", b);
  p.window.Survey.openCandidate(b.candidates[0].id);
  assert.doesNotMatch(p.$("dNums").innerHTML + p.$("dPromote").innerHTML + p.$("dArch").innerHTML, /<img|<b>dup/);
  assert.match(p.$("dNums").innerHTML, /&lt;b&gt;dup&lt;\/b&gt;/);
  p.close();
});

// ---------- the page's files ----------
test("page wiring: new controls exist once, are labelled, and scripts load in order with new versions", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "app", "survey.html"), "utf8");
  for (const id of ["fMinVis", "fMinSnr", "fHideEdge", "fHideCrowded", "fHideSat", "fHideArt", "fSort", "fHigh", "xCsv", "xJson", "xMsg", "dArch", "dWhen", "dPromote"])
    assert.equal((html.match(new RegExp(`\\bid="${id}"`, "g")) || []).length, 1, id);
  assert.match(html, /<script src="aladinlink\.js"><\/script>\s*<script src="surveytools\.js\?v=20261118a"><\/script>\s*<script src="theme\.js"><\/script>\s*<script src="survey\.js\?v=20261118a"><\/script>/);
  assert.match(html, /survey\.css\?v=20261118a/);
  assert.match(html, /id="fHigh" aria-pressed="false" aria-describedby="presetNote"/);
  assert.match(html, /cold brown dwarfs are red in W1−W2/);
});
