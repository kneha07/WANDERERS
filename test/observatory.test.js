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
