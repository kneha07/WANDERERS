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
    assert.match(p.$("channels").innerHTML, new RegExp(`data-ch="${want}" class="on"`), ch);
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
    [["12:30:00", "-45:00:00"], /--ra 187\.50000 --dec -45\.00000/],
    [["12 30 00", "-45 00 00"], /--ra 187\.50000 --dec -45\.00000/],
    [["24h00m00s", "0"], /--ra 0\.00000 --dec 0\.00000/],              // 24h is 0h
    [["0", "-90"], /--ra 0\.00000 --dec -90\.00000/],
    [["359.9999", "89.9"], /--ra 359\.99990 --dec 89\.90000/],
  ];
  for (const [[ra, dec], want] of cases) assert.match(typeCoords(p, ra, dec), want, `${ra} ${dec}`);
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

test("coordinates: a target just across RA 0h is still matched", async () => {
  const files = { "data/index.json": [{ id: "barnard", name: "Near zero", teaser: "", ra: 359.998, dec: 10, fov: 300 }] };
  const p = open("?target=barnard", { files });
  await p.settle(150);
  assert.match(typeCoords(p, "0.002", "10"), /Matched Near zero \(14″ away\)/);
  p.close();
});
