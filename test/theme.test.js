// Day / Night Observatory theme: the same rules and storage key on every redesigned page.
// Live Explore (web/) is the team's own console design in this version and is not yet part of the shared theme.
// node --test test/theme.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const PAGES = ["app/index.html", "app/observatory.html", "app/compass.html", "app/survey.html"];
const KEY = "wanderers-theme";

// ---- a tiny fake browser, just enough for the theme scripts ----
function fakeBrowser({ saved = null, osDark = false, storageThrows = false, buttons = 1 } = {}) {
  const store = new Map(saved ? [[KEY, saved]] : []);
  const localStorage = {
    getItem: (k) => { if (storageThrows) throw new Error("blocked"); return store.has(k) ? store.get(k) : null; },
    setItem: (k, v) => { if (storageThrows) throw new Error("blocked"); store.set(k, String(v)); },
  };
  const classes = new Set();
  const root = { dataset: {}, classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) } };
  const mkButton = () => {
    const attrs = {}, handlers = {};
    return { attrs, setAttribute: (k, v) => (attrs[k] = String(v)), addEventListener: (e, f) => (handlers[e] = f), click: () => handlers.click() };
  };
  const toggles = Array.from({ length: buttons }, mkButton);
  const meta = { content: "" };
  const events = [];
  const document = {
    documentElement: root,
    querySelectorAll: (s) => (s === ".theme-toggle" ? toggles : []),
    querySelector: (s) => (s === 'meta[name="theme-color"]' ? meta : null),
    dispatchEvent: (e) => events.push(e.detail),
  };
  const matchMedia = (q) => ({ matches: q.includes("dark") ? osDark : false, addEventListener: () => {} });
  const ctx = { document, localStorage, matchMedia, setTimeout: () => 0, CustomEvent: class { constructor(n, o) { this.detail = o.detail; } } };
  ctx.window = ctx;
  vm.createContext(ctx);
  return { ctx, root, store, toggles, meta, events };
}

// the inline <head> script that sets the theme before first paint
function bootstrapOf(html) {
  const s = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((js) => js.includes(KEY));
  assert.ok(s, "page has an inline theme bootstrap");
  return s;
}

test("every page sets the theme before first paint with the shared key", () => {
  for (const p of PAGES) {
    const html = read(p), js = bootstrapOf(html);
    assert.ok(html.indexOf(js) < html.indexOf("<body"), `${p}: bootstrap runs in <head>`);
    assert.match(html, /<meta name="theme-color"/, `${p}: theme-color meta`);
  }
});

test("bootstrap: saved choice wins, else the operating system, and blocked storage still works", () => {
  for (const p of PAGES) {
    const js = bootstrapOf(read(p)).replace(/location\.replace\([^)]*\)/, "0"); // index.html also redirects old links
    const cases = [
      [{ saved: "dark", osDark: false }, "dark"],
      [{ saved: "light", osDark: true }, "light"],
      [{ osDark: true }, "dark"],
      [{ osDark: false }, "light"],
      [{ saved: "purple", osDark: true }, "dark"],
      [{ storageThrows: true, osDark: true }, "dark"],
    ];
    for (const [opts, want] of cases) {
      const b = fakeBrowser(opts);
      b.ctx.location = { search: "", hash: "", replace: () => {} };
      vm.runInContext(js, b.ctx);
      assert.equal(b.root.dataset.theme, want, `${p} ${JSON.stringify(opts)}`);
    }
  }
});

test("app/theme.js: toggle flips the theme, saves it and updates labels", () => {
  const src = read("app/theme.js");
  const b = fakeBrowser({ osDark: false, buttons: 2 });
  b.root.dataset.theme = "light";
  vm.runInContext(src, b.ctx);
  assert.equal(b.toggles[0].attrs["aria-label"], "Switch to Night Observatory (dark theme)");
  assert.equal(b.toggles[0].attrs["aria-pressed"], "false");
  b.toggles[0].click();
  assert.equal(b.root.dataset.theme, "dark");
  assert.equal(b.store.get(KEY), "dark");
  assert.equal(b.meta.content, "#0B1422");
  for (const t of b.toggles) assert.equal(t.attrs["aria-pressed"], "true");   // every toggle on the page agrees
  assert.equal(b.events.at(-1), "dark");
  b.toggles[1].click();
  assert.equal(b.root.dataset.theme, "light");
  assert.equal(b.store.get(KEY), "light");
});

test("app/theme.js: switching still works when storage is blocked", () => {
  const b = fakeBrowser({ storageThrows: true });
  b.root.dataset.theme = "light";
  vm.runInContext(read("app/theme.js"), b.ctx);
  b.toggles[0].click();
  assert.equal(b.root.dataset.theme, "dark");
});

test("every page uses the shared brand stylesheet, logo and a theme toggle", () => {
  for (const p of ["app/index.html", "app/observatory.html", "app/compass.html"]) {
    const html = read(p);
    assert.match(html, /href="brand\.css"/, p);
    assert.match(html, /class="theme-toggle"/, p);
    assert.match(html, /<script src="theme\.js"><\/script>/, p);
    assert.match(html, /href="favicon\.svg"/, p);
  }
});

test("Sky Compass keeps every element its script uses", () => {
  const html = read("app/compass.html"), js = read("app/compass.js");
  const ids = [...new Set([...js.matchAll(/\$\("([A-Za-z0-9_]+)"\)/g)].map((m) => m[1]))];
  assert.ok(ids.length > 20);
  for (const id of ids) assert.match(html, new RegExp(`id="${id}"`), `#${id}`);
});

test("Observatory keeps every element its scripts use", () => {
  const html = read("app/observatory.html");
  const js = ["app.js", "stars.js"].map((f) => read(`app/${f}`)).join("\n");
  const ids = [...new Set([...js.matchAll(/\$\("([A-Za-z0-9_]+)"\)/g)].map((m) => m[1]))];
  const made = new Set([...js.matchAll(/id="([A-Za-z0-9_]+)"/g)].map((m) => m[1]));   // created by the scripts themselves
  for (const id of ids) if (!made.has(id)) assert.match(html, new RegExp(`id="${id}"`), `#${id}`);
});

test("old share links on the home page open the Observatory with the same query", () => {
  const js = bootstrapOf(read("app/index.html"));   // the same inline script holds the redirect
  for (const [q, want] of [["?target=wise0855&ch=w2", "observatory.html?target=wise0855&ch=w2"], ["?star=hip87937", "observatory.html?star=hip87937"], ["", null], ["?utm=x", null]]) {
    let went = null;
    const b = fakeBrowser();
    b.ctx.location = { search: q, hash: "", replace: (u) => (went = u) };
    vm.runInContext(js, b.ctx);
    assert.equal(went, want, q || "(no query)");
  }
});

test("the Orbit Epochs logo is identical on every redesigned page", () => {
  const norm = (s) => s.replace(/className=/g, "class=").replace(/strokeWidth=/g, "stroke-width=").replace(/\s*\/>\s*/g, "/>").replace(/\s+/g, " ").trim();
  const grab = (src) => [...src.matchAll(/<svg viewBox="2 2 36 36" aria-hidden="true">([\s\S]*?)<\/svg>/g)].map((m) => norm(m[1]));
  const ref = grab(read("app/index.html"));
  assert.equal(ref.length, 2, "header + footer on the home page");
  assert.equal(ref[0], ref[1]);
  for (const p of ["app/observatory.html", "app/compass.html"]) {
    const got = grab(read(p));
    assert.ok(got.length >= 1, `${p} has the logo`);
    for (const g of got) assert.equal(g, ref[0], p);
  }
  for (const part of ['class="ink"', 'class="acc"', 'class="ring"', 'class="dot"', 'class="ink-dot"']) assert.ok(ref[0].includes(part), part);
  assert.doesNotMatch(read("app/brand.css"), /Space Grotesk/);
});

test("logo files: every variant exists for both themes and shares the emblem's viewBox", () => {
  for (const t of ["light", "dark"]) for (const k of ["symbol", "logo-horizontal", "logo-compact"]) {
    const s = read(`app/brand/${k}-${t}.svg`);
    assert.match(s, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/, `${k}-${t}`);
    assert.match(s, /aria-label="WANDERERS"/);
    if (k !== "symbol") assert.match(s, /font-family="Sora/);
  }
  assert.match(read("app/brand/symbol-light.svg"), /viewBox="2 2 36 36"/);
  assert.match(read("app/favicon.svg"), /prefers-color-scheme:dark/);
});
