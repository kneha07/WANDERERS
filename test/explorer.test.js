// Explorer modes: "One universe, four ways to explore". Pure logic, privacy rules, shared data and the homepage wiring.
// node --test test/explorer.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const E = require("../app/explorer.js");
const H = require("../app/explorer-home.js");
const target = (id) => JSON.parse(read(`app/data/${id}/target.json`));

test("four modes, in order, with Research Mode open to everyone", () => {
  assert.deepEqual(E.IDS, ["kids", "teens", "adults", "research"]);
  assert.equal(E.DEFAULT, "adults");
  assert.ok(E.isPlayful("kids") && E.isPlayful("teens"));
  assert.ok(!E.isPlayful("adults") && !E.isPlayful("research"));
  for (const m of E.MODES) assert.ok(m.title && m.tag && m.blurb && m.preview.length, m.id);
});

test("resolve: ?mode= for this visit, else the saved preference, else not chosen yet", () => {
  assert.deepEqual(E.resolve(null, ""), { mode: null, fromLink: false });
  assert.deepEqual(E.resolve("kids", ""), { mode: "kids", fromLink: false });
  assert.deepEqual(E.resolve("kids", "?mode=research"), { mode: "research", fromLink: true });
  assert.deepEqual(E.resolve("teens", "?mode=wizard"), { mode: "teens", fromLink: false });
  assert.deepEqual(E.resolve("nonsense", "?target=barnard"), { mode: null, fromLink: false });
});

test("storage: saves only a valid mode id, survives blocked storage", () => {
  const store = new Map(), s = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(E.save(s, "teens"), true);
  assert.equal(E.readSaved(s), "teens");
  assert.equal(E.save(s, "age:9"), false);
  assert.equal(E.readSaved(s), "teens");
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(E.readSaved(blocked), null);
  assert.equal(E.save(blocked, "kids"), false);
  assert.equal(E.readSaved(undefined), null);
});

test("privacy: one stored key, no fields that could collect an age or identity, no network beyond app/data", () => {
  const code = (read("app/explorer.js") + read("app/explorer-home.js")).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.equal(E.KEY, "wanderers-mode");
  assert.doesNotMatch(code, /<input|<select|<textarea|prompt\(|type="(date|email|tel|number|text)"/i, "no form fields");
  assert.equal((code.match(/setItem\(/g) || []).length, 1, "the only thing written to storage is the mode");
  assert.doesNotMatch(code, /fetch\(\s*["'`]?(https?:|\/?api\/)/i, "reads only app/data");
  assert.match(read("app/explorer.js"), /No account or personal information required/);
  assert.match(read("app/explorer.js"), /not an age check: anyone can use Research Mode/);
});

test("every concept has an explanation for every mode; General Explorer is the fallback", () => {
  for (const [concept, layers] of Object.entries(E.EXPLAIN)) {
    for (const m of E.IDS) assert.ok(layers[m] && layers[m].length > 20, `${concept}/${m}`);
  }
  assert.equal(E.explain("motion", "wizard"), E.EXPLAIN.motion.adults);
  assert.equal(E.explain("nothing", "kids"), "");
});

test("facts come from the evidence cards, not typed in", () => {
  const b = H.facts(target("barnard"));
  assert.equal(b.moved, "163″");
  assert.equal(b.span, "2010 and 2026");
  assert.match(b.measured, /^10\.40″\/yr$/);
  assert.match(H.facts(target("wise0855")).methane, /^[\d.]+×$/);
  const r = H.facts(target("r_dra"));
  assert.equal(r.moved, "", "R Draconis did not measurably move");
  assert.match(r.brightness, /^(Faded|Brightened) by [\d.]+ ± [\d.]+ mag/);
  assert.equal(r.brightnessLc[0], r.brightnessLc[0].toLowerCase());
  assert.deepEqual(H.facts(null), {});
});

test("stories: same data for Kids and Students, different words, no empty placeholders", () => {
  const ids = ["barnard", "wise0855", "r_dra", "eps_indi_b"], ts = Object.fromEntries(ids.map((i) => [i, target(i)]));
  const kids = H.buildStories("kids", ts), teens = H.buildStories("teens", ts);
  assert.equal(kids.length, 4);
  assert.deepEqual(kids.map((s) => s.id), teens.map((s) => s.id));
  for (const s of [...kids, ...teens]) {
    assert.doesNotMatch(s.title + s.text + s.chip, /\{\w+\}|undefined|null/, s.id);
    assert.ok(s.chip.length > 2, s.id);
  }
  assert.notEqual(kids[0].text, teens[0].text);
  assert.match(teens[0].text, /163″.*10\.40″\/yr.*10\.39″\/yr/);
  assert.equal(H.buildStories("kids", { barnard: ts.barnard }).length, 1, "a missing target is skipped");
  const noMove = JSON.parse(JSON.stringify(ts.barnard)); noMove.evidence.checks = [];
  assert.equal(H.buildStories("kids", { barnard: noMove }).length, 0, "a story without its fact is skipped");
});

test("mission: the true 2010 position is the measured WISE point; kids get a bigger target", () => {
  const t = target("barnard"), trk = H.trackUnits(t, "w2");
  assert.equal(trk[0].mission, "WISE");
  assert.ok(trk[0].y > trk[trk.length - 1].y, "Barnard's Star moves north (up) between 2010 and 2026");
  for (const p of trk) assert.ok(p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1);
  const truth = trk[0], near = { x: truth.x + 0.15, y: truth.y };
  assert.equal(H.judgeTap(truth, truth, "teens").found, true);
  assert.equal(H.judgeTap(near, truth, "kids").found, true);
  assert.equal(H.judgeTap(near, truth, "teens").found, false);
});

test("homepage: early mode flag matches explorer.js, sections are wired, General Explorer markup untouched", () => {
  const html = read("app/index.html");
  const boot = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((s) => s.includes("wanderers-mode"));
  assert.ok(boot, "inline mode bootstrap in <head>");
  assert.ok(html.indexOf(boot) < html.indexOf("<body"));
  for (const [saved, q, want] of [[null, "", "adults"], ["kids", "", "kids"], ["kids", "?mode=research", "research"], ["teens", "?mode=x", "teens"], ["junk", "", "adults"]]) {
    const root = { dataset: {} };
    const ctx = { document: { documentElement: root }, location: { search: q, hash: "", replace: () => {} },
      localStorage: { getItem: (k) => (k === "wanderers-mode" ? saved : null) }, matchMedia: () => ({ matches: false }) };
    vm.createContext(ctx); vm.runInContext(boot, ctx);
    assert.equal(root.dataset.mode, want, `${saved} ${q}`);
    assert.equal(root.dataset.mode, E.resolve(saved, q).mode || E.DEFAULT);
  }
  for (const id of ["discover", "storyDeck", "mission", "showScience", "research", "researchRows"]) assert.match(html, new RegExp(`id="${id}"`), id);
  assert.match(html, /<script src="explorer\.js\?v=\w+"><\/script>\s*<script src="explorer-home\.js\?v=\w+"><\/script>/);
  assert.ok(html.indexOf("explorer.js") > html.indexOf("home.js?"), "loads after home.js");
  for (const id of ["heroSky", "heroStats", "tlAxis", "evCard", "miniSpec", "targetCards"]) assert.match(html, new RegExp(`id="${id}"`), `scientific homepage keeps #${id}`);
  assert.equal((html.match(/class="[^"]*\bsci\b/g) || []).length, 6, "hero and five chapters fold away for Kids and Students");
});

test("home.js is unchanged by the explorer layer (General Explorer stays the scientific homepage)", () => {
  const css = read("app/explorer.css");
  assert.match(css, /html\[data-mode="kids"\]:not\(\.show-science\) \.sci/);
  assert.doesNotMatch(css, /html\[data-mode="adults"\][^{]*\.sci/, "no rule hides science for General Explorer");
  assert.doesNotMatch(read("app/home.js"), /Explorer|data-mode/);
});
