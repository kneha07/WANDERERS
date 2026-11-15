// A small stand-in for the browser, enough to run the Observatory's scripts in Node with no packages.
// Elements come from the page's own HTML (id, tag, value, checked, <option>s); innerHTML is kept as a string.
// fetch() reads files from app/ (optionally slowed down per URL), images "load" on the next tick.
// Not a test file itself (no test() calls); used by observatory.test.js and home.test.js.
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const APP = path.join(__dirname, "..", "app");

function el(doc, tag, id) {
  const listeners = {}, classes = new Set();
  const e = {
    tagName: tag.toUpperCase(), id: id || "", children: [], attrs: {}, dataset: {}, style: {}, hidden: false, disabled: false,
    checked: false, textContent: "", value: "", className: "", options: [], width: 600, height: 600, clientWidth: 0, _html: "",
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); this.children = []; },
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); return want; } },
    setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); }, removeEventListener() {},
    dispatchEvent(ev) {
      ev.target = ev.target || e; ev.defaultPrevented = ev.defaultPrevented || false;
      ev.preventDefault = ev.preventDefault || (() => { ev.defaultPrevented = true; });
      if (typeof e["on" + ev.type] === "function") e["on" + ev.type](ev);
      for (const f of listeners[ev.type] || []) f(ev);
      if (ev.bubbles && e.parentElement) e.parentElement.dispatchEvent(ev);
      return !ev.defaultPrevented;
    },
    click() { e.dispatchEvent({ type: "click", bubbles: true }); },
    requestSubmit() { e.dispatchEvent({ type: "submit" }); },
    querySelectorAll(sel) {   // tag names only, over appended children (innerHTML is not parsed)
      const tagName = String(sel).trim().split(/[\s.#[:]/)[0].toUpperCase(), out = [];
      const walk = (n) => n.children.forEach((c) => { if (!tagName || c.tagName === tagName) out.push(c); walk(c); });
      walk(e); return out;
    },
    querySelector(sel) { return e.querySelectorAll(sel)[0] || null; },
    appendChild(c) { e.children.push(c); c.parentElement = e; return c; },
    insertAdjacentHTML(_, html) { e._html += html; }, remove() {}, focus() { doc.activeElement = e; }, blur() {},
    closest(sel) {   // supports a comma list of tag names
      const tags = String(sel).split(",").map((s) => s.trim().toUpperCase());
      for (let n = e; n; n = n.parentElement) if (tags.includes(n.tagName)) return n;
      return null;
    },
    contains: (n) => { for (; n; n = n.parentElement) if (n === e) return true; return false; },
    getContext: () => e._ctx || (e._ctx = canvasContext(doc)),
    getBoundingClientRect: () => ({ width: 900, height: 300, left: 0, top: 0 }),
    setPointerCapture() {},
  };
  e._classes = classes;
  return e;
}

// 2D context that accepts every call and remembers non-finite numbers (NaN in a drawing = a bug)
function canvasContext(doc) {
  return new Proxy({}, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === "getImageData" || k === "createImageData") return (...a) => { const [w, h] = k === "getImageData" ? [a[2], a[3]] : a; return { data: new Uint8ClampedArray(w * h * 4), width: w, height: h }; };
      if (k === "measureText") return (s) => ({ width: String(s).length * 6 });
      return (...args) => { if (args.some((a) => typeof a === "number" && !Number.isFinite(a))) doc.badDraws.push(String(k)); };
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}

// Every element with an id in the page, with its starting value / checked state / <option>s.
function elementsOf(doc, html) {
  const els = {};
  const re = /<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g;
  let m;
  while ((m = re.exec(html))) {
    const [, tag, attrs, id] = m, x = el(doc, tag, id);
    const a = (k) => { const r = new RegExp(`\\b${k}="([^"]*)"`).exec(attrs); return r ? r[1] : null; };
    for (const k of ["value", "min", "max", "step"]) if (a(k) !== null) x[k] = a(k);
    x.checked = /\bchecked\b/.test(attrs); x.hidden = /\bhidden\b/.test(attrs);
    if (tag === "select") {
      const body = html.slice(re.lastIndex, html.indexOf("</select>", re.lastIndex));
      x.options = [...body.matchAll(/<option value="([^"]*)"([^>]*)>/g)].map((o) => ({ value: o[1], selected: /selected/.test(o[2]) }));
      x.value = (x.options.find((o) => o.selected) || x.options[0] || { value: "" }).value;
    }
    if (/\bdata-aspect="([^"]+)"/.test(attrs)) x.dataset.aspect = /\bdata-aspect="([^"]+)"/.exec(attrs)[1];
    els[id] = x;
  }
  return els;
}

class FakeLocation {
  constructor(href) { this.u = new URL(href); }
  get href() { return this.u.href; } get search() { return this.u.search; } get hash() { return this.u.hash; }
  get pathname() { return this.u.pathname; } get origin() { return this.u.origin; }
  toString() { return this.u.href; }
}

/* open("observatory.html", "?target=barnard", { delays: { "r_dra/target.json": 300 }, scripts: [...] })
 * delays: substring of a fetched/loaded URL -> milliseconds, or a function (url, nth call) -> milliseconds. */
function openPage(page, query = "", opts = {}) {
  const html = fs.readFileSync(path.join(APP, page), "utf8");
  const doc = { badDraws: [], activeElement: null };
  const els = elementsOf(doc, html), listeners = {}, winListeners = {};
  const body = el(doc, "body"), docEl = el(doc, "html");
  Object.values(els).forEach((x) => { if (!x.parentElement) x.parentElement = body; });
  Object.assign(doc, {
    body, documentElement: docEl,
    getElementById: (id) => els[id] || null,
    querySelector: () => null, querySelectorAll: () => [],
    createElement: (t) => el(doc, t),
    addEventListener: (t, f) => (listeners[t] = listeners[t] || []).push(f),
    dispatchEvent: (ev) => { (listeners[ev.type] || []).forEach((f) => f(ev)); return true; },
  });
  const fetched = [], errors = [];
  const delayFor = (url) => {
    const d = opts.delays || {};
    for (const [k, v] of Object.entries(d)) if (url.includes(k)) return typeof v === "function" ? v(url, fetched.filter((f) => f.includes(k)).length) : v;
    return 0;
  };
  const location = new FakeLocation("http://localhost/" + page + query);
  const fileOf = (url) => path.join(APP, decodeURIComponent(new URL(url, location.href).pathname));
  const win = {
    document: doc, location, console, URL, URLSearchParams, Promise, Math, JSON, Date, Number, String, Array, Object, Set, Map,
    Float32Array, Float64Array, Uint8Array, Uint8ClampedArray, Error, TypeError, RangeError, SyntaxError, Symbol, Proxy, Reflect, isFinite, isNaN,
    setTimeout, clearTimeout, setInterval, clearInterval, performance,
    devicePixelRatio: 1, navigator: { clipboard: { writeText: async () => {} } }, prompt: () => null,
    history: { replaceState: (s, t, u) => { location.u = new URL(String(u), location.href); }, pushState: () => {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    requestAnimationFrame: (f) => setTimeout(() => f(performance.now()), 16), cancelAnimationFrame: (id) => clearTimeout(id),
    addEventListener: (t, f) => (winListeners[t] = winListeners[t] || []).push(f), removeEventListener() {},
    CustomEvent: class { constructor(type, o) { this.type = type; this.detail = o && o.detail; } },
    ImageData: class { constructor(d, w, h) { this.data = d; this.width = w; this.height = h; } },
    Image: class {
      constructor() { this.width = 150; this.height = 150; }
      set src(v) { this._src = v; fetched.push(v); setTimeout(() => (fs.existsSync(fileOf(v)) ? this.onload : this.onerror)?.(), delayFor(v)); }
      get src() { return this._src; }
    },
    fetch: (url, init) => {
      url = String(url); fetched.push(url);
      const wait = delayFor(url);
      return new Promise((resolve, reject) => setTimeout(() => {
        const u = new URL(url, location.href);
        if (u.pathname.startsWith("/api/")) {
          const r = opts.api && opts.api(u, init);
          return r ? resolve(r) : resolve({ ok: false, status: 404, json: async () => ({ error: "not found" }), text: async () => "not found" });
        }
        if (u.origin !== location.origin) return reject(new TypeError("Failed to fetch"));
        const f = fileOf(url);
        if (!fs.existsSync(f) || fs.statSync(f).isDirectory())
          return resolve({ ok: false, status: 404, json: async () => { throw new SyntaxError("Unexpected token '<'"); }, text: async () => "not found" });
        const text = fs.readFileSync(f, "utf8");
        resolve({ ok: true, status: 200, json: async () => JSON.parse(text), text: async () => text });
      }, wait));
    },
  };
  win.window = win; win.globalThis = win; win.self = win;
  const ctx = vm.createContext(win);
  const onRejection = (e) => errors.push(e);
  process.on("unhandledRejection", onRejection);
  const scripts = opts.scripts || [...html.matchAll(/<script src="([^"?]+)/g)].map((s) => s[1]).filter((s) => !opts.skip || !opts.skip.includes(s));
  for (const s of scripts) {
    try { vm.runInContext(fs.readFileSync(path.join(APP, s), "utf8"), ctx, { filename: s }); }
    catch (e) { errors.push(e); }
  }
  return {
    window: win, document: doc, $: (id) => els[id] || null, errors, fetched,
    key: (target, key, extra = {}) => { const ev = { type: "keydown", key, bubbles: true, target, ...extra }; (target || body).dispatchEvent(ev); doc.dispatchEvent(ev); return ev; },
    fire: (target, type) => target.dispatchEvent({ type, bubbles: true, target }),
    settle: (ms = 50) => new Promise((r) => setTimeout(r, ms)),
    close: () => process.off("unhandledRejection", onRejection),
  };
}

module.exports = { openPage, APP };
