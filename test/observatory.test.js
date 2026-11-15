// Behaviour tests for the Observatory page (app/observatory.html + app.js and friends), run in a fake browser.
// Run from the repository root:  node --test test/observatory.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { openPage } = require("./fakepage");

const INDEX = require("../app/data/index.json");
const nameOf = (id) => INDEX.find((t) => t.id === id).name;
const open = (q, opts) => openPage("observatory.html", q, opts);
const search = (p) => new URLSearchParams(p.window.location.search);

test("loads every target without errors or NaN in the drawing", async () => {
  for (const { id, name } of INDEX) {
    const p = open(`?target=${id}`);
    await p.settle(150);
    assert.equal(p.$("tName").textContent, name, id);
    assert.match(p.$("frameLbl").textContent, /^1\/\d+ · 2010\.5$/, id);
    assert.deepEqual(p.errors, [], id);
    assert.deepEqual(p.document.badDraws, [], id);
    p.close();
  }
});

test("switching targets quickly shows the last one picked, even if an earlier one answers later", async () => {
  const p = open("?target=barnard", { delays: { "data/r_dra/": 200 } });
  await p.settle(100);
  p.window.WANDERERS.openTarget("r_dra");             // slow to arrive
  await p.settle(20);
  p.window.WANDERERS.openTarget("wise0855");          // picked last
  await p.settle(500);
  assert.equal(p.$("tName").textContent, nameOf("wise0855"));
  assert.equal(search(p).get("target"), "wise0855");
  assert.match(p.$("frameLbl").textContent, new RegExp(`^1/${require("../app/data/wise0855/target.json").frames.w2.length} `));
  assert.deepEqual(p.errors, []);
  p.close();
});

test("six missions clicked 0 ms apart, answers in any order: the last click wins, pixels included", async (t) => {
  const order = ["barnard", "wise0855", "r_dra", "eps_indi_b", "pos_217p4398_s62p6795", "rw_aur"];
  const slow = { barnard: 40, wise0855: 220, r_dra: 90, eps_indi_b: 250, pos_217p4398_s62p6795: 180, rw_aur: 60 };
  const delays = Object.fromEntries(order.map((id) => [`data/${id}/`, (url, n) => (n ? slow[id] : 0)]));   // first page load is quick
  const p = open("?target=barnard", { delays });
  t.after(p.close);
  await p.settle(200);
  for (const id of order) p.window.WANDERERS.openTarget(id);
  await p.settle(900);
  assert.equal(p.$("tName").textContent, nameOf("rw_aur"));
  assert.equal(search(p).get("target"), "rw_aur");
  assert.match(p.$("verdict").innerHTML, new RegExp(require("../app/data/rw_aur/target.json").evidence.classification.slice(0, 20).replace(/[()]/g, ".")));
  let used = null;
  p.$("sky").getContext("2d").drawImage = (im) => { used = used || im; };
  p.fire(p.$("zoom"), "input");
  assert.match(used.src, /data\/rw_aur\/w2_wise2010\.png$/);
  assert.deepEqual(p.errors, []);
});

test("a slow image from the previous target is never used for the new one", async () => {
  // both targets name their first frame w2_wise2010.png: the late r_dra image must not land in wise0855's cache
  const p = open("?target=barnard", { delays: { "data/r_dra/w2_wise2010.png": 200 } });
  await p.settle(100);
  p.window.WANDERERS.openTarget("r_dra");
  await p.settle(60);
  p.window.WANDERERS.openTarget("wise0855");
  await p.settle(400);
  const drawn = p.$("sky").getContext("2d");   // the canvas draws S.imgs[...]: check the image object it was given
  let used = null;
  drawn.drawImage = (im) => { used = used || im; };
  p.fire(p.$("zoom"), "input");                // redraw
  assert.ok(used, "an image was drawn");
  assert.match(used.src, /data\/wise0855\/w2_wise2010\.png$/);
  p.close();
});

test("an unknown ?target falls back to the first target instead of hanging on Loading…", async () => {
  for (const q of ["?target=nope", "?target=../data", "?target=constructor"]) {
    const p = open(q);
    await p.settle(150);
    assert.equal(p.$("tName").textContent, INDEX[0].name, q);
    assert.deepEqual(p.errors, [], q);
    p.close();
  }
});

test("?ch= only picks a channel the target really has frames in", async () => {
  for (const [ch, want] of [["w1", "w1"], ["d3", "d3"], ["d9", "w2"], ["constructor", "w2"], ["__proto__", "w2"], ["toString", "w2"]]) {
    const p = open(`?target=barnard&ch=${ch}`);
    await p.settle(150);
    assert.deepEqual(p.errors, [], ch);
    const n = require("../app/data/barnard/target.json").frames[want].length;
    assert.match(p.$("frameLbl").textContent, new RegExp(`^1/${n} `), ch);
    assert.match(p.$("channels").innerHTML + p.$("detPick").innerHTML, new RegExp(`data-ch="${want}" class="on"`), ch);   // D1-D6 sit in the detector switch
    p.close();
  }
});

// ---------- keyboard ----------
test("Space and the arrow keys blink the time-lapse, but leave buttons, selects and other tabs alone", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(150);
  const playing = () => p.$("play").textContent !== "▶ Blink", frame = () => p.$("frameLbl").textContent;
  const f0 = frame();

  let ev = p.key(p.$("copyLink"), " ");                        // Space on a focused button presses that button
  assert.equal(ev.defaultPrevented, false); assert.equal(playing(), false);
  ev = p.key(p.$("mA"), " ");                                  // ... opens a select
  assert.equal(ev.defaultPrevented, false); assert.equal(playing(), false);
  p.key(p.$("mA"), "ArrowRight");                              // arrows change the select, not the frame
  assert.equal(frame(), f0);
  p.key(p.$("sky"), "ArrowRight", { metaKey: true });          // browser shortcuts pass through
  assert.equal(frame(), f0);

  p.key(p.document.body, "ArrowRight");                        // nothing focused: step the time-lapse
  assert.notEqual(frame(), f0);
  ev = p.key(p.document.body, " ");
  assert.equal(ev.defaultPrevented, true); assert.equal(playing(), true);
  p.key(p.document.body, " "); assert.equal(playing(), false);

  p.window.WANDERERS.selectTab("stars");                       // hidden time-lapse: keys belong to the Star database
  const f1 = frame();
  p.key(p.document.body, "ArrowRight"); p.key(p.document.body, "ArrowLeft");
  assert.equal(frame(), f1);
  p.key(p.document.body, " "); assert.equal(playing(), false);
});

// ---------- sky map ----------
// Aladin Lite stand-in: overlays and catalogues remember what is drawn on them.
function fakeAladin() {
  const layer = () => ({ items: [], add(x) { this.items.push(x); }, addSources(xs) { this.items.push(...xs); }, removeAll() { this.items = []; } });
  const made = [];
  const A = {
    init: Promise.resolve(),
    aladin: () => ({ gotoRaDec() {}, setFoV() {}, setBaseImageLayer() {}, addOverlay() {}, addCatalog() {} }),
    imageHiPS: () => ({ setSliceNumber() {} }),
    graphicOverlay: (o) => { const l = layer(); l.opts = o; made.push(l); return l; },
    catalog: (o) => { const l = layer(); l.opts = o; made.push(l); return l; },
    polyline: (pts) => ({ pts }), source: (ra, dec, o) => ({ ra, dec, o }),
  };
  return { A, made };
}

test("sky map: a slow path for the previous target is not drawn over the next one", async (t) => {
  const p = open("?target=barnard", { delays: { "pred/wanderers_r_dra.json": 250 } });
  t.after(p.close);
  const { A, made } = fakeAladin();
  p.window.A = A;
  await p.settle(200);
  p.$("tabMap").onclick();
  await p.settle(100);
  p.window.WANDERERS.openTarget("r_dra");          // its path file is slow
  await p.settle(60);
  p.window.WANDERERS.openTarget("barnard");
  p.$("tabMap").onclick();
  await p.settle(500);
  const lines = made.filter((l) => l.opts && l.opts.lineWidth === 2.5).flatMap((l) => l.items);   // path taken / path ahead
  assert.ok(lines.length, "Barnard's path is drawn");
  for (const ln of lines) for (const [ra] of ln.pts) assert.ok(Math.abs(ra - 269.45) < 0.1, `a point at RA ${ra} is not Barnard's Star`);
  const year = made.find((l) => l.opts && l.opts.name === "year").items;
  assert.equal(year.length, 1); assert.ok(Math.abs(year[0].ra - 269.45) < 0.1, "the year marker follows Barnard's Star");
});

// ---------- Star database tab ----------
test("Star database: a slow learnt path for the previous star is not drawn under the star picked after it", async (t) => {
  const p = open("?target=barnard", { delays: { "stars/pred/hip87937.json": 200 } });
  t.after(p.close);
  await p.settle(150);
  p.window.WANDERERS.selectTab("stars");
  await p.settle(100);
  p.window.StarsTab.open("hip87937");                  // Barnard's Star: path arrives late
  await p.settle(30);
  p.window.StarsTab.open("hip104214");                 // 61 Cygni, picked last
  await p.settle(400);
  assert.match(p.$("starDetail").innerHTML, /<h3>61 Cygni<\/h3>/);
  assert.match(p.$("starChart").getAttribute("aria-label"), /^Path of 61 Cygni /);
  assert.equal(search(p).get("star"), "hip104214");
  assert.deepEqual(p.errors, []);
});

test("Star database: ?star= accepts a name as well as a key", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(150);
  p.window.WANDERERS.selectTab("stars");
  for (const [q, name] of [["Vega", "Vega"], ["alpha lyrae", "Vega"], ["Barnard's Star", "Barnard&#39;s Star"], ["hip87937", "Barnard&#39;s Star"]]) {
    p.window.StarsTab.open(q);
    await p.settle(250);
    assert.match(p.$("starDetail").innerHTML, new RegExp(`<h3>${name}</h3>`), q);
    assert.match(search(p).get("star"), /^[a-z0-9_]+$/, `${q}: the link keeps the key`);
  }
  p.window.StarsTab.open("Not A Star");
  await p.settle(100);
  assert.equal(p.$("starMsg").textContent, "That star is not in the database.");
});

test("Star database: the 'no star by that name' message goes once a search finds something", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(150);
  const type = async (v) => { p.$("starQ").value = v; p.$("starQ").dispatchEvent({ type: "input", target: p.$("starQ") }); await p.settle(150); };
  await type("zzzzqq");
  assert.match(p.$("starMsg").textContent, /No star by that name/);
  await type("Vega");
  assert.doesNotMatch(p.$("starMsg").textContent, /No star by that name/);
  assert.doesNotMatch(p.$("starPredMsg").textContent, /node server|pipeline/);
});

// ---------- styles (checked in a headless browser while fixing; here the rules are pinned) ----------
test("styles: Aladin's own buttons are left alone, and [hidden] beats display: grid", () => {
  const css = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "app", "style.css"), "utf8");
  const rules = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
  for (const r of rules.filter((x) => /background:\s*var\(--surface\)/.test(x.body) && /(^|,|\s)\.obs button\b/.test(x.sel)))
    assert.match(r.sel, /:not\(:where\(\.aladin button\)\)/, `"${r.sel}" would paint Aladin's zoom and fullscreen buttons`);
  assert.ok(rules.some((r) => r.sel === ".obs [hidden]" && /display:\s*none\s*!important/.test(r.body)), "a [hidden] rule");
  assert.ok(rules.some((r) => r.sel === ".map-controls label" && /display:\s*grid/.test(r.body)), "(the rule it has to beat)");
});

// ---------- the coordinate box ----------
function typeCoords(p, ra, dec) {
  p.$("raIn").value = ra; p.$("decIn").value = dec;
  p.$("coordForm").onsubmit({ preventDefault() {} });
  return p.$("coordMsg").textContent;
}

test("coordinates: hours, degrees and the Star database's own format all read the same way", async () => {
  const p = open("?target=barnard");
  await p.settle(150);
  const cases = [
    [["08h55m10.831s", "-07d14m42.53s"], /Matched WISE 0855/],
    [["133.795", "-7.245"], /Matched WISE 0855/],
    [["08h 55m 10.83s", "−07° 14′ 42.5″"], /Matched WISE 0855/],      // copied from the Star database card (Unicode minus and primes)
    [["17h 57m 48.50s", "+04° 41′ 36.2″"], /Matched Barnard/],
    [["17 57 48.5", "+04 41 36"], /Matched Barnard/],                  // sexagesimal RA without letters is hours
    [["12:30:00", "-45:00:00"], /RA 187\.5000°, Dec -45\.0000°/],      // not prepared: the heading names the position
    [["12 30 00", "-45 00 00"], /RA 187\.5000°, Dec -45\.0000°/],
    [["4h 41m 36s", "4°41′36″"], /RA 70\.4000°, Dec 4\.6933°/],        // primes without spaces
    [["24h00m00s", "0"], /RA 0\.0000°, Dec 0\.0000°/],                // 24h is 0h
    [["0", "-90"], /RA 0\.0000°, Dec -90\.0000°/],
    [["359.9999", "89.9"], /RA 359\.9999°, Dec 89\.9000°/],
  ];
  for (const [[ra, dec], want] of cases) assert.match(`${typeCoords(p, ra, dec)} | ${p.$("tName").textContent}`, want, `${ra} ${dec}`);
  p.close();
});

test("coordinates: impossible positions are refused instead of searched", async () => {
  const p = open("?target=barnard");
  await p.settle(150);
  for (const [ra, dec] of [["10", "95"], ["10", "-90.5"], ["1e5", "1e5"], ["400", "0"], ["-0.5", "0"], ["25h", "0"]])
    assert.match(typeCoords(p, ra, dec), /RA runs from 0 to 360/, `${ra} ${dec}`);
  for (const [ra, dec] of [["", ""], ["abc", "def"], ["12", ""], ["12 30 00 -45 00 00", "0"]])
    assert.equal(typeCoords(p, ra, dec), "Could not read those coordinates.", `${ra} ${dec}`);
  p.close();
});

test("example buttons round to the next minute instead of showing 60 seconds", async () => {
  const ra = 15 * (10 + 59 / 60 + 59.999 / 3600), dec = -(4 + 59 / 60 + 59.97 / 3600);
  const p = open("?target=barnard", { files: { "data/index.json": [{ id: "barnard", name: "Round me", teaser: "", ra, dec, fov: 300 }] } });
  await p.settle(150);
  assert.match(p.$("examples").innerHTML, /Round me<span>11h00m00\.00s -05d00m00\.0s<\/span>/);
  p.close();
});

test("typed coordinates hide the previous star's path card on every tab", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(200);
  assert.equal(p.$("pathCard").hidden, false, "Barnard's Star has a path card");
  typeCoords(p, "10", "20");                                   // not cached: the sky map opens there
  await p.settle(50);
  for (const tab of ["map", "webb", "flip", "map"]) {
    p.window.WANDERERS.selectTab(tab);
    assert.equal(p.$("pathCard").hidden, true, `${tab}: no path is known for typed coordinates`);
  }
  p.window.WANDERERS.openTarget("wise0855");                   // a target again: its card comes back
  await p.settle(200);
  assert.equal(p.$("pathCard").hidden, false);
  assert.match(p.$("pathBody").innerHTML, /wanderers_wise0855/);
});

// ---------- what the page is about: heading, evidence, path and URL follow the current subject ----------
const nameSearch = async (p, q) => {
  p.$("nameIn").value = q;
  p.$("nameIn").dispatchEvent({ type: "input" }); await p.settle(30);
  p.$("nameIn").dispatchEvent({ type: "keydown", key: "Enter", preventDefault() {} }); await p.settle(200);
};

test("uncached coordinates in the link: the heading names the position and the evidence says it is not analysed", async (t) => {
  const p = open("?ra=279.2347&dec=38.7837");
  t.after(p.close);
  await p.settle(200);
  assert.equal(p.$("tName").textContent, "RA 279.2347°, Dec 38.7837°");
  assert.match(p.$("verdict").innerHTML, /NOT ANALYSED/);
  assert.doesNotMatch(p.$("coordMsg").textContent, /python|pipeline|node server/);
  p.$("tabFlip").onclick();                                    // the time-lapse belongs to a mission
  await p.settle(200);
  assert.equal(p.$("tName").textContent, INDEX[0].name);
});

test("a star found by name: heading, evidence, Webb and the path follow it; Time-lapse returns to the mission", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(200);
  await nameSearch(p, "Vega");
  assert.equal(p.$("tName").textContent, "Vega");
  assert.match(p.$("verdict").innerHTML, /NOT ANALYSED/);
  assert.equal(p.$("checks").innerHTML, "");
  assert.equal(p.$("changes").hidden, true);
  assert.equal(p.$("starCard").hidden, false);
  p.$("tabFlip").onclick();                                    // back to the time-lapse: Barnard's Star again, with its own path
  await p.settle(300);
  assert.equal(p.$("tName").textContent, nameOf("barnard"));
  assert.equal(p.$("starCard").hidden, true, "the Vega card goes with the subject");
  assert.match(p.$("verdict").innerHTML, /KNOWN OBJECT|CANDIDATE/);
  assert.match(p.$("pathBody").innerHTML, /hip87937/);
  await nameSearch(p, "Vega");
  p.window.WANDERERS.openTarget("wise0855");                    // picking a mission puts the Vega card away
  await p.settle(200);
  assert.equal(p.$("starCard").hidden, true);
  assert.equal(p.$("tName").textContent, nameOf("wise0855"));
});

test("after a name search, typed coordinates drop the star's path everywhere", async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(200);
  await nameSearch(p, "Vega");
  typeCoords(p, "10", "20");
  await p.settle(50);
  for (const tab of ["webb", "map"]) { p.window.WANDERERS.selectTab(tab); assert.equal(p.$("pathCard").hidden, true, tab); }
  assert.equal(p.$("starCard").hidden, true);
  assert.equal(p.$("tName").textContent, "RA 10.0000°, Dec 20.0000°");
});

test("Through Webb looks where the star is now, not at the field centre (Wolf 359)", async (t) => {
  const p = open("?target=pos_164p1223_n7p0153");
  t.after(p.close);
  await p.settle(200);
  p.window.WANDERERS.selectTab("webb");
  await p.settle(400);
  assert.match(p.$("webbHead").innerHTML, /Webb has imaged Wolf 359/);
});

test("URL: a channel or star from before does not stick to the next target", async (t) => {
  const p = open("?target=barnard&ch=d2");
  t.after(p.close);
  await p.settle(200);
  assert.equal(search(p).get("ch"), "d2");
  p.window.WANDERERS.openTarget("wise0855");
  await p.settle(200);
  assert.equal(search(p).get("ch"), null);
  p.window.WANDERERS.selectTab("stars");
  p.window.StarsTab.open("hip87937");
  await p.settle(300);
  assert.equal(search(p).get("star"), "hip87937");
  p.window.WANDERERS.openTarget("barnard");
  await p.settle(200);
  assert.equal(search(p).get("star"), null);
});

test("What else moved shows with the time-lapse only", async (t) => {
  const p = open("?target=wise0855");
  t.after(p.close);
  await p.settle(200);
  assert.equal(p.$("changes").hidden, false);
  for (const tab of ["stars", "map", "webb"]) { p.window.WANDERERS.selectTab(tab); assert.equal(p.$("changes").hidden, true, tab); }
  p.window.WANDERERS.selectTab("flip");
  assert.equal(p.$("changes").hidden, false);
});

test("a channel with one frame: no blink, compare, stack or difference", async (t) => {
  const p = open("?target=eps_indi_b&ch=d2");
  t.after(p.close);
  await p.settle(200);
  assert.equal(require("../app/data/eps_indi_b/target.json").frames.d2.length, 1);
  for (const id of ["play", "frame", "mOp", "mA", "mB", "mixMode", "stackAll", "tDiff"]) assert.equal(p.$(id).disabled, true, id);
  assert.match(p.$("frameLbl").textContent, /only one frame/);
  p.key(p.document.body, " ");
  assert.equal(p.$("play").textContent, "▶ Blink");
  p.$("channels").dispatchEvent({ type: "click", target: { closest: () => ({ dataset: { ch: "w2" } }) } });
  for (const id of ["play", "frame", "mOp", "stackAll", "tDiff"]) assert.equal(p.$(id).disabled, false, id);
});

test("an unknown ?target says so", async (t) => {
  const p = open("?target=nope");
  t.after(p.close);
  await p.settle(200);
  assert.match(p.$("coordMsg").textContent, /No mission called “nope”/);
});

test("coordinates: a target just across RA 0h is still matched", async () => {
  const files = { "data/index.json": [{ id: "barnard", name: "Near zero", teaser: "", ra: 359.998, dec: 10, fov: 300 }] };
  const p = open("?target=barnard", { files });
  await p.settle(150);
  assert.match(typeCoords(p, "0.002", "10"), /Matched Near zero \(14″ away\)/);
  p.close();
});
