// The "See it in the sky" button opens the Sky Compass aimed at what the console shows.
// node --test test/compass-cta.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { openPage } = require("./fakepage");

const html = (p) => fs.readFileSync(path.join(__dirname, "..", "app", p), "utf8");

test("console and home page show a real Sky Compass button, not a small text link", () => {
  for (const p of ["observatory.html", "index.html"]) {
    const a = html(p).match(/<a class="btn [^"]*compass-cta"[^>]*href="compass\.html"[^>]*>[\s\S]*?<\/a>/);
    assert.ok(a, `${p}: button`);
    assert.match(a[0], /See it in the sky/, p);
    assert.match(a[0], /<svg class="cc-icon"/, p);
  }
  assert.doesNotMatch(html("observatory.html"), /class="ws-link" href="compass\.html"/);
});

test("the button follows the target on screen", async () => {
  const p = openPage("observatory.html", "?target=wise0855");
  await p.settle(150);
  assert.equal(p.$("compassCta").href, "compass.html?target=wise0855");
  assert.match(p.$("compassCtaSub").textContent, /Find WISE 0855-0714 with your phone/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("after typed coordinates it falls back to the plain Sky Compass", async () => {
  const p = openPage("observatory.html", "?ra=10&dec=10");
  await p.settle(150);
  assert.equal(p.$("compassCta").href, "compass.html");
  p.close();
});

test("the home hero is the chooser: exactly three doors, Observatory, Sky Compass, Star Fix (A12)", () => {
  const h = html("index.html");
  const hero = h.match(/<p class="hero-lede">[\s\S]*?<div class="cta">([\s\S]*?)<\/div>\s*<p class="hero-sub"/);   // right under the lede
  assert.ok(hero, "hero buttons");
  const links = [...hero[1].matchAll(/<a class="btn [^"]*"[^>]*href="([^"]+)"/g)].map((x) => x[1]);
  assert.deepEqual(links, ["observatory.html", "compass.html", "starfix.html"]);
  const doors = [...hero[1].matchAll(/<a class="(btn [^"]*)"[\s\S]*?<b>([^<]+)<\/b><small>([^<]+)<\/small><\/span><\/a>/g)].map((x) => [x[1].includes("btn-primary"), x[2], x[3]]);
  assert.deepEqual(doors, [
    [true, "Explore the Sky", "Observatory · watch 16 years of sky change"],
    [false, "See it in the sky", "Sky Compass · point your phone up"],
    [false, "Find where you were", "Star Fix · upload a star photo"],
  ]);
  assert.equal((hero[1].match(/<svg class="cc-icon"/g) || []).length, 3, "the same two-line style for all three");
  assert.match(h.match(/<nav class="site-nav"[\s\S]*?<\/nav>/)[0], /<a href="#how">How It Works<\/a>/, "How It Works stays in the top navigation");
  assert.equal((h.match(/See it in the sky/g) || []).length, 1, "only one copy on the page");
  assert.match(h.match(/<footer[\s\S]*<\/footer>/)[0], /<a href="starfix\.html">Star Fix<\/a>/, "footer link");
});
