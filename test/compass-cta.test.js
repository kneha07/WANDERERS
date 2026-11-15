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
    assert.match(a[0], /<span class="cc-text">Visualise with Sky Compass<\/span>/, p);   // one line, same text everywhere
    assert.match(a[0], /<svg class="cc-icon"/, p);
  }
  assert.doesNotMatch(html("observatory.html"), /class="ws-link" href="compass\.html"/);
});

test("the button follows the target on screen", async () => {
  const p = openPage("observatory.html", "?target=wise0855");
  await p.settle(150);
  assert.equal(p.$("compassCta").href, "compass.html?target=wise0855");
  assert.match(p.$("compassCta").title, /aimed at WISE 0855-0714/);
  assert.deepEqual(p.errors, []);
  p.close();
});

test("after typed coordinates it falls back to the plain Sky Compass", async () => {
  const p = openPage("observatory.html", "?ra=10&dec=10");
  await p.settle(150);
  assert.equal(p.$("compassCta").href, "compass.html");
  p.close();
});

test("on the home page the button sits in the hero, right after How It Works, not at the bottom", () => {
  const h = html("index.html");
  const hero = h.match(/<div class="cta">([\s\S]*?)<\/div>\s*<dl class="hero-stats"/);
  assert.ok(hero, "hero buttons");
  const links = [...hero[1].matchAll(/<a class="btn [^"]*"[^>]*href="([^"]+)"/g)].map((x) => x[1]);
  assert.deepEqual(links, ["observatory.html", "#how", "compass.html"]);
  assert.equal((h.match(/Visualise with Sky Compass/g) || []).length, 1, "only one copy on the page");
});
