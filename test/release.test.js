// Tests for app/release.js (the "SPHEREx data" status line) and its place on the home page and the observatory.
// Run from the repository root:  node --test test/release.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const R = require("../app/release.js");
const { openPage } = require("./fakepage");

const APP = path.join(__dirname, "..", "app");
const REAL = path.join(APP, "data", "spherex_release.json");

// A status as pipeline/spherex_releases.py writes it after a good check (dates and counts made up for the test).
const OK = {
  current: "spherex_qr3", current_label: "SPHEREx Quick Release 3",
  releases: [{ name: "spherex_dr1", label: "SPHEREx Data Release 1" }, { name: "spherex_qr3", label: "SPHEREx Quick Release 3" }],
  new_release_available: false, new_releases: [], targets_behind: {}, targets: 11,
  data_through: "2026-10-02", synced: "2026-11-15T06:10:33Z", checked: "2026-11-15T12:00:00Z",
  last_attempt: "2026-11-15T12:00:00Z", error: null,
};
const NEW = { ...OK, new_release_available: true, new_releases: [{ name: "spherex_qr4", label: "SPHEREx Quick Release 4" }],
  targets_behind: { barnard: ["spherex_qr4"], wise0855: ["spherex_qr4"] } };
const FAILED = { ...OK, checked: null, error: "IRSA release check failed on 2026-11-15: IRSA TAP answered HTTP 502" };

const text = (html) => html.replace(/<[^>]+>/g, "");

// Run fn while counting console calls; release.js must stay silent.
async function silently(fn) {
  const calls = [], saved = {};
  for (const k of ["log", "info", "warn", "error", "debug"]) { saved[k] = console[k]; console[k] = (...a) => calls.push([k, ...a]); }
  try { return { value: await fn(), calls }; } finally { Object.assign(console, saved); }
}

function fakeDoc() {
  const attrs = {}, classes = new Set();
  const el = { hidden: true, innerHTML: "", setAttribute: (k, v) => { attrs[k] = v; }, attrs,
    classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), contains: (c) => classes.has(c) } };
  return { el, doc: { getElementById: (id) => (id === "spherexStatus" ? el : null) } };
}
const answer = (body, ok = true, status = 200) => async () => ({ ok, status, json: async () => (typeof body === "function" ? body() : structuredClone(body)) });

// ---------------------------------------------------------------- dates

test("dates: a day and a month, in UTC", () => {
  assert.equal(R.fmtDay("2026-11-15T06:10:33Z"), "15 Nov 2026");
  assert.equal(R.fmtDay("2026-01-01"), "1 Jan 2026");
  assert.equal(R.fmtMonth("2026-09-07"), "Sep 2026");
  assert.equal(R.fmtMonth("2026-12-31 23:59"), "Dec 2026");
});

test("dates: an offset is turned into UTC", () => {
  assert.equal(R.fmtDay("2026-11-14T22:10:33-08:00"), "15 Nov 2026");
  assert.equal(R.fmtDay("2026-11-15T01:00:00+05:30"), "14 Nov 2026");
  assert.equal(R.parseDate("2026-11-15T06:10:33Z").toISOString(), "2026-11-15T06:10:33.000Z");
});

test("dates: anything else gives nothing", () => {
  for (const bad of [null, undefined, 42, "", "soon", "2026-13-01", "2026-02-30", "2026-11-15T25:00:00Z", "15/11/2026", {}, []])
    assert.equal(R.fmtDay(bad), "", String(bad));
  assert.equal(R.parseDate("2026-02-30"), null);
});

// ---------------------------------------------------------------- what the line says

test("the status line reads like the example", () => {
  assert.equal(text(R.render(OK)), "SPHEREx Quick Release 3 · data through Oct 2026 · last synced 15 Nov 2026 · checked 15 Nov 2026");
  const d = R.describe(OK);
  assert.equal(d.note, null);
  assert.equal(d.fresh, true);
});

test("dates are marked up as <time> with an ISO date", () => {
  const html = R.render(OK);
  assert.match(html, /<time datetime="2026-10-02">Oct 2026<\/time>/);
  assert.match(html, /<time datetime="2026-11-15">15 Nov 2026<\/time>/);
  assert.doesNotMatch(html, /spx-new|spx-dot-new/);
});

test("a newer release gives a short new-data note", () => {
  const d = R.describe(NEW);
  assert.equal(d.note, "New data available at IRSA: Quick Release 4 is not yet in 2 of 11 targets.");
  assert.equal(d.fresh, false);
  const html = R.render(NEW);
  assert.match(html, /<span class="spx-new">New data available at IRSA: Quick Release 4/);
  assert.match(html, /spx-dot spx-dot-new/);
});

test("the note still shows when the file does not count targets", () => {
  const d = R.describe({ ...NEW, targets_behind: undefined, targets: undefined });
  assert.equal(d.note, "New data available at IRSA: Quick Release 4 is not yet in these views.");
  assert.match(R.describe({ ...NEW, new_releases: [] }).note, /a newer release is not yet in 2 of 11 targets/);
  assert.equal(R.describe({ ...NEW, new_release_available: "yes" }).note, null, "only a real true counts");
});

test("never checked online: says the check failed, with the date it was tried", () => {
  assert.equal(text(R.render(FAILED)), "SPHEREx Quick Release 3 · data through Oct 2026 · last synced 15 Nov 2026 · IRSA release check failed 15 Nov 2026");
  assert.match(R.render(FAILED), /spx-fail/);
  assert.match(R.describe(FAILED).title, /HTTP 502/);
});

test("a later failed check keeps the last good check date", () => {
  const st = { ...OK, last_attempt: "2026-11-22T12:00:00Z", error: "IRSA release check failed on 2026-11-22: HTTP 502" };
  assert.match(text(R.render(st)), /checked 15 Nov 2026$/);
  assert.match(R.describe(st).title, /2026-11-22/);
});

// ---------------------------------------------------------------- IRSA down, S3 bucket listed

// As pipeline/spherex_releases.py writes it when IRSA's services fail and the S3 bucket listing answers.
const VIA_S3 = { ...OK, checked: "2026-11-15T13:52:21Z", checked_via: "S3 bucket", last_attempt: "2026-11-15T13:52:19Z",
  error: "IRSA release check failed on 2026-11-15: astroquery: 502 Server Error; TAP: IRSA TAP answered HTTP 502",
  releases: [{ name: "spherex_dr1", label: "SPHEREx Data Release 1", newest_week: "2026W20_1A", newest_week_label: "2026 week 20" },
    { name: "spherex_qr3", label: "SPHEREx Quick Release 3", newest_week: "2026W40_2A", newest_week_label: "2026 week 40" }] };

test("IRSA down but the S3 bucket listed: checked, with where the answer came from", () => {
  assert.equal(text(R.render(VIA_S3)),
    "SPHEREx Quick Release 3 · data through Oct 2026 · last synced 15 Nov 2026 · checked 15 Nov 2026 (S3 listing; IRSA services down)");
  assert.doesNotMatch(R.render(VIA_S3), /spx-fail|failed/);
  assert.equal(R.describe(VIA_S3).fresh, true);
});

test("an S3 listing without an IRSA error says only where the answer came from", () => {
  assert.match(text(R.render({ ...VIA_S3, error: null })), /checked 15 Nov 2026 \(S3 listing\)$/);
});

test("the S3 note sits after the date, outside the <time> element", () => {
  assert.match(R.render(VIA_S3), /<time datetime="2026-11-15">15 Nov 2026<\/time> \(S3 listing; IRSA services down\)<\/span>/);
});

test("both IRSA and the bucket failed: still 'IRSA release check failed'", () => {
  const st = { ...FAILED, checked_via: null, error: FAILED.error + "; S3 bucket listing failed too: timeout" };
  assert.match(text(R.render(st)), /IRSA release check failed 15 Nov 2026$/);
  assert.doesNotMatch(text(R.render(st)), /S3 listing/);
});

test("a check answered by IRSA has no S3 note", () => {
  assert.match(text(R.render({ ...OK, checked_via: "IRSA" })), /checked 15 Nov 2026$/);
});

test("the title gives the newest week of each release and the IRSA error", () => {
  const title = R.describe(VIA_S3).title;
  assert.match(title, /Quick Release 3 at IRSA has images through 2026 week 40/);
  assert.match(title, /Data Release 1 at IRSA has images through 2026 week 20/);
  assert.match(title, /Last check: IRSA release check failed on 2026-11-15/);
  assert.doesNotMatch(R.describe(OK).title, /has images through/);
});

test("an S3-listed status with new data still shows the note", () => {
  const st = { ...VIA_S3, new_release_available: true, new_releases: [{ name: "spherex_qr4", label: "SPHEREx Quick Release 4" }],
    targets_behind: { barnard: ["spherex_qr4"] } };
  assert.equal(R.describe(st).note, "New data available at IRSA: Quick Release 4 is not yet in 1 of 11 targets.");
});

test("week labels from the file are escaped in the title source too", () => {
  const st = { ...VIA_S3, releases: [{ name: "spherex_qr3", label: "SPHEREx Quick Release 3", newest_week_label: "<b>x</b>" }] };
  assert.match(R.describe(st).title, /<b>x<\/b>/);                        // a title attribute: set with setAttribute
  assert.doesNotMatch(R.render(st), /<b>x/);                              // never in the HTML
});

test("missing parts are left out, not shown as blanks", () => {
  assert.equal(text(R.render({ current_label: "SPHEREx Quick Release 3" })), "SPHEREx Quick Release 3");
  assert.equal(text(R.render({ ...OK, synced: null, data_through: "garbage" })), "SPHEREx Quick Release 3 · checked 15 Nov 2026");
});

test("the label falls back to the release list", () => {
  assert.equal(R.describe({ current: "spherex_qr3", releases: OK.releases }).parts[0].text, "SPHEREx Quick Release 3");
});

test("a file that does not say which release is current shows nothing", () => {
  for (const st of [null, undefined, "x", 3, [], {}, { current: "spherex_qr9", releases: OK.releases }, { current_label: "  " }])
    assert.equal(R.render(st), "", JSON.stringify(st));
});

test("text from the file is escaped", () => {
  const html = R.render({ ...NEW, current_label: "<img src=x onerror=alert(1)>", new_releases: [{ label: "SPHEREx <b>QR</b>" }] });
  assert.doesNotMatch(html, /<img|<b>/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

// ---------------------------------------------------------------- loading, quietly

test("missing file (404): nothing shown, nothing logged", async () => {
  const { el, doc } = fakeDoc();
  const res = await silently(() => R.init(doc, async () => ({ ok: false, status: 404, json: async () => { throw new SyntaxError("Unexpected token '<'"); } })));
  assert.equal(res.value, false);
  assert.equal(el.hidden, true);
  assert.equal(el.innerHTML, "");
  assert.deepEqual(res.calls, []);
});

test("broken JSON, wrong shapes, no network, no fetch: null, never a rejection or a log", async () => {
  const cases = [
    answer(() => { throw new SyntaxError("Unexpected end of JSON input"); }),
    answer([]), answer("text"), answer(null),
    async () => { throw new TypeError("Failed to fetch"); },
    () => { throw new Error("fetch blew up synchronously"); },
    async () => null,
    undefined,
  ];
  for (const f of cases) {
    const res = await silently(() => R.load(f));
    assert.equal(res.value, null);
    assert.deepEqual(res.calls, []);
  }
});

test("load asks for the file without a stale cache", async () => {
  let seen;
  await R.load(async (url, init) => { seen = [url, init]; return { ok: true, json: async () => OK }; });
  assert.deepEqual(seen, ["data/spherex_release.json", { cache: "no-cache" }]);
});

test("init fills the element, unhides it and sets a title", async () => {
  const { el, doc } = fakeDoc();
  assert.equal(await R.init(doc, answer(NEW)), true);
  assert.equal(el.hidden, false);
  assert.match(el.innerHTML, /Quick Release 4/);
  assert.match(el.attrs.title, /SPHEREx data status/);
  assert.equal(el.classList.contains("spx-has-new"), true);
});

test("init without the element or a document does nothing", async () => {
  assert.equal(await R.init({ getElementById: () => null }, answer(OK)), false);
  assert.equal(await R.init(null, answer(OK)), false);
});

test("a file that renders nothing keeps the element hidden", () => {
  const { el } = fakeDoc();
  el.hidden = false;
  assert.equal(R.apply(el, { error: "only an error" }), false);
  assert.equal(el.hidden, true);
});

// ---------------------------------------------------------------- the two pages

for (const page of ["index.html", "observatory.html"]) {
  test(`${page}: loads release.js with a ?v= version and has a hidden placeholder`, () => {
    const html = fs.readFileSync(path.join(APP, page), "utf8");
    assert.match(html, /<script src="release\.js\?v=\w+"><\/script>/);
    assert.match(html, /<p class="spx-status" id="spherexStatus" hidden><\/p>/);
    assert.equal((html.match(/id="spherexStatus"/g) || []).length, 1);
  });

  test(`${page}: shows the line from the status file, with no errors`, async (t) => {
    const p = openPage(page, "", { files: { "data/spherex_release.json": NEW } });
    t.after(p.close);
    await p.settle(150);
    assert.deepEqual(p.errors, []);
    const el = p.$("spherexStatus");
    assert.equal(el.hidden, false);
    assert.equal(text(el.innerHTML), "SPHEREx Quick Release 3 · data through Oct 2026 · last synced 15 Nov 2026 · checked 15 Nov 2026" +
      "New data available at IRSA: Quick Release 4 is not yet in 2 of 11 targets.");
    assert.ok(p.fetched.some((u) => u.startsWith("data/spherex_release.json")));
  });

  test(`${page}: a broken status file shows nothing and breaks nothing`, async (t) => {
    const p = openPage(page, "", { files: { "data/spherex_release.json": [1, 2] } });
    t.after(p.close);
    await p.settle(150);
    assert.deepEqual(p.errors, []);
    assert.equal(p.$("spherexStatus").hidden, true);
  });
}

test("the observatory line sits with the frame details, the home line with the data sources", () => {
  const obs = fs.readFileSync(path.join(APP, "observatory.html"), "utf8"), home = fs.readFileSync(path.join(APP, "index.html"), "utf8");
  const i = obs.indexOf('id="spherexStatus"');
  assert.ok(i > obs.indexOf('id="metaBox"') && i < obs.indexOf('id="aladinLink"'));
  const j = home.indexOf('id="spherexStatus"');
  assert.ok(j > home.indexOf('<dl class="sources">') && j < home.indexOf("Honest limits"));
});

test("the committed status file renders", { skip: !fs.existsSync(REAL) && "no status file" }, () => {
  const st = JSON.parse(fs.readFileSync(REAL, "utf8"));
  const line = text(R.render(st));
  assert.ok(line.startsWith(st.current_label), line);
  if (st.data_through) assert.match(line, new RegExp(`data through ${R.fmtMonth(st.data_through)}`));
  if (st.checked) assert.match(line, /checked \d{1,2} \w{3} \d{4}/);
  else assert.match(line, /IRSA release check failed/);
  assert.equal(R.describe(st).note !== null, st.new_release_available === true);
});

// ---------------------------------------------------------------- style

test("CSS: theme colours only, reduced motion respected, wraps at phone width", () => {
  const brand = fs.readFileSync(path.join(APP, "brand.css"), "utf8");
  const block = fs.readFileSync(path.join(APP, "release.css"), "utf8");
  assert.ok(block.startsWith("/* ---------- SPHEREx data status line"));
  assert.doesNotMatch(brand, /spx-status/, "kept out of the unversioned brand.css (browsers cache it)");
  const css = brand + "\n" + block, start = brand.length + 1;
  for (const page of ["index.html", "observatory.html"]) {
    const html = fs.readFileSync(path.join(APP, page), "utf8");
    assert.match(html, /<link rel="stylesheet" href="brand\.css">\n<link rel="stylesheet" href="release\.css\?v=\d{8}[a-z]">/, page);
  }
  assert.doesNotMatch(block.replace(/\/\*[\s\S]*?\*\//g, ""), /#[0-9a-f]{3,8}\b|rgba?\(/i, "colours come from the theme variables");
  for (const v of ["--surface-2", "--muted", "--text", "--known", "--cand", "--warn", "--line"]) {
    assert.match(block, new RegExp(`var\\(${v}\\)`));
    assert.match(css.slice(0, start), new RegExp(`:root \\{[\\s\\S]*${v}:`), `${v} defined for the light theme`);
  }
  for (const v of ["--surface-2", "--muted", "--text", "--known", "--cand", "--warn", "--line"]) {
    assert.match(css, new RegExp(`:root\\[data-theme="dark"\\] \\{[^}]*${v}:`), `${v} in the Night theme`);
    assert.match(css, new RegExp(`@media \\(prefers-color-scheme: dark\\) \\{\\s*:root:not\\(\\[data-theme\\]\\) \\{[^}]*${v}:`), `${v} in the OS dark mode`);
  }
  assert.match(block, /@media \(prefers-reduced-motion: no-preference\) \{ \.spx-status:not\(\[hidden\]\) \{ animation/);
  assert.match(block, /flex-wrap: wrap/);
  assert.match(block, /max-width: 100%/);
  assert.match(block, /@media \(max-width: 420px\) \{ \.spx-status \.spx-part \{ white-space: normal; \} \}/);
  assert.match(block, /\.spx-status\[hidden\] \{ display: none; \}/);
});
