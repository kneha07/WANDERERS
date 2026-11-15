// Sky Survey page, checked from its files: every element the script uses exists, the shared brand and theme rules,
// accessible markup, a stylesheet that cannot push a 375 px phone sideways, Day/Night tokens, navigation from the
// other pages, and sample results that agree with themselves and with the contract.
// node --test test/survey-static.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process");
const Hips = require("../app/hips.js");

const ROOT = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const html = read("app/survey.html"), js = read("app/survey.js"), css = read("app/survey.css");
const SUMMARY = require("./fixtures/survey/summary.json");
const BOARD = require("./fixtures/survey/leaderboard.json");
const head = html.slice(0, html.indexOf("<body"));

test("every element id the script uses exists in the page, once", () => {
  const used = [...new Set([...js.matchAll(/\$\("([A-Za-z0-9_]+)"\)/g)].map((m) => m[1]))];
  const listed = [...js.matchAll(/for \(const id2? of \[([^\]]+)\]\)/g)].flatMap((m) => [...m[1].matchAll(/"([A-Za-z0-9_]+)"/g)].map((x) => x[1]));
  assert.ok(used.length > 40, `${used.length} ids`);
  for (const id of [...used, ...listed]) assert.equal((html.match(new RegExp(`\\bid="${id}"`, "g")) || []).length, 1, `#${id}`);
  const all = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(all).size, all.length, "no duplicate ids");
  for (const ref of [...html.matchAll(/aria-(?:labelledby|controls|describedby)="([^"]+)"/g)].flatMap((m) => m[1].split(/\s+/))) assert.ok(all.includes(ref), `aria reference #${ref}`);
  assert.ok(all.includes(html.match(/class="skip" href="#([^"]+)"/)[1]), "skip link target");
});

test("shared theme rules: bootstrap in <head>, brand.css, toggle, theme.js, favicon, theme-color", () => {
  assert.match(head, /<script>\(function \(\) \{ var t; try \{ t = localStorage\.getItem\("wanderers-theme"\)/);
  assert.match(head, /<meta name="theme-color" content="#F6F8FB">/);
  assert.match(head, /<link rel="stylesheet" href="brand\.css">/);
  assert.match(head, /<link rel="icon" href="favicon\.svg" type="image\/svg\+xml">/);
  assert.match(html, /<button class="theme-toggle" type="button"/);
  assert.match(html, /<script src="theme\.js"><\/script>\s*<script src="survey\.js\?v=\w+"><\/script>/);
  assert.ok(head.indexOf("brand.css") < head.indexOf("survey.css"), "page styles after the brand");
  assert.match(read("test/theme.test.js"), /const PAGES = \[[^\]]*"app\/survey\.html"/, "the shared theme tests cover this page");
});

test("the logo is the same Orbit Epochs mark as the home page, in the header and the footer", () => {
  const grab = (src) => [...src.matchAll(/<svg viewBox="2 2 36 36" aria-hidden="true">([\s\S]*?)<\/svg>/g)].map((m) => m[1].replace(/\s+/g, " ").trim());
  const ref = grab(read("app/index.html"))[0], got = grab(html);
  assert.equal(got.length, 2);
  for (const g of got) assert.equal(g, ref);
});

test("styles and script are versioned so a new release is not served from cache", () => {
  assert.match(html, /<link rel="stylesheet" href="survey\.css\?v=\d{8}\w*">/);
  assert.match(html, /<script src="survey\.js\?v=\d{8}\w*"><\/script>/);
});

test("navigation: Sky Survey is in the site menu here, on the home page and in the Observatory", () => {
  assert.match(html, /<nav class="site-nav" id="siteNav" aria-label="Main">[\s\S]*?<a href="survey\.html" aria-current="page">Sky Survey<\/a>/);
  for (const p of ["app/index.html", "app/observatory.html"]) {
    const nav = read(p).match(/<nav class="site-nav"[\s\S]*?<\/nav>/)[0];
    assert.match(nav, /<a href="survey\.html">Sky Survey<\/a>/, p);
  }
  const compass = read("app/compass.html");
  if (/class="site-nav"/.test(compass)) assert.match(compass, /href="survey\.html"/);   // the compass has no site menu today
});

test("accessible markup: labelled controls, a captioned table, a labelled dialog, live regions", () => {
  for (const m of html.matchAll(/<(input|select)\b[^>]*id="([^"]+)"[^>]*>/g)) {
    const [tag, , id] = [m[0], m[1], m[2]];
    const wrapped = new RegExp(`<label[^>]*>[^<]*(?:<(?!/?label)[^>]*>[^<]*)*<${m[1]}\\b[^>]*id="${id}"`).test(html) || html.includes(`for="${id}"`);
    assert.ok(wrapped || /aria-label=/.test(tag), `#${id} has a label`);
  }
  assert.match(html, /<table class="sv-table" id="candTable">\s*<caption class="visually-hidden">/);
  assert.match(js, /<th scope="col" class="\$\{cls\}" aria-sort="\$\{sort\}"><button type="button" class="sorter" data-sort=/);
  assert.match(js, /<th scope="row"><button type="button" class="cid mono" data-id=/);
  assert.match(html, /<aside class="sv-drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="dTitle"/);
  assert.match(html, /id="dClose" aria-label="Close the candidate details"/);
  assert.match(html, /<canvas id="skyMap" role="img" aria-label=/);
  assert.match(html, /id="tCount" aria-live="polite"/); assert.match(html, /id="banners" role="status" aria-live="polite"/);
  assert.match(html, /role="group" aria-label="Sky survey under the track"/);
  for (const b of html.matchAll(/<button\b[^>]*>/g)) assert.match(b[0], /type="button"/, b[0]);
  assert.match(html, /<html lang="en">/);
});

test("the stylesheet cannot push a 375 px phone sideways", () => {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of body.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const [, sel, decl] = m;
    for (const w of decl.matchAll(/(?:^|;|\s)((?:min-)?width)\s*:\s*(\d+(?:\.\d+)?)px/g))
      assert.ok(+w[2] <= 375 || /max-width\s*:/.test(decl), `${sel.trim()}: ${w[1]} ${w[2]}px without max-width`);
    for (const g of decl.matchAll(/minmax\(\s*(\d+)px/g)) assert.ok(+g[1] <= 375, `${sel.trim()}: minmax(${g[1]}px, …)`);
    for (const g of decl.matchAll(/repeat\(\s*(\d+)\s*,\s*(\d+)px/g)) assert.ok(+g[1] * +g[2] <= 375, `${sel.trim()}: fixed grid ${g[0]}`);
  }
  assert.match(body, /\.sv-table-wrap \{[^}]*overflow-x: auto;[^}]*max-width: 100%/, "the wide table scrolls inside its own box");
  assert.match(body, /\.survey main \{ overflow-x: clip; \}/);
  assert.match(body, /\.sv-drawer \{[^}]*width: min\(580px, 100%\)/, "the drawer is never wider than the screen");
  assert.match(body, /@media \(max-width: 600px\) \{[\s\S]*?\.sv-table \.hide-sm \{ display: none; \}/, "phones drop the two least important columns");
  assert.match(head, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
  assert.match(body, /\.survey \[hidden\] \{ display: none !important; \}/, "hidden buttons stay hidden although .btn sets display");
});

test("Day and Night: colours come from tokens, and new tokens exist in all three theme blocks", () => {
  const blocks = [/:root \{([^}]*)\}/, /:root\[data-theme="dark"\] \{([^}]*)\}/, /:root:not\(\[data-theme\]\) \{([^}]*)\}/].map((re) => (css.match(re) || [])[1] || "");
  const names = [...blocks[0].matchAll(/(--[\w-]+):/g)].map((m) => m[1]);
  assert.ok(names.length >= 3);
  for (const n of names) for (const b of blocks.slice(1)) assert.match(b, new RegExp(`${n}:`), `${n} in every theme`);
  assert.match(css, /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme\]\)/);
  const outside = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/:root[^{]*\{[^}]*\}/g, "").replace(/@media \(prefers-color-scheme: dark\) \{[^{]*\{[^}]*\}\s*\}/, "");
  assert.doesNotMatch(outside, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, "no fixed colours outside the token blocks");
  assert.match(js, /getComputedStyle\(document\.documentElement\)/, "the canvas map reads the theme's tokens");
  assert.match(js, /addEventListener\("themechange", \(\) => drawMap\(\)\)/, "and redraws when the theme changes");
});

test("motion: the only animation stops for people who ask for reduced motion", () => {
  const anims = [...css.matchAll(/animation:\s*([\w-]+)/g)].map((m) => m[1]).filter((a) => a !== "none");
  assert.deepEqual(anims, ["sv-in"]);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\.sv-drawer \{ animation: none; \}/);
  assert.doesNotMatch(js, /setInterval|scrollIntoView\(\{ behavior: "smooth"/, "no timers or smooth scrolling in the script");
});

test("live sky view: Aladin Lite 3.8.2 from jsdelivr and the IRSA SPHEREx / AllWISE HiPS from the contract", () => {
  assert.match(js, /"https:\/\/cdn\.jsdelivr\.net\/npm\/aladin-lite@3\.8\.2\/dist\/aladin\.js"/);
  assert.match(js, /"https:\/\/irsa\.ipac\.caltech\.edu\/data\/hips\/SPHEREx\/spherex_allsky_cube"/);
  assert.match(js, /"https:\/\/irsa\.ipac\.caltech\.edu\/data\/hips\/CDS\/AllWISE\/RGB-W4-W2-W1"/);
  assert.match(js, /await import\(ALADIN\)/, "loaded only when a candidate is opened");
  assert.doesNotMatch(html, /aladin\.js/, "not in the page's own script tags");
});

test("credits name every data source and tool", () => {
  for (const s of ["NEOWISE-R", "IRSA", "AWS", "Gaia DR3", "ESA", "SPHEREx", "AllWISE", "Aladin Lite", "CDS", "HEALPix"]) assert.ok(html.includes(s), s);
  assert.match(html, /A candidate is a lead, never a discovery\./);
});

// ---------- the sample results ----------
test("sample files are marked as sample data", () => {
  assert.equal(SUMMARY.demo, true); assert.equal(BOARD.demo, true);
});

test("sample summary agrees with itself", () => {
  assert.equal(SUMMARY.tiles.length, SUMMARY.tiles_done);
  assert.ok(Math.abs(SUMMARY.sky_fraction - SUMMARY.tiles_done / 12288) < 1e-6);
  assert.ok(Math.abs(SUMMARY.sky_deg2 - SUMMARY.tiles_done * 3.357174580844667) < 0.1);
  assert.equal(SUMMARY.movers, SUMMARY.tiles.reduce((a, t) => a + t[1], 0));
  assert.equal(SUMMARY.unexplained, SUMMARY.tiles.reduce((a, t) => a + t[2], 0));
  assert.ok(SUMMARY.detections > SUMMARY.good_detections && SUMMARY.good_detections > SUMMARY.visit_sources && SUMMARY.visit_sources > SUMMARY.tracks && SUMMARY.tracks > SUMMARY.movers);
  assert.ok(Math.abs(SUMMARY.runtime_hours * SUMMARY.tiles_per_hour - SUMMARY.tiles_done) < 1);
  for (const k of [7945, 8545, 10226, 9509, 6865, 1355, 10397, 3325, 11391]) assert.ok(SUMMARY.tiles.some((t) => t[0] === k), `validation tile ${k}`);
  assert.equal(new Set(SUMMARY.tiles.map((t) => t[0])).size, SUMMARY.tiles.length);
});

test("sample leaderboard: contract fields, contiguous ranks by score, rows inside their tiles", () => {
  const C = BOARD.candidates, tiles = new Map(SUMMARY.tiles.map((t) => [t[0], t]));
  const keys = ["id", "k5", "ra", "dec", "epoch", "pmra", "pmdec", "pm", "pm_err", "pm_snr", "chi2r", "n_visits", "span_yr", "w1", "w2", "w1w2", "plx", "plx_err", "track", "flags", "gaia", "score", "reasons", "class", "rank"];
  C.forEach((m, i) => {
    for (const k of keys) assert.ok(k in m, `${m.id} has ${k}`);
    assert.equal(m.rank, i + 1);
    if (i) assert.ok(C[i - 1].score >= m.score, "sorted by score");
    assert.ok(["unexplained", "known (Gaia)", "likely artefact", "not checked"].includes(m.class));
    assert.ok(tiles.has(m.k5), `${m.id}: its tile is in the summary`);
    assert.equal(Hips.pixel(5, m.ra, m.dec), m.k5, `${m.id} lies in tile ${m.k5}`);
    assert.ok(m.track.length >= 2 && m.track.length <= 30 && m.track.length === m.n_visits, m.id);
    assert.equal(m.class === "unexplained", m.gaia.checked && !m.gaia.match && m.class !== "likely artefact", m.id);
  });
  assert.equal(C.filter((m) => m.class === "unexplained").length, SUMMARY.unexplained);
  assert.equal(BOARD.n_candidates, SUMMARY.movers);
  const kap = C.find((m) => m.id === "8545-0003");
  assert.equal(kap.gaia.source_id, "4810594479418041856");
  assert.ok(Math.abs(kap.pm - 8644) / 8644 < 0.01, "Kapteyn's Star moves at its Gaia speed");
});

test("the sample generator is deterministic (and does not write unless asked)", () => {
  const before = fs.statSync(path.join(__dirname, "fixtures", "survey", "summary.json")).mtimeMs;
  const out = execFileSync(process.execPath, [path.join(__dirname, "fixtures", "survey", "make-fixtures.js")], { encoding: "utf8" });
  assert.equal(out.trim(), `640 tiles, ${SUMMARY.movers} movers, ${BOARD.candidates.length} candidates (${SUMMARY.unexplained} unexplained), ${SUMMARY.detections.toLocaleString("en-US")} detections`);
  assert.equal(fs.statSync(path.join(__dirname, "fixtures", "survey", "summary.json")).mtimeMs, before);
});
