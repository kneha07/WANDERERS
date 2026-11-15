// Behaviour tests for the home page (app/index.html + home.js), run in a fake browser.
// Run from the repository root:  node --test test/home.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { openPage } = require("./fakepage");

const EPS = require("../app/data/eps_indi_b/target.json").frames.w2;

test("home page loads without errors", async (t) => {
  const p = openPage("index.html", "");
  t.after(p.close);
  await p.settle(300);
  assert.deepEqual(p.errors, []);
  assert.match(p.$("heroStamp").textContent, /^WISE 2010 · 1\/\d+$/);
  assert.deepEqual(p.document.badDraws, []);
});

test("epoch timeline: WISE, NEOWISE and SPHEREx each get their own stretch, labels do not pile up", async (t) => {
  const p = openPage("index.html", "");
  t.after(p.close);
  await p.settle(300);
  const ax = p.$("tlAxis");
  const labels = [...ax.innerHTML.matchAll(/<span class="yr" style="left:([\d.]+)%">([^<]+)<\/span>/g)].map((m) => ({ at: +m[1], text: m[2] }));
  assert.ok(labels.length >= 4 && labels.length <= 12, `${labels.length} year labels`);
  for (let i = 1; i < labels.length; i++) assert.ok(labels[i].at - labels[i - 1].at >= 5, `"${labels[i - 1].text}" and "${labels[i].text}" overlap`);
  const at = (m) => ax.children.filter((b, j) => EPS[j].mission === m).map((b) => parseFloat(b.style.left));
  const wise = at("WISE"), neo = at("NEOWISE"), spx = at("SPHEREx");
  assert.ok(neo.length && spx.length);
  assert.ok(Math.max(...wise) < Math.min(...neo), "2010 sits left of NEOWISE");
  assert.ok(Math.max(...neo) < Math.min(...spx), "NEOWISE sits left of SPHEREx");
  assert.ok(Math.max(...neo) - Math.min(...neo) > 20, "NEOWISE years are spread out");
  assert.ok(Math.max(...spx) <= 97 && Math.min(...wise) >= 0);
  assert.equal(ax.children.length, EPS.length);
});

test("home copy matches the data: how many targets, and the NEOWISE years", () => {
  const html = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "app", "index.html"), "utf8");
  const n = require("../app/data/index.json").length, words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
  const h = /<h2 id="c4">([^<]+)<\/h2>/.exec(html)[1];
  assert.match(h, new RegExp(`^(${words[n]}|${n})\\b`, "i"), `"${h}" for ${n} target cards`);
  if (EPS.some((f) => f.mission === "NEOWISE")) assert.match(html, /NEOWISE 2014–2024 and SPHEREx 2025–26/, "hero caption names NEOWISE");
  assert.doesNotMatch(require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "app", "home.js"), "utf8"), /Run the pipeline|README/);
});

test("epoch timeline: a NEOWISE frame is not called a stack of SPHEREx images", async (t) => {
  const p = openPage("index.html", "");
  t.after(p.close);
  await p.settle(300);
  const k = EPS.findIndex((f) => f.mission === "NEOWISE");
  p.$("tlAxis").children[k].onclick();
  assert.match(p.$("tlNote").innerHTML, new RegExp(`stack of ${EPS[k].n_images} NEOWISE images`));
  const s = EPS.findIndex((f) => f.mission === "SPHEREx");
  p.$("tlAxis").children[s].onclick();
  assert.match(p.$("tlNote").innerHTML, /stack of \d+ SPHEREx image/);
});
