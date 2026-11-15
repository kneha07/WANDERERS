// Sky Survey page in every state a visitor can meet: no results yet, a run in progress, a partial run, sample data,
// failed or broken downloads, an empty ranked list, and shared links that restore filters or open a candidate.
// node --test test/survey-states.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { openPage } = require("./fakepage");

const SUMMARY = require("./fixtures/survey/summary.json");
const BOARD = require("./fixtures/survey/leaderboard.json");
const files = (s = SUMMARY, b = BOARD) => ({ "data/survey/summary.json": s, "data/survey/leaderboard.json": b });
const rowIds = (p) => [...p.$("candBody").innerHTML.matchAll(/<tr data-id="([^"]+)"/g)].map((m) => m[1]);

// Serve each data file as: an object (200), a number (that HTTP status), an Error (network failure) or "text" (not JSON).
function serve(p, { summary, board }) {
  p.window.fetch = async (url) => {
    const v = String(url).includes("summary.json") ? summary : board;
    if (v instanceof Error) throw v;
    if (typeof v === "number") return { ok: v >= 200 && v < 300, status: v, json: async () => { throw new SyntaxError("Unexpected token '<'"); } };
    if (typeof v === "string") return { ok: true, status: 200, json: async () => JSON.parse(v) };
    return { ok: true, status: 200, json: async () => structuredClone(v) };
  };
}
// open with the sample results, then load the state under test (also checks that a reload replaces everything shown)
async function openState(state, q = "") {
  const p = openPage("survey.html", q, { files: files() });
  await p.window.Survey.ready;
  serve(p, state);
  await p.window.Survey.reload();
  return p;
}
async function open(q = "", s, b) {
  const p = openPage("survey.html", q, { files: files(s, b) });
  await p.window.Survey.ready;
  return p;
}

test("no results yet: says so plainly, shows dashes, an empty map and an empty table", async () => {
  const p = await openState({ summary: 404, board: 404 });
  assert.match(p.$("banners").innerHTML, /<b>No survey results yet\.<\/b>/);
  assert.doesNotMatch(p.$("banners").innerHTML, /Sample data|role="alert"/);
  assert.equal(p.$("retry").hidden, true);
  assert.equal(p.$("heroTitle").innerHTML, "Billions of infrared detections. Which ones move?");
  for (const id of ["statDet", "statTracks", "statSky", "statMovers", "statUnex", "statTime"]) assert.equal(p.$(id).innerHTML, "—", id);
  assert.equal(p.$("funnel").hidden, true);
  assert.equal(p.window.Survey.mapTiles().length, 0);
  assert.equal(p.$("mapNote").textContent, "No tiles searched yet.");
  assert.match(p.$("skyMap").getAttribute("aria-label"), /no tiles searched yet/);
  assert.equal(p.$("candBody").innerHTML, "");
  assert.equal(p.$("tEmpty").hidden, false); assert.equal(p.$("tEmpty").textContent, "No ranked candidates yet.");
  assert.equal(p.$("pager").hidden, true);
  assert.match(p.$("valBody").innerHTML, /No validation results yet/);
  assert.match(p.$("limitsList").innerHTML, /has not listed its limits yet/);
  assert.equal(p.$("methodBox").hidden, true); assert.equal(p.$("genTime").textContent, "");
  assert.deepEqual(p.errors, []); assert.deepEqual(p.document.badDraws, []);
  p.close();
});

test("summary but no ranked list yet: numbers shown, table explains why it is empty", async () => {
  const p = await openState({ summary: SUMMARY, board: 404 });
  assert.match(p.$("statDet").innerHTML, /^8,116,540,408/);
  assert.equal(p.$("tEmpty").hidden, false);
  assert.match(p.$("tEmpty").textContent, /^The ranked list is not ready yet/);
  assert.doesNotMatch(p.$("banners").innerHTML, /role="alert"/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("run in progress: tiles done below the total says so, with both numbers", async () => {
  const running = { ...SUMMARY, demo: false, status: undefined, tiles_done: 120, tiles_total: 12288, sky_fraction: 120 / 12288, tiles: SUMMARY.tiles.slice(0, 120) };
  const p = await openState({ summary: running, board: { ...BOARD, demo: false } });
  assert.match(p.$("banners").innerHTML, /<b>Run in progress:<\/b> 120 of 12,288 tiles searched so far\. The numbers below are results so far/);
  assert.match(p.$("statSky").innerHTML, /^120 tiles<span class="sub">.*0\.98% of the sky/);
  assert.equal(p.window.Survey.mapTiles().length, 120);
  const st = await openState({ summary: { ...running, status: "running", tiles_done: 12288 }, board: BOARD });
  assert.match(st.$("banners").innerHTML, /Run in progress/, "an explicit running status wins");
  p.close(); st.close();
});

test("a finished run over part of the sky is called partial, not in progress", async () => {
  const p = await openState({ summary: { ...SUMMARY, status: "done", tiles_total: 12288 }, board: BOARD });
  assert.match(p.$("banners").innerHTML, /<b>Partial survey:<\/b> this run searched 640 of 12,288 tiles\./);
  assert.doesNotMatch(p.$("banners").innerHTML, /in progress/);
  p.close();
});

test("sample data shows a banner; real results do not", async () => {
  let p = await open();
  assert.match(p.$("banners").innerHTML, /<p class="sv-banner demo"><b>Sample data\.<\/b>[^<]*made up[^<]*not survey results/);
  p.close();
  p = await open("", { ...SUMMARY, demo: false }, { ...BOARD, demo: false });
  assert.equal(p.$("banners").innerHTML, "");
  p.close();
  p = await open("", { ...SUMMARY, demo: false }, BOARD);
  assert.match(p.$("banners").innerHTML, /Sample data/, "either file marked demo is enough");
  p.close();
});

test("network failure: an alert with the reason and a Try again button that works", async () => {
  const p = await openState({ summary: new TypeError("Failed to fetch"), board: new TypeError("Failed to fetch") });
  assert.match(p.$("banners").innerHTML, /<p class="sv-banner err" role="alert"><b>Could not load the survey results:<\/b> the network request failed\./);
  assert.equal(p.$("retry").hidden, false);
  assert.equal(p.$("tEmpty").textContent, "The ranked list could not be loaded.");
  assert.equal(p.$("statDet").innerHTML, "—");
  serve(p, { summary: SUMMARY, board: BOARD });
  p.$("retry").click();
  await p.settle(20);
  assert.doesNotMatch(p.$("banners").innerHTML, /role="alert"/);
  assert.equal(p.$("retry").hidden, true);
  assert.equal(rowIds(p).length, 50);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("server errors, broken JSON and the wrong shape are reported, never shown as numbers", async () => {
  for (const [state, why] of [
    [{ summary: 500, board: BOARD }, "the server answered 500"],
    [{ summary: "{not json", board: BOARD }, "the file is not valid JSON"],
    [{ summary: { hello: "world" }, board: BOARD }, "summary.json does not have the expected fields"],
    [{ summary: [1, 2], board: BOARD }, "summary.json does not have the expected fields"],
    [{ summary: SUMMARY, board: { candidates: "nope" } }, "leaderboard.json does not have a candidate list"],
  ]) {
    const p = await openState(state);
    assert.match(p.$("banners").innerHTML, new RegExp(`role="alert"><b>Could not load the survey results:</b> ${why}`), why);
    assert.equal(p.$("retry").hidden, false, why);
    assert.deepEqual(p.errors, [], why); assert.deepEqual(p.document.badDraws, [], why);
    p.close();
  }
});

test("a run that ranked nothing says so", async () => {
  const p = await open("", SUMMARY, { generated: "x", n_candidates: 0, candidates: [] });
  assert.equal(p.$("tEmpty").hidden, false);
  assert.equal(p.$("tEmpty").textContent, "No candidates passed the cuts in this run.");
  assert.equal(p.$("tCount").textContent, "0 of 0 candidates shown.");
  p.close();
});

test("no validation in the summary: the page says the numbers are unchecked", async () => {
  const s = { ...SUMMARY }; delete s.validation;
  const p = await open("", s);
  assert.match(p.$("valBody").innerHTML, /Validation results are not available for this run yet\. Until they are, treat every number on this page as unchecked\./);
  p.close();
});

test("missing optional fields still render (no NaN, no undefined)", async () => {
  const s = { tiles_done: 3, tiles_total: 3, tiles: [[8545, 1, 0], [10226, 1, 1], [7945, 0, 0]] };
  const bare = BOARD.candidates.slice(0, 3).map(({ id, ra, dec, pm }) => ({ id, ra, dec, pm }));
  const p = await open("", s, { candidates: bare });
  for (const id of ["statDet", "statSky", "statTime", "candBody", "valBody", "funnel"]) assert.doesNotMatch(p.$(id).innerHTML, /NaN|undefined/, id);
  p.window.Survey.openCandidate(bare[0].id);
  for (const id of ["dNums", "dReasons", "dTrack", "dTrackNote", "dRank"]) assert.doesNotMatch(p.$(id).innerHTML || p.$(id).textContent, /NaN|undefined/, id);
  assert.equal(p.$("dTrackNote").textContent, "This candidate has fewer than two track points in the results file.");
  assert.deepEqual(rowIds(p), bare.map((m) => m.id), "missing ranks follow file order");
  assert.deepEqual(p.errors, []); assert.deepEqual(p.document.badDraws, []);
  p.close();
});

test("while the files download, the page says it is loading", async () => {
  const p = openPage("survey.html", "", { files: files(), delays: { "data/survey/": 80 } });
  assert.equal(p.$("mapNote").textContent, "Loading…");
  assert.match(p.$("valBody").innerHTML, /Loading…/);
  assert.equal(p.$("tEmpty").textContent, "Loading the ranked list…");
  await p.window.Survey.ready;
  assert.match(p.$("mapNote").textContent, /^640 tiles searched/);
  p.close();
});

// ---------- shared links ----------
test("?id= opens that candidate straight away; an unknown id is ignored", async () => {
  let p = await open("?id=10226-0001");
  assert.equal(p.$("drawer").hidden, false);
  assert.equal(p.$("dTitle").textContent, "10226-0001");
  p.close();
  p = await open("?id=nope");
  assert.equal(p.$("drawer").hidden, true);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("filters, tile and the open candidate are kept in the address for sharing", async () => {
  const p = await open();
  p.$("fClass").value = "unexplained"; p.fire(p.$("fClass"), "change");
  p.$("fMinPm").value = "0.5"; p.fire(p.$("fMinPm"), "input");
  p.$("fRed").checked = true; p.fire(p.$("fRed"), "change");
  p.$("fSearch").value = "0"; p.fire(p.$("fSearch"), "input");
  const q = new URLSearchParams(p.window.location.search);
  assert.deepEqual([q.get("class"), q.get("minpm"), q.get("red"), q.get("q")], ["unexplained", "0.5", "1", "0"]);
  const first = rowIds(p)[0];
  p.window.Survey.openCandidate(first);
  assert.equal(new URLSearchParams(p.window.location.search).get("id"), first);
  p.window.Survey.closeDrawer();
  assert.equal(new URLSearchParams(p.window.location.search).get("id"), null);
  const shown = rowIds(p), search = p.window.location.search;
  p.close();
  const again = await open(search);
  assert.equal(again.$("fClass").value, "unexplained"); assert.equal(again.$("fMinPm").value, "0.5");
  assert.equal(again.$("fRed").checked, true); assert.equal(again.$("fSearch").value, "0");
  assert.deepEqual(rowIds(again), shown);
  again.close();
});

test("?tile= filters to that tile; nonsense values are ignored", async () => {
  let p = await open("?tile=10226");
  assert.equal(p.$("fTile").value, "10226");
  assert.ok(rowIds(p).every((id) => id.startsWith("10226-")));
  p.close();
  for (const q of ["?tile=99999", "?tile=-1", "?tile=abc", "?class=constructor", "?minpm=abc"]) {
    p = await open(q);
    assert.equal(rowIds(p).length, 50, q);
    assert.equal(p.$("fClass").value, "all", q);
    p.close();
  }
});

// ---------- the files the page really reads ----------
test("app/data/survey/*.json, when present, are files this page can show", async () => {
  const dir = path.join(__dirname, "..", "app", "data", "survey");
  const s = path.join(dir, "summary.json"), b = path.join(dir, "leaderboard.json");
  if (!fs.existsSync(s) && !fs.existsSync(b)) return;   // nothing published: the page shows its empty state
  const p = openPage("survey.html", "");                 // no stand-ins: the real files
  await p.window.Survey.ready;
  assert.doesNotMatch(p.$("banners").innerHTML, /role="alert"/, "the published files load");
  assert.deepEqual(p.errors, []); assert.deepEqual(p.document.badDraws, []);
  p.close();
});

// Gaia (ESA, CDS, IRSA) can be offline during a run: "0 unexplained" must not read as "checked and found nothing".
test("movers still waiting for the Gaia check are counted next to 'unexplained'", async () => {
  const s = { ...structuredClone(SUMMARY), movers: 119, unexplained: 0, gaia_unchecked: 119 };
  const p = await open("", s);
  assert.match(p.$("statUnex").innerHTML, /^0<span class="sub">no Gaia DR3 counterpart · 119 of 119 movers still to check<\/span>$/);
  p.close();
});

test("no pending note once every mover is checked, or when an older summary lacks the count", async () => {
  for (const extra of [{ gaia_unchecked: 0 }, {}]) {
    const s = { ...structuredClone(SUMMARY), unexplained: 3, ...extra };
    if (!("gaia_unchecked" in extra)) delete s.gaia_unchecked;
    const p = await open("", s);
    assert.equal(p.$("statUnex").innerHTML, '3<span class="sub">no Gaia DR3 counterpart</span>');
    assert.deepEqual(p.errors, []);
    p.close();
  }
});

test("a partial Gaia check shows how many movers are left", async () => {
  const s = { ...structuredClone(SUMMARY), movers: 2500, unexplained: 12, gaia_unchecked: 1234 };
  const p = await open("", s);
  assert.match(p.$("statUnex").innerHTML, /^12<span class="sub">no Gaia DR3 counterpart · 1,234 of 2,500 movers still to check<\/span>$/);
  p.close();
});
