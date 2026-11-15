// Sky Compass page logic (app/compass.js) run in Node against a tiny fake DOM, with the real orient.js and sky.js.
// node --test test/compass-flows.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = path.join(__dirname, "..", "app");
const Orient = require("../app/orient.js");
const Sky = require("../app/sky.js");
const HIDDEN = new Set([...fs.readFileSync(path.join(APP, "compass.html"), "utf8").matchAll(/<[^>]*\bid="([^"]+)"[^>]*\shidden[\s>]/g)].map((m) => m[1]));

// ---- a fake browser: just enough DOM for compass.js ----
function fakeElement(id) {
  const listeners = {}, classes = new Set();
  return {
    id, hidden: HIDDEN.has(id), textContent: "", innerHTML: "", value: "", checked: false, disabled: false, className: "",
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
  const els = {}, timers = [], windowListeners = {}, rafs = [];
  let clock = 0;
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
  if (webb === "real") {                          // app/telescope.js on the given data/webb.json
    const w = {}; new Function("window", "fetch", fs.readFileSync(path.join(APP, "telescope.js"), "utf8"))(w, fetchFile); webb = w.Webb;
  }
  const introMod = { playIntro: async (o) => { await null; o.onDone({ lat: 47.61, lon: -122.33 }); }, earthFacts: () => ({ distanceAU: 1, speedKms: 30 }) };
  const importIntro = () => (intro === "ok" ? Promise.resolve(introMod) : Promise.reject(new Error("CDN unreachable")));
  const StarSearch = { attach() {}, load: () => Promise.resolve([]), search: () => [], hms: (d) => `${d}h`, dms: (d) => `${d}d`, describe: () => [] };
  const navigator = { geolocation, vibrate: () => true, mediaDevices: { getUserMedia: () => Promise.reject(new Error("no camera")) } };
  const env = {
    window, document, location: loc, history: { replaceState(_, __, u) { loc.href = String(u); } }, navigator, fetch: fetchFile,
    Orient, Sky: SkyLocal, StarSearch, Webb: webb || { load: () => new Promise(() => {}), near: () => [] }, PathView: undefined,
    getComputedStyle: () => ({ paddingTop: "0" }), requestAnimationFrame: (fn) => rafs.push(fn), performance: { now: () => (clock += 300) },
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
  const frame = () => { for (const fn of rafs.splice(0)) fn(); };   // draw one animation frame
  return { $, els, dirs, body, window, windowListeners, timers, runTimers, flush, frame, ...window.__wanderers, location: loc };
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

test("a phone with only the absolute (compass) orientation stream gets motion control, not drag mode", async () => {
  const c = loadCompass({ intro: "fail" });
  await c.$("go").onclick();
  // Chrome on a phone without a gyroscope: deviceorientation carries nulls, deviceorientationabsolute has the angles
  for (const fn of c.windowListeners.deviceorientation) fn({ alpha: null, beta: null, gamma: null, absolute: false });
  for (let i = 0; i < 5; i++) for (const fn of c.windowListeners.deviceorientationabsolute) fn({ alpha: 30, beta: 60, gamma: 0 });
  assert.equal(c.S.sensors, true);
  const p = c.F.pointing();
  assert.ok(p && Math.abs(Orient.wrap180(p.az - 330)) < 1, `camera direction from the absolute stream, got ${p && p.az}`);
  c.runTimers(300);
  assert.equal(c.$("calib").hidden, false, "calibration offered instead of drag mode");
  assert.doesNotMatch(c.$("guideSub").textContent, /No motion sensors/);
});

test("a sight check rejected for a tilt mismatch leaves the compass in charge", () => {
  const c = loadCompass({ intro: "fail" });
  aimPhone(c, 100, 10);
  assert.ok(!c.F.compassFrozen);
  c.$("lmCoords").value = "47.6205, -122.3493";
  c.$("lmUse").click();                          // enter aim mode, then aim "at Vega 70 deg up" while pointing 10 deg up
  c.S.aim = { label: "Vega", az: 100, alt: 70 };
  c.$("aimGo").click();
  assert.match(c.$("aimMsg").textContent, /higher or lower than Vega/);
  assert.equal(c.F.fineAz, 0);
  assert.equal(c.F.fineAlt, 0);
  assert.ok(!c.F.compassFrozen, "a rejected sight check must not freeze the compass");
  assert.equal(c.$("aimBar").hidden, false, "still aiming, so the user can try again or cancel");
});

test("after a sight check, tapping Done and aiming again right away still offers Cancel", () => {
  const c = loadCompass({ intro: "fail" });
  aimPhone(c, 100, 10);
  const [north, east] = c.dirs;
  north.click();                                   // "This is North" -> aim mode
  c.$("aimGo").click();                            // Calibrate succeeds
  assert.equal(c.$("aimGo").textContent, "Done");
  assert.equal(c.$("aimCancel").hidden, true);
  c.$("aimGo").click();                            // Done, before the 4 s auto-close
  assert.equal(c.$("aimBar").hidden, true);
  east.click();                                    // a new aim within 4 s
  assert.equal(c.$("aimBar").hidden, false);
  assert.equal(c.$("aimGo").textContent, "Calibrate");
  assert.equal(c.$("aimCancel").hidden, false, "Cancel must be offered on the new aim");
  c.runTimers();                                   // the first aim's auto-close must not end the new aim
  assert.equal(c.$("aimBar").hidden, false);
  c.$("aimCancel").click();
  assert.equal(c.$("aimBar").hidden, true);
  assert.equal(c.body.classList.contains("aiming"), false);
});

test("a successful sight check closes itself after 4 s and restores Cancel", () => {
  const c = loadCompass({ intro: "fail" });
  aimPhone(c, 100, 10);
  c.dirs[0].click();
  c.$("aimGo").click();
  c.runTimers();
  assert.equal(c.$("aimBar").hidden, true);
  assert.equal(c.$("aimCancel").hidden, false);
  assert.equal(c.F.compassFrozen, true);
});

// where the crosshair is (J2000) when looking at az/alt in drag mode: one frame of the real page
async function crosshairAt(az, alt, opts = {}) {
  const c = loadCompass({ intro: "fail", ...opts });
  await c.$("go").onclick();
  c.S.manual = { az, alt };
  c.frame(); await c.flush(); await c.flush(); c.frame();
  return c;
}

test("the 'Webb looked here' chip keeps its frame in a crowded field until you move 4.5 deg away", async () => {
  const a = (await crosshairAt(200, 40)).S.crosshair, b = (await crosshairAt(200, 40.8)).S.crosshair;
  // frame A where the crosshair starts; 100 frames crowded 0.8 deg away (like COSMOS: 500+ frames within 4.5 deg)
  const row = (ra, dec, obs, target) => [ra, dec, 0.05, "NIRCam", target, "1234", 60000, "F200W", obs,
    [ra - 0.03, dec - 0.03, ra + 0.03, dec - 0.03, ra + 0.03, dec + 0.03, ra - 0.03, dec + 0.03], 0, 0];
  const rows = [row(a.ra, a.dec, "A", "Frame A")];
  for (let i = 0; i < 100; i++) rows.push(row(b.ra + (i % 10) * 0.004, b.dec + Math.floor(i / 10) * 0.004, `B${i}`, `Crowd ${i}`));
  rows.sort((x, y) => x[0] - y[0]);
  const files = { "data/webb.json": { updated: "test", count: rows.length, programs: {}, p: rows } };
  const c = await crosshairAt(200, 40, { webb: "real", files });
  c.frame();
  assert.equal(c.S.webbHere && c.S.webbHere.obs, "A", "chip starts on the frame under the crosshair");
  c.S.manual = { az: 200, alt: 40.8 };            // move 0.8 deg: still well inside 4.5 deg of A
  c.frame();
  assert.equal(c.S.webbHere.obs, "A", "the chip must not change under your finger");
  assert.match(c.$("webbChip").innerHTML, /Frame A/);
  c.S.manual = { az: 200, alt: 46 };              // 6 deg away: now it may let go
  c.frame();
  assert.notEqual(c.S.webbHere && c.S.webbHere.obs, "A");
});
