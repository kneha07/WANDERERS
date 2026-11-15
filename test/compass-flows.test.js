// Sky Compass page logic (app/compass.js) run in Node against a tiny fake DOM, with the real orient.js and sky.js.
// node --test test/compass-flows.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = path.join(__dirname, "..", "app");
const Orient = require("../app/orient.js");
const Sky = require("../app/sky.js");

// ---- a fake browser: just enough DOM for compass.js ----
function fakeElement(id) {
  const listeners = {}, classes = new Set();
  return {
    id, hidden: false, textContent: "", innerHTML: "", value: "", checked: false, disabled: false, className: "",
    dataset: {}, style: {}, width: 240, height: 240, videoWidth: 0, listeners,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c), toggle: (c, on) => (on ?? !classes.has(c)) ? classes.add(c) : classes.delete(c) },
    addEventListener: (type, fn) => (listeners[type] = listeners[type] || []).push(fn),
    dispatch(type, ev = {}) { for (const fn of listeners[type] || []) fn({ target: this, preventDefault() {}, ...ev }); },
    click() { if (this.onclick) return this.onclick({ target: this }); },
    querySelectorAll: () => [], querySelector: () => null, setAttribute() {}, removeAttribute() {}, focus() {}, blur() {},
    setPointerCapture() {}, play: () => Promise.resolve(), remove() {}, appendChild() {},
    getContext: () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => ({ addColorStop() {} })), set: (t, k, v) => ((t[k] = v), true) }),
  };
}

function loadCompass({ search = "", intro = "ok", geolocation = null, webb = null, files = {} } = {}) {
  const els = {}, timers = [], windowListeners = {};
  const $ = (id) => els[id] || (els[id] = fakeElement(id));
  const dirs = [0, 90, 180, 270].map((az) => Object.assign(fakeElement(), { dataset: { az: String(az) } }));
  const body = fakeElement("body");
  const document = {
    getElementById: $, body,
    querySelectorAll: (sel) => (sel === ".dirs button" ? dirs : []),
    createElement: () => fakeElement(), addEventListener() {},
  };
  const loc = new URL("https://wanderers.test/compass.html" + search);
  const window = {
    devicePixelRatio: 1, innerWidth: 390, innerHeight: 844,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener: (type, fn) => (windowListeners[type] = windowListeners[type] || []).push(fn),
  };
  const fetchFile = async (u) => {
    const rel = String(u).split("?")[0];
    if (rel in files) return { ok: true, json: async () => files[rel] };
    const p = path.join(APP, rel);
    if (!fs.existsSync(p)) return { ok: false, json: async () => { throw new Error("404 " + rel); } };
    return { ok: true, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) };
  };
  const SkyLocal = { ...Sky, loadDeclination: () => Promise.resolve(null) };
  const introMod = { playIntro: async (o) => { await null; o.onDone({ lat: 47.61, lon: -122.33 }); }, earthFacts: () => ({ distanceAU: 1, speedKms: 30 }) };
  const importIntro = () => (intro === "ok" ? Promise.resolve(introMod) : Promise.reject(new Error("CDN unreachable")));
  const StarSearch = { attach() {}, load: () => Promise.resolve([]), search: () => [], hms: (d) => `${d}h`, dms: (d) => `${d}d`, describe: () => [] };
  const navigator = { geolocation, vibrate: () => true, mediaDevices: { getUserMedia: () => Promise.reject(new Error("no camera")) } };
  const env = {
    window, document, location: loc, history: { replaceState(_, __, u) { loc.href = String(u); } }, navigator, fetch: fetchFile,
    Orient, Sky: SkyLocal, StarSearch, Webb: webb || { load: () => new Promise(() => {}), near: () => [] }, PathView: undefined,
    getComputedStyle: () => ({ paddingTop: "0" }), requestAnimationFrame: () => 0, performance: { now: () => 0 },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout: (h) => { if (timers[h - 1]) timers[h - 1].fn = null; },
    DeviceOrientationEvent: undefined, innerWidth: 390, innerHeight: 844, console: { warn() {}, log() {} },
  };
  Object.assign(window, env);
  let src = fs.readFileSync(path.join(APP, "compass.js"), "utf8");
  // a static import that fails takes the whole module down; a dynamic one is stubbed
  src = src.replace(/^import \{ playIntro, earthFacts \} from "[^"]+";$/m, intro === "ok" ? "const { playIntro, earthFacts } = __introMod;" : "throw new Error('CDN unreachable');")
    .replace(/import\("\.\/intro\.js[^"]*"\)/, "__importIntro()");
  const names = Object.keys(env);
  new Function(...names, "__introMod", "__importIntro", `"use strict";\n${src}`)(...names.map((k) => env[k]), introMod, importIntro);
  const runTimers = (maxMs = Infinity) => { for (const t of timers.splice(0)) if (t.fn && t.ms <= maxMs) t.fn(); };
  const flush = () => new Promise((r) => setImmediate(r));
  return { $, els, dirs, body, window, windowListeners, timers, runTimers, flush, ...window.__wanderers, location: loc };
}
// feed iPhone-style events: camera pointing at az/alt (compass heading = az, gyro frame offset 137 deg)
function aimPhone(c, az, alt, n = 60) {
  const D2R = Math.PI / 180, f = [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
  const k = Math.hypot(-f[2] * f[0], -f[2] * f[1], 1 - f[2] * f[2]), up = [-f[2] * f[0] / k, -f[2] * f[1] / k, (1 - f[2] * f[2]) / k];
  const x = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]];
  const e = Orient.eulerFromMat([[x[0], up[0], -f[0]], [x[1], up[1], -f[1]], [x[2], up[2], -f[2]]]);
  for (let i = 0; i < n; i++) c.F.feed({ alpha: Orient.wrap360(e.alpha + 137), beta: e.beta, gamma: e.gamma, webkitCompassHeading: az, t: (c.tick = (c.tick || 0) + 16) });
  c.S.sensors = true;
}


test("the page still starts when the three.js intro cannot be loaded (offline / CDN blocked)", async () => {
  const c = loadCompass({ intro: "fail" });
  await c.flush();
  await c.$("go").onclick();
  assert.equal(c.$("landing").hidden, true);
  assert.equal(c.$("cosmos").hidden, true, "intro screen closed");
  assert.equal(c.$("ar").hidden, false, "AR view shown");
  c.$("infoBtn").click();
  assert.match(c.$("infoRows").innerHTML, /Earth's orbit<\/dt><dd>not available/);
});

test("with the intro available it plays and then opens the AR view", async () => {
  const c = loadCompass({ intro: "ok" });
  await c.flush();
  await c.$("go").onclick();
  await c.flush();
  assert.equal(c.$("ar").hidden, false);
  c.$("infoBtn").click();
  assert.match(c.$("infoRows").innerHTML, /1\.0000 AU from the Sun/);
});
