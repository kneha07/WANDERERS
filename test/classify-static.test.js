// Citizen-science classification, checked from the files and in the fake browser: both pages load classify.js and
// classify.css (versioned), the explorer and the Sky Survey mount the card where it belongs, the stylesheet follows the
// theme and phone rules, and the real pages run it with no errors and no call to the GitHub API.
// node --test test/classify-static.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { openPage } = require("./fakepage");
const C = require("../app/classify.js");

const ROOT = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const obs = read("app/observatory.html"), sv = read("app/survey.html"), css = read("app/classify.css");
const appJs = read("app/app.js"), svJs = read("app/survey.js");
const BOARD = require("./fixtures/survey/leaderboard.json"), SUMMARY = require("./fixtures/survey/summary.json");
const VERSION = /\?v=(\d{8}\w*)"/;

test("explorer: classify.css after the page styles, the card in the evidence panel, classify.js before app.js", () => {
  const head = obs.slice(0, obs.indexOf("<body"));
  assert.match(head, /<link rel="stylesheet" href="classify\.css\?v=\d{8}\w*">/);
  assert.ok(head.indexOf("style.css") < head.indexOf("classify.css") && head.indexOf("brand.css") < head.indexOf("classify.css"));
  const evidence = obs.slice(obs.indexOf('<section class="panel evidence"'), obs.indexOf('<section class="panel spectrum"'));
  assert.match(evidence, /<section id="classify" class="cls-card" aria-label="Classify this object" hidden><\/section>/);
  assert.ok(evidence.indexOf('id="insights"') < evidence.indexOf('id="classify"') && evidence.indexOf('id="classify"') < evidence.indexOf('class="ai"'),
    "after the evidence and insights, before the AI text");
  assert.match(obs, /<script src="classify\.js\?v=\d{8}\w*"><\/script>\s*<script src="app\.js\?v=\d{8}\w*"><\/script>/);
  assert.notEqual(obs.match(/app\.js\?v=(\w+)/)[1], "20261116r", "app.js changed, so its version did too");
});

test("survey: classify.css after survey.css, a card in the candidate drawer, classify.js before survey.js", () => {
  const head = sv.slice(0, sv.indexOf("<body"));
  assert.ok(head.indexOf("survey.css") < head.indexOf("classify.css?v="));
  const drawer = sv.slice(sv.indexOf('<aside class="sv-drawer"'), sv.indexOf("</aside>"));
  assert.match(drawer, /<section aria-labelledby="dClsH">\s*<h3 id="dClsH">Classify this candidate<\/h3>\s*<div id="dClassify" class="cls-card"><\/div>\s*<\/section>/);
  assert.ok(drawer.indexOf('id="dSkyH"') < drawer.indexOf('id="dClsH"') && drawer.indexOf('id="dClsH"') < drawer.indexOf('id="dNumH"'), "after the sky view");
  // classify.js must be loaded before survey.js mounts the card (other helpers may sit in between)
  const at = (re) => sv.search(re);
  assert.ok(at(/<script src="classify\.js\?v=\d{8}\w*"><\/script>/) > 0);
  assert.ok(at(/<script src="classify\.js/) < at(/<script src="theme\.js"><\/script>/));
  assert.match(sv, /<script src="theme\.js"><\/script>\s*<script src="survey\.js\?v=\d{8}\w*"><\/script>/);
  assert.notEqual(sv.match(/survey\.js\?v=(\w+)/)[1], "20261115a", "survey.js changed, so its version did too");
  assert.equal(obs.match(/classify\.js\?v=(\w+)/)[1], sv.match(/classify\.js\?v=(\w+)/)[1], "one classify.js version on both pages");
  assert.equal(obs.match(/classify\.css\?v=(\w+)/)[1], sv.match(/classify\.css\?v=(\w+)/)[1]);
  assert.ok(VERSION.test(obs) && VERSION.test(sv));
});

test("the hooks in app.js and survey.js are one mount call each (plus the survey's row badges)", () => {
  assert.match(appJs, /if \(window\.Classify\) Classify\.mount\(\$\("classify"\), \{ id, kind: "target", name: t\.name \}\);/);
  assert.match(appJs, /function showSubject[\s\S]*?\$\("classify"\)\.hidden = true;[\s\S]*?\n  \}/, "a searched star or typed position has no card");
  assert.match(svJs, /if \(root\.Classify\) root\.Classify\.mount\(\$\("dClassify"\), \{ id: m\.id, kind: "candidate", name: `candidate \$\{m\.id\}`, heading: false \}\);/);
  assert.match(svJs, /\$\("candBody"\)\.innerHTML = rows\.map\(rowHtml\)\.join\(""\);\s*if \(root\.Classify\) root\.Classify\.badges\(\$\("candBody"\)\);/);
  assert.equal((appJs.match(/Classify\./g) || []).length, 1);
  assert.equal((svJs.match(/Classify\./g) || []).length, 2);
});

test("classify.js points at the team repo's issue form and the snapshot the workflow writes", () => {
  assert.equal(C.REPO, "kneha07/WANDERERS");
  assert.ok(fs.existsSync(path.join(ROOT, ".github", "ISSUE_TEMPLATE", C.TEMPLATE)));
  assert.equal(C.DATA_URL, "data/classifications.json");
  const snap = JSON.parse(read("app/" + C.DATA_URL));
  assert.deepEqual(snap.classes, C.KEYS);
  assert.equal(snap.min_voters, C.MIN_VOTERS); assert.equal(snap.min_agreement, C.MIN_AGREEMENT);
  assert.deepEqual(snap.objects, {}, "the shipped snapshot holds no invented votes");
  assert.match(read(".github/workflows/classifications.yml"), /--out app\/data\/classifications\.json/);
});

test("classify.css: new colours are tokens in all three theme blocks, and nothing else is a fixed colour", () => {
  const blocks = [/:root \{([^}]*)\}/, /:root\[data-theme="dark"\] \{([^}]*)\}/, /:root:not\(\[data-theme\]\) \{([^}]*)\}/].map((re) => (css.match(re) || [])[1] || "");
  const names = [...blocks[0].matchAll(/(--[\w-]+):/g)].map((m) => m[1]);
  assert.ok(names.length >= 5 && names.every((n) => n.startsWith("--cls-")), names.join());
  for (const n of names) for (const b of blocks.slice(1)) assert.match(b, new RegExp(`${n}:`), `${n} in every theme`);
  assert.match(css, /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme\]\)/);
  const outside = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/:root[^{]*\{[^}]*\}/g, "").replace(/@media \(prefers-color-scheme: dark\) \{[^{]*\{[^}]*\}\s*\}/, "");
  assert.doesNotMatch(outside, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/, "no fixed colours outside the token blocks");
});

test("classify.css: 44 px touch targets, no sideways scroll at phone width, reduced motion respected", () => {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.match(body, /\.cls-card \.cls-btn \{[^}]*min-height: 44px;[^}]*min-width: 44px;/);
  assert.match(body, /\.cls-card \.cls-send \{[^}]*min-height: 44px;/);
  for (const m of body.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const [, sel, decl] = m;
    for (const w of decl.matchAll(/(?:^|;|\s)((?:min-)?width)\s*:\s*(\d+(?:\.\d+)?)px/g)) assert.ok(+w[2] <= 375, `${sel.trim()}: ${w[1]} ${w[2]}px`);
    for (const g of decl.matchAll(/minmax\(\s*(\d+)px/g)) assert.ok(+g[1] <= 375, `${sel.trim()}: minmax(${g[1]}px, …)`);
  }
  const row = /\.cls-card \.cls-row \{[^}]*grid-template-columns: ([^;]+);/.exec(body)[1];
  const fixedRem = [...row.matchAll(/(\d+(?:\.\d+)?)rem/g)].reduce((s, m) => s + +m[1], 0);
  assert.ok(fixedRem * 16 + 20 <= 358, "the two fixed columns and gaps fit a 390 px phone's card");
  assert.match(body, /@container \(max-width: 380px\) \{[\s\S]*?\.cls-card \.cls-help \{ grid-column: 1 \/ -1;/, "narrow cards move the help line under its button");
  assert.match(body, /\.cls-card \{[^}]*max-width: 100%/);
  assert.match(body, /@media \(prefers-reduced-motion: reduce\) \{\s*\.cls-card \.cls-bar i \{ transition: none; \}/);
  assert.doesNotMatch(body, /animation\s*:/);
});

test("explorer page: the target's card follows the target picked, with no errors and no GitHub API call", async () => {
  const INDEX = require("../app/data/index.json");
  const p = openPage("observatory.html", "?target=barnard");
  try {
    await p.settle(200);
    assert.equal(p.$("classify").hidden, false);
    assert.match(p.$("classify").innerHTML, /Classify this object/);
    assert.match(p.$("classify").innerHTML, /aria-label="Your classification of Barnard&#39;s Star"/);
    p.window.WANDERERS.openTarget("wise0855");
    await p.settle(250);
    assert.match(p.$("classify").innerHTML, new RegExp(`Your classification of ${INDEX.find((t) => t.id === "wise0855").name}`));
    assert.match(p.$("classify").innerHTML, /No community votes yet\./);
    assert.ok(p.fetched.some((u) => u.includes("data/classifications.json")));
    assert.ok(!p.fetched.some((u) => u.includes("api.github.com")));
    assert.deepEqual(p.errors, []);
  } finally { p.close(); }
});

test("survey page: opening a candidate fills the drawer's card; rows are offered for badges; no errors", async () => {
  const files = { "data/survey/summary.json": SUMMARY, "data/survey/leaderboard.json": BOARD };
  const p = openPage("survey.html", "", { files });
  try {
    await p.window.Survey.ready;
    await p.settle(50);
    const id = BOARD.candidates[0].id;
    assert.ok(p.window.Survey.openCandidate(id));
    const h = p.$("dClassify").innerHTML;
    assert.match(h, /Look at its track and the sky view/);
    assert.match(h, new RegExp(`Your classification of candidate ${id}`));
    assert.doesNotMatch(h, /<h3/, "the drawer's own heading labels the card");
    assert.ok(p.fetched.some((u) => u.includes("data/classifications.json")));
    assert.ok(!p.fetched.some((u) => u.includes("api.github.com")));
    assert.deepEqual(p.errors, []);
  } finally { p.close(); }
});

test("survey page still works when classify.js is not there", async () => {
  const files = { "data/survey/summary.json": SUMMARY, "data/survey/leaderboard.json": BOARD };
  const p = openPage("survey.html", "", { files, skip: ["classify.js"] });
  try {
    await p.window.Survey.ready;
    assert.ok(p.window.Survey.openCandidate(BOARD.candidates[0].id));
    assert.equal(p.$("dClassify").innerHTML, "");
    assert.deepEqual(p.errors, []);
  } finally { p.close(); }
});
