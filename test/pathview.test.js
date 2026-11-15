// Tests for app/pathview.js (the path card under the console and in the Sky Compass).
// Run from the repository root:  node --test test/pathview.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");

const APP = path.join(__dirname, "..", "app");
globalThis.StarCore = require("../app/starcore.js");
require("../app/pathview.js");
const PV = globalThis.PathView;

// fetch from app/, with an optional delay per URL substring
let delays = {};
globalThis.fetch = (url) => new Promise((resolve) => {
  const ms = Object.entries(delays).find(([k]) => String(url).includes(k));
  setTimeout(() => {
    const f = path.join(APP, decodeURIComponent(String(url)));
    if (!fs.existsSync(f)) return resolve({ ok: false, json: async () => null });
    const text = fs.readFileSync(f, "utf8");
    resolve({ ok: true, json: async () => JSON.parse(text) });
  }, ms ? ms[1] : 0);
});

test("a slow path for an earlier target does not overwrite the card of the target picked after it", async () => {
  delays = { "pred/hip87937.json": 150 };            // Barnard's Star answers late
  const el = { innerHTML: "" };
  const first = PV.render(el, { target: "barnard" }), second = PV.render(el, { target: "wise0855" });
  const [a, b] = await Promise.all([first, second]);
  assert.equal(a, null, "the replaced render reports nothing");
  assert.equal(b.key, "wanderers_wise0855");
  assert.match(el.innerHTML, /star=wanderers_wise0855/);
  assert.doesNotMatch(el.innerHTML, /hip87937/);
  delays = {};
});

test("separate cards do not cancel each other", async () => {
  const a = { innerHTML: "" }, b = { innerHTML: "" };
  const [ma, mb] = await Promise.all([PV.render(a, { target: "barnard" }), PV.render(b, { target: "wise0855" })]);
  assert.equal(ma.key, "hip87937"); assert.equal(mb.key, "wanderers_wise0855");
  assert.match(a.innerHTML, /hip87937/); assert.match(b.innerHTML, /wanderers_wise0855/);
});

test("Moon-width time agrees with the evidence card's insight (same 1,800″, same rounding)", async () => {
  for (const id of ["barnard", "pos_77p9125_s45p0184", "wise0855"]) {
    const el = { innerHTML: "" };
    await PV.render(el, { target: id });
    const card = /a Moon-width every ([\d,]+) years/.exec(el.innerHTML)[1];
    const t = JSON.parse(fs.readFileSync(path.join(APP, "data", id, "target.json"), "utf8"));
    const ins = /full Moon in about ([\d,]+) years/.exec(t.insights.facts.map((f) => f.headline).join(" "))[1];
    assert.equal(card, ins, id);
  }
});

test("the 'now' dot is drawn under the year labels, so it cannot hide 2050", async () => {
  const el = { innerHTML: "" };
  await PV.render(el, { target: "barnard" });
  const svg = el.innerHTML.split("</svg>")[0];
  assert.ok(svg.indexOf('class="pv-now"') < svg.indexOf('class="pv-yr"'));
});

test("a star without known motion gets the plain message, not an error", async () => {
  const el = { innerHTML: "" };
  const m = await PV.render(el, { star: { name: "No motion", ra: 10, dec: 20, pmra: null, pmdec: null } });
  assert.equal(m, null);
  assert.match(el.innerHTML, /No motion is known/);
});
