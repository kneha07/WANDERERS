// Behaviour tests for the Sky Survey page (app/survey.html + survey.js), run in the fake browser against the
// sample results in test/fixtures/survey/ (served in place of app/data/survey/, which a real run overwrites).
// node --test test/survey.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { openPage } = require("./fakepage");
const C = require("../app/survey.js");

const SUMMARY = require("./fixtures/survey/summary.json");
const BOARD = require("./fixtures/survey/leaderboard.json");
const files = (s = SUMMARY, b = BOARD) => ({ "data/survey/summary.json": s, "data/survey/leaderboard.json": b });
async function open(q = "", opts = {}) {
  const p = openPage("survey.html", q, { files: files(opts.summary, opts.board), ...opts });
  await p.window.Survey.ready;
  return p;
}
const rowIds = (p) => [...p.$("candBody").innerHTML.matchAll(/<tr data-id="([^"]+)"/g)].map((m) => m[1]);
const target = (data) => ({ closest: () => ({ dataset: data }) });   // what a click inside the table hands the delegated handler
const clickSort = (p, key) => p.$("candHead").dispatchEvent({ type: "click", target: target({ sort: key }) });
const clickRow = (p, id) => p.$("candBody").dispatchEvent({ type: "click", target: target({ id }) });
const setVal = (p, id, v, ev = "change") => { p.$(id).value = v; p.fire(p.$(id), ev); };
const byRank = BOARD.candidates.slice().sort((a, b) => a.rank - b.rank);
const UNEX = BOARD.candidates.filter((m) => m.class === "unexplained");

function fakeAladin() {
  const calls = [], layer = (name) => ({ name, items: [], add(x) { this.items.push(x); }, addSources(xs) { this.items.push(...xs); }, removeAll() { this.items = []; } });
  const view = { base: null, at: null, fov: null, overlays: [], catalogs: [],
    gotoRaDec(ra, dec) { this.at = [ra, dec]; }, setFoV(f) { this.fov = f; }, setBaseImageLayer(l) { this.base = l; },
    addOverlay(o) { this.overlays.push(o); }, addCatalog(c) { this.catalogs.push(c); } };
  const A = {
    init: Promise.resolve(),
    aladin: (sel, o) => { calls.push(["aladin", sel, o]); return view; },
    imageHiPS: (url, o) => ({ url, o, slice: null, setSliceNumber(n) { this.slice = n; } }),
    graphicOverlay: (o) => Object.assign(layer("overlay"), { opts: o }), catalog: (o) => Object.assign(layer("catalog"), { opts: o }),
    polyline: (pts) => ({ pts }), source: (ra, dec, o) => ({ ra, dec, o }),
  };
  return { A, view, calls };
}

// ---------- the scale ----------
test("loads the sample results with no errors and no NaN in the map", async () => {
  const p = await open();
  assert.deepEqual(p.errors, []);
  assert.deepEqual(p.document.badDraws, []);
  assert.ok(p.fetched.some((u) => u.includes("data/survey/summary.json")) && p.fetched.some((u) => u.includes("data/survey/leaderboard.json")));
  p.close();
});

test("hero: detections in words and in full, with thousands separators", async () => {
  const p = await open();
  assert.match(p.$("heroTitle").innerHTML, new RegExp(`${C.fmtBig(SUMMARY.detections)}</span> infrared detections, searched`));
  assert.match(p.$("statDet").innerHTML, /^8,116,540,408<span class="sub">5,757,653,995 passed the quality cuts<\/span>$/);
  assert.match(p.$("statTracks").innerHTML, /^60,604,048/);
  assert.match(p.$("statTracks").innerHTML, /961,493,573 per-visit sources/);
  p.close();
});

test("hero: tiles, sky area and sky fraction; movers, unexplained, run time and throughput", async () => {
  const p = await open();
  assert.match(p.$("statSky").innerHTML, /^640 tiles<span class="sub">2,149 deg² · 5\.2% of the sky<\/span>$/);
  assert.match(p.$("statMovers").innerHTML, /^7,853<span class="sub">move ≥ 0\.15″ a year, steadily/);
  assert.match(p.$("statUnex").innerHTML, /^128<span class="sub">no Gaia DR3 counterpart/);
  assert.match(p.$("statTime").innerHTML, /^8\.2 hours<span class="sub">78 tiles\/hour · 274,779 detections\/s<\/span>$/);
  p.close();
});

test("hero: the funnel goes from detections down to the people who check", async () => {
  const p = await open(), f = p.$("funnel");
  assert.equal(f.hidden, false);
  const keys = [...f.innerHTML.matchAll(/data-k="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(keys, ["detections", "good_detections", "visit_sources", "tracks", "movers", "unexplained", "people"]);
  const vals = keys.slice(0, -1).map((k) => SUMMARY[k]);
  for (let i = 1; i < vals.length; i++) assert.ok(vals[i] < vals[i - 1], `${keys[i]} smaller than ${keys[i - 1]}`);
  assert.match(f.innerHTML, /<b class="mono">8\.12 billion<\/b><span>NEOWISE detections read/);
  assert.match(f.innerHTML, /href="#candidates"/);
  p.close();
});

// ---------- table: rows, order, count, paging ----------
test("table: first page shows 50 rows in rank order", async () => {
  const p = await open();
  assert.deepEqual(rowIds(p), byRank.slice(0, 50).map((m) => m.id));
  assert.match(p.$("tCount").textContent, /^Showing 1–50 of 260 candidates; the list holds the top 260 of 7,853 ranked movers\.$/);
  assert.equal(p.$("tEmpty").hidden, true);
  p.close();
});

test("table: a row shows rank, id, class badge, motion, direction, visits/span, colour, Gaia result and score", async () => {
  const p = await open(), m = BOARD.candidates.find((x) => x.id === "10226-0001");
  const tr = p.$("candBody").innerHTML.match(/<tr data-id="10226-0001"[\s\S]*?<\/tr>/)[0];
  const pa = C.posAngle(m.pmra, m.pmdec);
  assert.match(tr, new RegExp(`<td class="num">${m.rank}</td>`));
  assert.match(tr, /<th scope="row"><button type="button" class="cid mono" data-id="10226-0001"/);
  assert.match(tr, /<span class="badge b-unex">unexplained<\/span>/);
  assert.match(tr, /<td class="num">8\.15<\/td>/);
  assert.match(tr, new RegExp(`${Math.round(pa)}° ${C.compass(pa)}`));
  assert.match(tr, new RegExp(`${m.n_visits} · ${m.span_yr.toFixed(1)} yr`));
  assert.match(tr, /<td class="num red">no W1<\/td>/);
  assert.match(tr, /<td>No match<\/td>/);
  assert.match(tr, new RegExp(`<td class="num">${m.score.toFixed(2)}</td></tr>`));
  const k = p.$("candBody").innerHTML;
  p.$("pgSize").value = "1000"; p.fire(p.$("pgSize"), "change");
  assert.match(p.$("candBody").innerHTML, /<tr data-id="8545-0003"[\s\S]*?<td>Match · 0\.4″<\/td>/);
  assert.ok(k.length < p.$("candBody").innerHTML.length);
  p.close();
});

test("paging: next, previous, disabled ends and page size", async () => {
  const p = await open();
  assert.equal(p.$("pager").hidden, false);
  assert.equal(p.$("pgPrev").disabled, true); assert.equal(p.$("pgInfo").textContent, "Page 1 of 6");
  p.$("pgNext").click();
  assert.deepEqual(rowIds(p), byRank.slice(50, 100).map((m) => m.id));
  assert.match(p.$("tCount").textContent, /^Showing 51–100 of 260/);
  for (let i = 0; i < 10; i++) p.$("pgNext").click();
  assert.equal(p.$("pgInfo").textContent, "Page 6 of 6"); assert.equal(p.$("pgNext").disabled, true);
  assert.equal(rowIds(p).length, 10);
  p.$("pgPrev").click(); assert.equal(p.$("pgInfo").textContent, "Page 5 of 6");
  setVal(p, "pgSize", "100");
  assert.equal(p.$("pgInfo").textContent, "Page 1 of 3"); assert.equal(rowIds(p).length, 100);
  setVal(p, "pgSize", "1000");
  assert.equal(rowIds(p).length, 260); assert.equal(p.$("pager").hidden, true, "one page: no pager");
  p.close();
});

test("1,000 candidates (the contract's top list) page and render in full", async () => {
  const many = Array.from({ length: 1000 }, (_, i) => ({ ...BOARD.candidates[i % BOARD.candidates.length], id: `X-${String(i + 1).padStart(4, "0")}`, rank: i + 1 }));
  const p = await open("", { board: { generated: "x", n_candidates: 4000, candidates: many } });
  assert.match(p.$("tCount").textContent, /^Showing 1–50 of 1,000 candidates; the list holds the top 1,000 of 4,000/);
  assert.equal(p.$("pgInfo").textContent, "Page 1 of 20");
  setVal(p, "pgSize", "1000");
  assert.equal(rowIds(p).length, 1000);
  assert.equal(rowIds(p)[999], "X-1000");
  assert.deepEqual(p.errors, []);
  p.close();
});

// ---------- filters ----------
test("filter: unexplained only", async () => {
  const p = await open();
  setVal(p, "fClass", "unexplained");
  assert.match(p.$("tCount").textContent, new RegExp(`of ${UNEX.length} candidates \\(filtered from 260\\)`));
  setVal(p, "pgSize", "1000");
  const ids = rowIds(p);
  assert.equal(ids.length, UNEX.length);
  assert.doesNotMatch(p.$("candBody").innerHTML, /b-known|b-art|b-nc/);
  setVal(p, "fClass", "known (Gaia)");
  assert.equal(rowIds(p).length, BOARD.candidates.filter((m) => m.class === "known (Gaia)").length);
  p.close();
});

test("filter: minimum motion in arcseconds per year", async () => {
  const p = await open();
  setVal(p, "pgSize", "1000");
  setVal(p, "fMinPm", "2", "input");
  const want = byRank.filter((m) => m.pm >= 2000).map((m) => m.id);
  assert.ok(want.length > 5 && want.length < 260);
  assert.deepEqual(rowIds(p), want);
  setVal(p, "fMinPm", "", "input");
  assert.equal(rowIds(p).length, 260, "cleared: everything again");
  setVal(p, "fMinPm", "-3", "input");
  assert.equal(rowIds(p).length, 260, "negative is ignored");
  p.close();
});

test("filter: red only keeps W1−W2 ≥ 0.5 and W1 non-detections", async () => {
  const p = await open();
  setVal(p, "pgSize", "1000");
  p.$("fRed").checked = true; p.fire(p.$("fRed"), "change");
  const want = byRank.filter((m) => (m.w1w2 !== null ? m.w1w2 >= 0.5 : m.w1 === null)).map((m) => m.id);
  assert.deepEqual(rowIds(p), want);
  assert.ok(want.includes("10226-0001"), "WISE 0855 (no W1) counts as red");
  assert.ok(!want.includes("8545-0003"), "Kapteyn's Star (W1−W2 0.3) does not");
  p.close();
});

test("filter: search by id is a case-insensitive part match; no match says so", async () => {
  const p = await open();
  setVal(p, "fSearch", "8545-", "input");
  assert.deepEqual(rowIds(p), byRank.filter((m) => m.id.includes("8545-")).map((m) => m.id));
  setVal(p, "fSearch", "no-such-thing", "input");
  assert.deepEqual(rowIds(p), []);
  assert.equal(p.$("tEmpty").hidden, false);
  assert.equal(p.$("tEmpty").textContent, "No candidates match these filters.");
  assert.equal(p.$("pager").hidden, true);
  p.close();
});

test("filters combine, go back to page 1, and Reset clears them all", async () => {
  const p = await open();
  p.$("pgNext").click();
  setVal(p, "fClass", "unexplained");
  assert.equal(p.$("pgInfo").textContent, "Page 1 of 3", "a new filter starts at page 1");
  setVal(p, "fMinPm", "1", "input");
  p.$("fRed").checked = true; p.fire(p.$("fRed"), "change");
  const want = byRank.filter((m) => m.class === "unexplained" && m.pm >= 1000 && (m.w1w2 !== null ? m.w1w2 >= 0.5 : m.w1 === null)).map((m) => m.id);
  assert.deepEqual(rowIds(p), want.slice(0, 50));
  p.$("fReset").click();
  assert.equal(p.$("fClass").value, "all"); assert.equal(p.$("fRed").checked, false); assert.equal(p.$("fMinPm").value, "0");
  assert.deepEqual(rowIds(p), byRank.slice(0, 50).map((m) => m.id));
  p.close();
});

test("filter: tile number from the filter bar", async () => {
  const p = await open();
  setVal(p, "fTile", "8545");
  assert.deepEqual(rowIds(p), byRank.filter((m) => m.k5 === 8545).map((m) => m.id));
  assert.match(p.$("tileInfo").innerHTML, /<b>Tile 8545<\/b>/);
  assert.equal(p.$("tileClear").hidden, false);
  setVal(p, "fTile", "");
  assert.equal(rowIds(p).length, 50); assert.equal(p.$("tileClear").hidden, true);
  p.close();
});

// ---------- sorting ----------
test("sort: clicking a column sorts it, clicking again reverses it; aria-sort follows", async () => {
  const p = await open();
  assert.match(p.$("candHead").innerHTML, /aria-sort="ascending"><button type="button" class="sorter" data-sort="rank">/);
  clickSort(p, "pm");
  const desc = C.sortRows(BOARD.candidates, "pm", -1).map((m) => m.id);
  assert.deepEqual(rowIds(p), desc.slice(0, 50));
  assert.match(p.$("candHead").innerHTML, /aria-sort="descending"><button type="button" class="sorter" data-sort="pm">/);
  assert.match(p.$("candHead").innerHTML, /aria-sort="none"><button type="button" class="sorter" data-sort="rank">/);
  clickSort(p, "pm");
  assert.deepEqual(rowIds(p), C.sortRows(BOARD.candidates, "pm", 1).map((m) => m.id).slice(0, 50));
  assert.match(p.$("candHead").innerHTML, /aria-sort="ascending"><button type="button" class="sorter" data-sort="pm">/);
  p.close();
});

test("sort: every column sorts the whole list, not just the page", async () => {
  const p = await open();
  setVal(p, "pgSize", "1000");
  for (const key of ["rank", "id", "class", "pm", "pa", "visits", "w1w2", "gaia", "score"]) {
    if (key === "rank") clickSort(p, "id");   // move off rank first so one click sorts it ascending again
    clickSort(p, key);
    const want = C.sortRows(BOARD.candidates, key, C.SORTS[key].dir).map((m) => m.id);
    assert.deepEqual(rowIds(p), want, key);
  }
  clickSort(p, "nonsense");
  assert.deepEqual(p.errors, []);
  p.close();
});

test("sort and filter together: unexplained candidates by colour, reddest first", async () => {
  const p = await open();
  setVal(p, "fClass", "unexplained"); clickSort(p, "w1w2");
  const ids = rowIds(p), got = ids.map((id) => BOARD.candidates.find((m) => m.id === id).w1w2).filter((c) => c !== null);
  for (let i = 1; i < got.length; i++) assert.ok(got[i] <= got[i - 1]);
  p.close();
});

// ---------- the candidate drawer ----------
test("clicking a row opens its details: title, class, rank, reasons", async () => {
  const p = await open(), m = BOARD.candidates.find((x) => x.id === "10226-0001");
  clickRow(p, "10226-0001");
  assert.equal(p.$("drawer").hidden, false); assert.equal(p.$("scrim").hidden, false);
  assert.equal(p.$("dTitle").textContent, "10226-0001");
  assert.equal(p.$("dClass").textContent, "unexplained"); assert.equal(p.$("dClass").className, "badge b-unex");
  assert.equal(p.$("dRank").textContent, `Rank ${m.rank} · score ${m.score.toFixed(2)}`);
  const li = [...p.$("dReasons").innerHTML.matchAll(/<li>([^<]*)<\/li>/g)].map((x) => x[1]);
  assert.deepEqual(li, m.reasons.map(C.esc));
  assert.equal(p.document.activeElement, p.$("dClose"), "focus moves into the dialog");
  p.close();
});

test("drawer numbers: position, motion, direction, visits, colours, Gaia", async () => {
  const p = await open();
  p.window.Survey.openCandidate("8545-0003");
  const h = p.$("dNums").innerHTML, m = BOARD.candidates.find((x) => x.id === "8545-0003"), s = C.sexa(m.ra, m.dec);
  assert.ok(h.includes(s.pretty), "sexagesimal");
  assert.match(h, new RegExp(`RA ${m.ra.toFixed(5)}°, Dec ${m.dec.toFixed(5)}°`));
  assert.match(h, /<b class="mono">8\.66″\/yr<\/b>/);
  assert.match(h, /131° east of north \(towards SE\)/);
  assert.match(h, new RegExp(`${m.n_visits} visits over ${m.span_yr.toFixed(1)} years`));
  assert.match(h, /W1 6\.10 · W2 5\.80 · W1−W2 0\.30/);
  assert.match(h, /Matched: Gaia DR3 4810594479418041856, 0\.40″ from where it should be; Gaia motion 8\.64″\/yr; G = 8\.06\./);
  assert.match(h, /data-tile="8545"/);
  p.window.Survey.openCandidate("10226-0001");
  assert.match(p.$("dNums").innerHTML, /No Gaia DR3 source where this object should be/);
  assert.match(p.$("dNums").innerHTML, /W1 — · W2 14\.\d\d/);
  p.close();
});

test("drawer track: one dot per NEOWISE visit, first and last years labelled, straight-line fit", async () => {
  const p = await open(), m = BOARD.candidates.find((x) => x.id === "10226-0001");
  p.window.Survey.openCandidate(m.id);
  const svg = p.$("dTrack").innerHTML, ts = m.track.map((x) => x[0]).sort((a, b) => a - b);
  assert.equal((svg.match(/<circle class="tp"/g) || []).length, m.track.length);
  assert.match(svg, new RegExp(`>${ts[0].toFixed(1)}</text>`)); assert.match(svg, new RegExp(`>${ts.at(-1).toFixed(1)}</text>`));
  assert.match(svg, /<line class="fit"/);
  assert.doesNotMatch(svg, /NaN/);
  assert.match(p.$("dTrack").getAttribute("aria-label"), new RegExp(`${m.track.length} positions from ${ts[0].toFixed(1)} to ${ts.at(-1).toFixed(1)}`));
  assert.match(p.$("dTrackNote").textContent, /^19 visits\. The dashed line is a straight-line fit to these points \(8\.\d\d″\/yr\)/);
  p.close();
});

test("investigate links: sky map and Webb at the candidate's RA/Dec, Backyard Worlds, SIMBAD", async () => {
  const p = await open();
  for (const id of ["8545-0003", "10226-0001", byRank[0].id]) {
    const m = BOARD.candidates.find((x) => x.id === id);
    p.window.Survey.openCandidate(id);
    const q = new URL(p.$("dMap").href, "http://x/").searchParams;
    assert.equal(+q.get("ra"), +m.ra.toFixed(5), id); assert.equal(+q.get("dec"), +m.dec.toFixed(5), id);
    assert.match(p.$("dMap").href, /^observatory\.html\?ra=/);
    assert.equal(p.$("dWebb").href, p.$("dMap").href);
    assert.equal(p.$("dByw").href, "https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9");
    assert.match(p.$("dSimbad").href, new RegExp(`Coord=${m.ra.toFixed(5)}%20`));
    p.window.Survey.closeDrawer();
  }
  const html = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "app", "survey.html"), "utf8");
  for (const id of ["dByw", "dSimbad"]) assert.match(html, new RegExp(`id="${id}"[^>]*target="_blank" rel="noopener noreferrer"`), id);
  p.close();
});

test("copy coordinates: sexagesimal and degrees go to the clipboard", async () => {
  const p = await open();
  let copied = null;
  p.window.navigator.clipboard.writeText = async (t) => { copied = t; };
  p.window.Survey.openCandidate("8545-0003");
  const m = BOARD.candidates.find((x) => x.id === "8545-0003"), s = C.sexa(m.ra, m.dec);
  assert.equal(p.$("dCoords").textContent, `${s.ra} ${s.dec} (RA ${m.ra.toFixed(5)}°, Dec ${m.dec.toFixed(5)}°)`);
  p.$("dCopy").click();
  await p.settle(10);
  assert.equal(copied, p.$("dCoords").textContent);
  assert.equal(p.$("dCopyMsg").textContent, "Copied to the clipboard.");
  p.close();
});

test("copy coordinates: a blocked clipboard says how to copy by hand", async () => {
  const p = await open();
  p.window.navigator.clipboard.writeText = async () => { throw new Error("NotAllowedError"); };
  p.window.Survey.openCandidate("8545-0003");
  p.$("dCopy").click();
  await p.settle(10);
  assert.match(p.$("dCopyMsg").textContent, /select the coordinates above/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("Escape, the close button and the backdrop close the drawer; focus goes back to the row", async () => {
  const p = await open(), opener = { focus() { p.document.activeElement = this; } };
  for (const how of ["escape", "button", "scrim"]) {
    p.document.activeElement = opener;
    p.window.Survey.openCandidate("8545-0003");
    assert.equal(p.$("svMain").inert, true, "the page behind is inert");
    assert.equal(p.$("drawer").getAttribute("aria-hidden"), "false");
    if (how === "escape") p.key(p.document.body, "Escape");
    else if (how === "button") p.$("dClose").click();
    else p.$("scrim").click();
    assert.equal(p.$("drawer").hidden, true, how); assert.equal(p.$("scrim").hidden, true, how);
    assert.equal(p.$("svMain").inert, false, how);
    assert.equal(p.document.activeElement, opener, how);
  }
  p.key(p.document.body, "Escape");   // nothing open: nothing happens
  assert.deepEqual(p.errors, []);
  p.close();
});

test("the tile link in the drawer closes it and filters the table to that tile", async () => {
  const p = await open();
  p.window.Survey.openCandidate("10226-0001");
  p.$("dNums").dispatchEvent({ type: "click", target: { closest: (s) => (s === "[data-tile]" ? { dataset: { tile: "10226" } } : null) } });
  assert.equal(p.$("drawer").hidden, true);
  assert.equal(p.$("fTile").value, "10226");
  assert.deepEqual(rowIds(p), byRank.filter((m) => m.k5 === 10226).map((m) => m.id));
  p.close();
});

// ---------- the live sky view (Aladin Lite, loaded only when a candidate is opened) ----------
test("sky view: Aladin centred on the candidate with its NEOWISE track drawn", async () => {
  const p = await open(), { A, view, calls } = fakeAladin();
  assert.equal(calls.length, 0);
  p.window.A = A;
  p.window.Survey.openCandidate("10226-0001");
  await p.settle(20);
  const m = BOARD.candidates.find((x) => x.id === "10226-0001");
  assert.equal(calls.length, 1); assert.equal(calls[0][1], "#dSky");
  assert.deepEqual(view.at, [m.ra, m.dec]);
  assert.ok(view.fov >= 0.03 && view.fov <= 1, `fov ${view.fov}`);
  const track = view.overlays[0].items[0].pts;
  assert.equal(track.length, m.track.length);
  const first = m.track.slice().sort((a, b) => a[0] - b[0])[0];
  assert.deepEqual(Array.from(track[0]), [first[1], first[2]], "the polyline starts at the earliest visit");   // Array.from: the page's arrays come from another realm
  assert.equal(view.catalogs[0].items.length, 2, "first and last positions marked");
  assert.match(view.base.url, /SPHEREx\/spherex_allsky_cube$/);
  assert.equal(view.base.slice, 95, "the 4.6 µm slice, like NEOWISE W2");
  assert.match(p.$("dSkyMsg").textContent, /^SPHEREx \(2025, 4\.6 µm\) under the NEOWISE track/);
  p.close();
});

test("sky view: the SPHEREx / AllWISE switch changes the picture underneath", async () => {
  const p = await open(), { A, view } = fakeAladin();
  p.window.A = A;
  p.window.Survey.openCandidate("8545-0003");
  await p.settle(20);
  p.$("dSrcWise").click();
  await p.settle(10);
  assert.match(view.base.url, /AllWISE\/RGB-W4-W2-W1$/);
  assert.equal(p.$("dSrcWise").getAttribute("aria-pressed"), "true"); assert.equal(p.$("dSrcSpherex").getAttribute("aria-pressed"), "false");
  assert.match(p.$("dSkyMsg").textContent, /^AllWISE colour/);
  p.$("dSrcSpherex").click();
  assert.match(view.base.url, /spherex_allsky_cube$/);
  p.close();
});

test("sky view: one Aladin for every candidate, and the last one opened wins", async () => {
  const p = await open(), { A, view, calls } = fakeAladin();
  p.window.A = A;
  for (const id of ["8545-0003", byRank[5].id, "10226-0001"]) p.window.Survey.openCandidate(id);
  await p.settle(30);
  const m = BOARD.candidates.find((x) => x.id === "10226-0001");
  assert.equal(calls.length, 1);
  assert.deepEqual(view.at, [m.ra, m.dec]);
  assert.equal(view.overlays[0].items.length, 1);
  p.close();
});

test("sky view: when Aladin cannot load (offline), the drawer says so and still works", async () => {
  const p = await open();
  p.window.Survey.openCandidate("8545-0003");   // no window.A: the dynamic import fails in this fake browser
  await p.settle(30);
  assert.match(p.$("dSkyMsg").textContent, /could not load/);
  assert.match(p.$("dMap").href, /^observatory\.html\?ra=/);
  assert.deepEqual(p.errors, []);
  p.close();
});

// ---------- the all-sky map ----------
test("map: one polygon per searched tile, at the projected HEALPix centre", async () => {
  const p = await open(), tiles = p.window.Survey.mapTiles();
  assert.equal(tiles.length, SUMMARY.tiles.length);
  for (const k of [8545, 10226, 7945]) {
    const t = tiles.find((x) => x.k5 === k), c = C.pix2ang(k), [x, y] = C.project(c.ra, c.dec);
    assert.ok(Math.abs(t.x - x) < 1e-9 && Math.abs(t.y - y) < 1e-9, `k5 ${k}`);
    assert.equal(t.poly.length, 4);
  }
  const kap = tiles.find((x) => x.k5 === 8545);   // RA 76.5 (east of 0h: left), Dec −45 (south: lower half)
  assert.ok(kap.x < 500 && kap.y > 250);
  p.close();
});

test("map: tiles are coloured by what they hold", async () => {
  const p = await open(), tiles = p.window.Survey.mapTiles();
  for (const [k5, movers, unex] of SUMMARY.tiles) {
    const t = tiles.find((x) => x.k5 === k5);
    assert.equal(t.kind, unex > 0 ? "unexplained" : movers > 0 ? "movers" : "none", `k5 ${k5}`);
  }
  assert.equal(tiles.find((x) => x.k5 === 10226).kind, "unexplained");
  const fills = [];
  const ctx = p.$("skyMap").getContext("2d");
  Object.defineProperty(ctx, "fillStyle", { set(v) { fills.push(v); }, get() { return fills.at(-1); }, configurable: true });
  p.document.dispatchEvent({ type: "themechange" });   // redraws with the theme's colours
  assert.ok(fills.includes("#9A5A00") && fills.includes("#2864C5"), "candidate amber and accent blue (Day tokens)");
  assert.deepEqual(p.document.badDraws, []);
  p.close();
});

test("map: clicking a tile filters the table to it; clicking again or Clear removes the filter", async () => {
  const p = await open(), t = p.window.Survey.mapTiles().find((x) => x.k5 === 8545);
  const click = (x, y) => p.$("skyMap").dispatchEvent({ type: "click", offsetX: (x * 900) / 1000, offsetY: (y * 300) / 500 });   // fake canvas is 900×300 on screen
  click(t.x, t.y);
  assert.equal(p.$("fTile").value, "8545");
  assert.deepEqual(rowIds(p), byRank.filter((m) => m.k5 === 8545).map((m) => m.id));
  assert.match(p.$("tileInfo").innerHTML, /<b>Tile 8545<\/b>: \d+ movers?, 0 unexplained; 1 in the ranked list\. <a href="#candidates">/);
  assert.match(p.window.location.search, /tile=8545/);
  click(t.x + 1, t.y - 1);
  assert.equal(p.$("fTile").value, "", "second click on the same tile clears it");
  click(t.x, t.y);
  p.$("tileClear").click();
  assert.equal(p.$("fTile").value, ""); assert.equal(rowIds(p).length, 50);
  click(5, 5);   // outside the sky: nothing
  assert.equal(p.$("fTile").value, "");
  p.close();
});

test("map: hovering a tile shows what it holds", async () => {
  const p = await open(), t = p.window.Survey.mapTiles().find((x) => x.k5 === 10226), row = SUMMARY.tiles.find((x) => x[0] === 10226);
  p.$("skyMap").dispatchEvent({ type: "mousemove", offsetX: (t.x * 900) / 1000, offsetY: (t.y * 300) / 500 });
  assert.equal(p.$("mapTip").hidden, false);
  assert.match(p.$("mapTip").textContent, new RegExp(`^Tile 10226 · ${row[1]} movers · ${row[2]} unexplained · centre RA 133\\.6°, Dec −?-?7\\.2°$`));
  p.$("skyMap").dispatchEvent({ type: "mouseleave" });
  assert.equal(p.$("mapTip").hidden, true);
  assert.match(p.$("skyMap").getAttribute("aria-label"), /^All-sky map in equatorial coordinates: 640 of 12,288 tiles searched/);
  assert.match(p.$("mapGrid").innerHTML, /class="g-gal"/); assert.match(p.$("mapGrid").innerHTML, /class="g-ecl"/);
  assert.match(p.$("mapGrid").innerHTML, />4h</);
  p.close();
});

// ---------- validation, limits, credits ----------
test("validation: completeness by motion and brightness, false alarms, famous stars", async () => {
  const p = await open(), h = p.$("valBody").innerHTML;
  assert.match(h, /We hid 2,400 fake moving sources/);
  assert.match(h, /It found <b>83\.3%<\/b> of them/);
  assert.equal((h.match(/<li><span class="bl">/g) || []).length, 12, "6 motion bins + 6 brightness bins");
  assert.match(h, /<span class="bl">0\.15–0\.3<\/span>[\s\S]*?<b class="mono">55%<\/b><small>220 of 400<\/small>/);
  assert.match(h, /<span class="bl">14\.5–15\.5<\/span>[\s\S]*?<b class="mono">58%<\/b>/);
  assert.match(h, /<b class="mono">2<\/b> false movers in 8 test tiles with no real movers/);
  assert.match(h, /8 of 9 known high-motion objects/);
  for (const name of ["Barnard&#39;s Star", "Kapteyn&#39;s Star", "WISE 0855-0714"]) assert.match(h, new RegExp(`<th scope="row">${name}</th><td>✓ found`));
  assert.match(h, /<th scope="row">61 Cygni A<\/th><td>✗ missed<small>Saturated/);
  assert.match(h, /median of 5\.2 mas\/yr \(1\.1%\)/);
  p.close();
});

test("limits, method and the date of the results come from the summary", async () => {
  const p = await open();
  const li = [...p.$("limitsList").innerHTML.matchAll(/<li>([^<]*)<\/li>/g)].map((m) => m[1]);
  assert.deepEqual(li, SUMMARY.limits.map(C.esc));
  assert.equal(p.$("methodText").textContent, SUMMARY.method);
  assert.equal(p.$("methodBox").hidden, false);
  assert.equal(p.$("genTime").textContent, "Results generated 2026-11-15 08:42:10 UTC.");
  p.close();
});

test("data from the files is escaped everywhere it is shown", async () => {
  const evil = "<img src=x onerror=alert(1)>";
  const board = { ...BOARD, candidates: [{ ...BOARD.candidates[0], id: evil, reasons: [evil], class: evil, flags: [evil] }] };
  const summary = { ...SUMMARY, limits: [evil], validation: { known: [{ name: evil, recovered: true, note: evil }] } };
  const p = await open("", { summary, board });
  p.window.Survey.openCandidate(evil);
  for (const id of ["candBody", "dReasons", "dNums", "limitsList", "valBody"]) assert.doesNotMatch(p.$(id).innerHTML, /<img/, id);
  assert.equal(p.$("dTitle").textContent, evil, "plain text is fine as textContent");
  p.close();
});
