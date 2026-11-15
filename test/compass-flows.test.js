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
    querySelectorAll(sel) {   // <button data-*> written through innerHTML come back as fake elements
      if (sel !== "button") return [];
      if (this._qsFor !== this.innerHTML) {
        this._qsFor = this.innerHTML;
        this._qs = [...this.innerHTML.matchAll(/<button([^>]*)>/g)].map((m) => Object.assign(fakeElement(),
          { dataset: Object.fromEntries([...m[1].matchAll(/data-([a-z]+)="([^"]*)"/g)].map((d) => [d[1], d[2]])) }));
      }
      return this._qs;
    },
    querySelector() { return this.querySelectorAll("button")[0] || null; },
    setAttribute() {}, removeAttribute() {}, focus() {}, blur() {},
    setPointerCapture() {}, play: () => Promise.resolve(), remove() {}, appendChild() {},
    texts: [],   // canvas fillText calls: [text, x, y]
    getContext() {
      const texts = this.texts, base = { fillText: (t, x, y) => texts.push([String(t), x, y]), measureText: (t) => ({ width: String(t).length * 7 }) };
      return new Proxy(base, { get: (t, k) => (k in t ? t[k] : () => ({ addColorStop() {} })), set: (t, k, v) => ((t[k] = v), true) });
    },
  };
}

function loadCompass({ search = "", intro = "ok", geolocation = null, webb = null, files = {}, timeZone = "America/Los_Angeles", pathView, time = null } = {}) {
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
  const picked = {};
  const StarSearch = { attach(input, list, onPick) { picked.onPick = onPick; }, load: () => Promise.resolve([]), search: () => [], hms: (d) => `${d}h`, dms: (d) => `${d}d`, describe: () => [] };
  const navigator = { geolocation, vibrate: () => true, mediaDevices: { getUserMedia: () => Promise.reject(new Error("no camera")) } };
  const env = {
    window, document, location: loc, history: { replaceState(_, __, u) { loc.href = String(u); } }, navigator, fetch: fetchFile,
    // realsky.js (the team's real-sky layer) draws extra sky detail; these flow tests only need it to be present
    RealSky: { R: { sky: "off" }, DEEP: { state: "off" }, init() {}, draw() {}, cancelGesture() {}, renderSaved() {}, projector: () => () => null },
    Orient, Sky: SkyLocal, StarSearch, Webb: webb || { load: () => new Promise(() => {}), near: () => [] }, PathView: pathView,
    getComputedStyle: () => ({ paddingTop: "0" }), requestAnimationFrame: (fn) => rafs.push(fn), performance: { now: () => (clock += 300) },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout: (h) => { if (timers[h - 1]) timers[h - 1].fn = null; },
    DeviceOrientationEvent: undefined, innerWidth: 390, innerHeight: 844, console: { warn() {}, log() {} },
    Intl: { DateTimeFormat: () => ({ resolvedOptions: () => ({ timeZone }) }) },
    // a clock the test moves (time.t, in ms) for checks over time; the real one otherwise
    Date: time ? class extends Date { constructor(...a) { super(...(a.length ? a : [time.t])); } static now() { return time.t; } } : Date,
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
  return { $, els, dirs, body, window, windowListeners, timers, runTimers, flush, frame, pickStar: (st) => picked.onPick(st), ...window.__wanderers, location: loc };
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
  assert.match(c.$("infoRows").innerHTML, /Earth's orbit<\/dt><dd>not (available|loaded)/);
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

test("a target picked by the URL (?target=) shows the About button, like picking it by hand", async () => {
  const c = loadCompass({ intro: "fail", search: "?target=barnard" });
  await c.flush(); await c.flush();
  assert.equal(c.S.sel && c.S.sel.id, "barnard");
  assert.equal(c.$("aboutBtn").hidden, false);
  const none = loadCompass({ intro: "fail", search: "?target=nope&star=Nope" });
  await none.flush(); await none.flush();
  assert.equal(none.S.sel, null);
  assert.equal(none.$("aboutBtn").hidden, true);
});

test("drag mode: a drag longer than a full turn keeps the heading in 0-360", async () => {
  const c = loadCompass({ intro: "fail" });
  const hud = c.$("hud");
  hud.dispatch("pointerdown", { clientX: 0, clientY: 400, pointerId: 1 });
  hud.dispatch("pointermove", { clientX: 8000, clientY: 400 });     // 8000 px * 70/844 deg = 663 deg to the left
  const az = c.S.manual.az;
  assert.ok(az >= 0 && az < 360, `az ${az}`);
  assert.ok(Math.abs(az - (((180 - 8000 * 70 / 844) % 360) + 360) % 360) < 1e-9);
  hud.dispatch("pointermove", { clientX: -9000, clientY: 400 });
  assert.ok(c.S.manual.az >= 0 && c.S.manual.az < 360);
});

test("zoom: two fingers pinch the view, and the finger that stays down does not drag it", async () => {
  const c = loadCompass({ intro: "fail" });
  const hud = c.$("hud"), stop = { stopImmediatePropagation() {} };
  const ev = (type, id, x, y) => hud.dispatch(type, { pointerId: id, clientX: x, clientY: y, ...stop });
  ev("pointerdown", 1, 100, 400); ev("pointerdown", 2, 200, 400);
  ev("pointermove", 2, 300, 400);                                    // fingers 100 px apart, then 200 px
  assert.equal(c.S.zoom, 2);
  assert.equal(c.S.manual.az, 180, "a pinch does not turn the view");
  ev("pointermove", 2, 40000, 400);
  assert.equal(c.S.zoom, 300, "zoom stops at 300x");
  ev("pointermove", 2, 110, 400);
  assert.equal(c.S.zoom, 0.5, "with no camera the view can widen, to half");
  ev("pointerup", 2, 110, 400); ev("pointermove", 1, 600, 400);
  assert.equal(c.S.manual.az, 180, "the remaining finger does not drag");
  ev("pointerup", 1, 600, 400);
  c.S.camOn = true; hud.dispatch("wheel", { deltaY: 5000 });
  assert.equal(c.S.zoom, 1, "the camera picture cannot be made wider than the lens");
  hud.dispatch("wheel", { deltaY: -200 });
  assert.ok(c.S.zoom > 1.4 && c.$("cam").style.transform === `scale(${c.S.zoom})`, "the camera picture is enlarged by the same factor");
  ev("pointerdown", 1, 0, 400); ev("pointermove", 1, 844, 400);       // one finger: 70 deg per screen height, divided by the zoom
  assert.ok(Math.abs(c.S.manual.az - (180 - 70 / c.S.zoom)) < 1e-9);
});

// a phone page with a fixed time and place, so frames drawn at high zoom do not move the view
const AT = "2026-11-15T06:00:00Z", HERE = { lat: 47.6, lon: -122.3 };
async function phoneAt(az, alt, more = "") {
  const c = loadCompass({ intro: "fail", search: `?debug=1&at=${AT}&lat=${HERE.lat}&lon=${HERE.lon}${more}` });
  await c.flush();
  await c.$("go").onclick();
  aimPhone(c, az, alt);
  return c;
}
const near = (p, az, alt, tol = 1) => Math.abs(Orient.wrap180(p.az - az)) < tol && Math.abs(p.alt - alt) < tol;

test("hold mode: from 8x the view stops following the phone, and below 6x it follows again", async () => {
  const c = await phoneAt(100, 20);
  c.setZoom(7.9);
  assert.equal(c.S.hold, false, "not at 7.9x");
  c.setZoom(8);
  assert.equal(c.S.hold, true, "held at 8x");
  const held = c.pose();
  assert.ok(near(held, 100, 20), `held where the phone pointed, got ${held.az}, ${held.alt}`);
  aimPhone(c, 140, 35);                                       // the phone moves (or its sensors jitter)
  c.frame();                                                  // and a frame at a fixed time adds no sidereal drift
  assert.deepEqual([c.pose().az, c.pose().alt], [held.az, held.alt], "the held view does not move");
  assert.match(c.$("telemetry").innerHTML, /ZOOM<\/b> 8\.0× HELD/);
  c.setZoom(12); c.frame();
  assert.match(c.$("telemetry").innerHTML, /ZOOM<\/b> 12× HELD/, "no decimals from 10x");
  c.setZoom(6.5);
  assert.equal(c.S.hold, true, "still held at 6.5x: the gap stops flicker");
  c.setZoom(5.9);
  assert.equal(c.S.hold, false, "let go below 6x");
  assert.ok(near(c.pose(), 140, 35), `follows the phone again, got ${c.pose().az}, ${c.pose().alt}`);
});

test("hold mode: one finger and the arrow keys move the held view, slower when zoomed in", async () => {
  const c = await phoneAt(100, 20);
  c.setZoom(10);
  const { az, alt } = c.S.manual, hud = c.$("hud");
  hud.dispatch("pointerdown", { pointerId: 1, isPrimary: true, clientX: 0, clientY: 400 });
  hud.dispatch("pointermove", { pointerId: 1, clientX: 844, clientY: 400 });     // a screen height: 70 deg, divided by the zoom
  hud.dispatch("pointerup", { pointerId: 1, clientX: 844, clientY: 400 });
  assert.ok(Math.abs(Orient.wrap180(c.S.manual.az - (az - 7))) < 1e-9, `drag: ${az} -> ${c.S.manual.az}`);
  for (const fn of c.windowListeners.keydown) fn({ key: "ArrowUp", target: { tagName: "BODY" } });
  assert.ok(Math.abs(c.S.manual.alt - (alt + 0.2)) < 1e-9, `arrow key: 2 deg divided by the zoom, ${alt} -> ${c.S.manual.alt}`);
  assert.deepEqual([c.pose().az, c.pose().alt], [c.S.manual.az, c.S.manual.alt]);
});

test("hold mode: a selected target within 6 deg of the crosshair is centred, not the noisy phone pose (snap)", async () => {
  const c = await phoneAt(337, 28);                          // R Draconis is at az 340.9, alt 29.6 at this time and place
  c.$("targets").querySelectorAll("button").find((b) => b.dataset.id === "r_dra").click();
  c.frame();
  const T = c.S.sel;
  assert.ok(T._sep > 1 && T._sep <= 6, `crosshair ${T._sep} deg from the target`);
  c.setZoom(8);
  assert.deepEqual(c.S.manual, { az: T._az, alt: T._alt });
  assert.equal(c.S.snapped, true);
});

test("from 8x a dragged or held view turns with the sky, so a star stays in the view (sidereal tracking)", async () => {
  const time = { t: Date.parse(AT) }, capella = { ra: 79.17, dec: 46.0 }, D2R = Math.PI / 180;
  const c = loadCompass({ intro: "fail", search: `?debug=1&lat=${HERE.lat}&lon=${HERE.lon}`, time });
  await c.$("go").onclick();
  const seen = () => Sky.observe(capella, new Date(time.t), HERE.lat, HERE.lon);
  const unit = (p) => [Math.sin(p.az * D2R) * Math.cos(p.alt * D2R), Math.cos(p.az * D2R) * Math.cos(p.alt * D2R), Math.sin(p.alt * D2R)];
  const apart = (a, b) => Math.acos(Math.min(1, unit(a).reduce((s, x, i) => s + x * unit(b)[i], 0))) / D2R;
  const start = seen();
  c.S.manual = { az: start.az, alt: start.alt };
  c.setZoom(300);
  c.$("hud").dispatch("pointerdown", { pointerId: 1, isPrimary: true, clientX: 200, clientY: 400 });   // a finger rests on the sky
  c.frame();
  for (let i = 0; i < 20; i++) { time.t += 30000; c.frame(); }    // 10 minutes, a frame every 30 s
  c.$("hud").dispatch("pointermove", { pointerId: 1, clientX: 200, clientY: 400 });
  assert.ok(apart(c.S.manual, start) > 1, `the view turned ${apart(c.S.manual, start).toFixed(2)} deg with the sky`);
  assert.ok(apart(c.S.manual, seen()) < 0.01, `${apart(c.S.manual, seen()).toFixed(4)} deg from Capella after 10 minutes`);
});

test("location note: a later GPS timeout does not claim the location was declined", async () => {
  const run = async (events) => {
    const geolocation = { watchPosition: (ok, fail) => { for (const e of events) e.code ? fail(e) : ok({ coords: { latitude: 47.6, longitude: -122.3, accuracy: 12, altitude: null } }); } };
    const c = loadCompass({ intro: "fail", geolocation });
    await c.$("go").onclick(); await c.flush();
    return c.S.locNote;
  };
  assert.equal(await run([{}, { code: 3 }]), "GPS ±12 m");
  assert.match(await run([{ code: 1 }]), /declined/);
  assert.match(await run([{ code: 3 }]), /no GPS fix yet/);
});

test("telemetry shows the time-zone city with every underscore replaced", async () => {
  const c = loadCompass({ intro: "fail", timeZone: "America/Port_of_Spain" });
  await c.$("go").onclick();
  c.frame();
  assert.match(c.$("telemetry").innerHTML, /Port of Spain/);
});

test("Recalibrate without motion sensors explains why instead of opening a calibration that never moves", async () => {
  const c = loadCompass({ intro: "fail" });
  await c.$("go").onclick();
  c.runTimers(300);                                // no sensor events: drag mode
  assert.equal(c.$("calib").hidden, true);
  c.$("recalBtn").click();
  assert.equal(c.$("calib").hidden, true, "no calibration sheet without sensors");
  assert.equal(c.F.flat, null);
  assert.match(c.$("guideSub").textContent, /needs a phone's motion sensors/);
  aimPhone(c, 100, 10);                            // with sensors it opens as before
  c.$("recalBtn").click();
  assert.equal(c.$("calib").hidden, false);
});

test("picking a target from the list after a star search drops the stale ?star=", async () => {
  const c = loadCompass({ intro: "fail", search: "?target=found&star=Sirius" });
  await c.flush(); await c.flush();
  c.pickStar({ name: "Vega", ra: 279.23473, dec: 38.78369, alt: [] });
  assert.equal(c.location.searchParams.get("star"), "Vega");
  const btn = (id) => c.$("targets").querySelectorAll("button").find((b) => b.dataset.id === id);
  btn("r_dra").click();
  assert.equal(c.location.searchParams.get("target"), "r_dra");
  assert.equal(c.location.searchParams.get("star"), null, `URL ${c.location.search}`);
  btn("found").click();                            // the searched star's own chip keeps its name
  assert.equal(c.location.searchParams.get("target"), "found");
  assert.equal(c.location.searchParams.get("star"), "Vega");
});

test("Webb sheet: the red cross for a searched star sits where the star was on the frame's date", async () => {
  const vega = { name: "Vega", ra: 279.23473, dec: 38.78369, pmra: 200.94, pmdec: 286.23, alt: [], spect: "A0Va", mag: 0.03 };
  const at = (y) => ({ year: y, ra: vega.ra + vega.pmra * (y - 2000) / 3.6e6 / Math.cos(vega.dec * Math.PI / 180), dec: vega.dec + vega.pmdec * (y - 2000) / 3.6e6 });
  const pathView = { sky: async () => ({ now: 2026.9, pts: [1990, 2000, 2010, 2020, 2030, 2040].map(at) }), render: async () => null, trail: async () => null };
  const frame = { obs: "jw01234-o001_t001_nircam", ra: 279.2355, dec: 38.7845, r: 0.05, inst: "NIRCam", target: "VEGA", pid: "1234", mjd: 60100,
    hull: [279.2, 38.75, 279.27, 38.75, 279.27, 38.82, 279.2, 38.82] };
  const rendered = [];
  const webb = { load: async () => ({ count: 1 }), framesAt: () => [frame], near: () => [], best: (f) => f, describe: () => ({ title: "Debris disk", line: "NIRCam" }),
    source: () => "outline", esc: (t) => String(t), full: () => "#", progUrl: () => "#", thumb: () => "#", name: (q) => q.target,
    dateOf: (mjd) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 10), sep: () => 0, appeal: () => 0,
    render: async (el, ra, dec, frames, opts) => { rendered.push(opts); }, setOpacity() {}, setBase() {} };
  const c = loadCompass({ intro: "fail", webb, pathView });
  await c.flush();
  c.pickStar(vega);
  c.$("aboutBtn").click();
  for (let i = 0; i < 5; i++) await c.flush();
  c.$("dWebb").querySelector("button").onclick();
  for (let i = 0; i < 5; i++) await c.flush();
  assert.equal(rendered.length, 1, "the Webb view was drawn");
  const year = 2000 + (frame.mjd - 51544.5) / 365.25, want = at(year), m = rendered[0].mark;
  const arcsec = (a, b) => Math.hypot((a.ra - b.ra) * Math.cos(b.dec * Math.PI / 180), a.dec - b.dec) * 3600;
  assert.ok(arcsec(m, want) < 0.01, `mark ${arcsec(m, want).toFixed(3)}" from the 2023 position`);
  assert.ok(arcsec(m, vega) > 7, "moved off the J2000 catalogue position (Vega: about 8 arcsec by 2023)");
  assert.match(c.$("wNote").innerHTML, /red cross is Vega on 2023-06-05/);
});

test("Webb sheet: without a known motion the red cross stays on the catalogue position", async () => {
  const star = { name: "Nomotion", ra: 10, dec: 20, alt: [] };
  const frame = { obs: "jw1", ra: 10, dec: 20, r: 0.05, inst: "NIRCam", target: "X", pid: "1", mjd: 60100, hull: [9.9, 19.9, 10.1, 19.9, 10.1, 20.1, 9.9, 20.1] };
  const rendered = [];
  const webb = { load: async () => ({ count: 1 }), framesAt: () => [frame], near: () => [], best: (f) => f, describe: () => ({ title: "t", line: "l" }),
    source: () => "outline", esc: (t) => String(t), full: () => "#", progUrl: () => "#", thumb: () => "#", name: (q) => q.target,
    dateOf: () => "2023-06-13", sep: () => 0, appeal: () => 0, render: async (el, ra, dec, frames, opts) => { rendered.push(opts); }, setOpacity() {}, setBase() {} };
  const pathView = { sky: async () => null, render: async () => null, trail: async () => null };
  const c = loadCompass({ intro: "fail", webb, pathView });
  await c.flush();
  c.pickStar(star);
  c.$("aboutBtn").click();
  for (let i = 0; i < 5; i++) await c.flush();
  c.$("dWebb").querySelector("button").onclick();
  for (let i = 0; i < 5; i++) await c.flush();
  assert.deepEqual(rendered[0].mark, { ra: 10, dec: 20 });
  assert.doesNotMatch(c.$("wNote").innerHTML, /red cross/);
});

test("the selected star's trail labels are thinned so years never print on top of each other", async () => {
  const yearLabels = async (spreadDeg) => {
    const c = loadCompass({ intro: "fail" });
    await c.flush();
    await c.$("go").onclick();
    c.S.manual = { az: 200, alt: 40 };
    c.frame();
    const cr = c.S.crosshair;
    c.S.sel = c.S.targets.find((t) => t.id === "r_dra");
    c.S.trailFor = `${c.S.sel.id}:${c.S.sel.name}`;          // hand the page a ready trail
    c.S.trail = { half: 100000, now: 2026.9, pts: Array.from({ length: 81 }, (_, i) => ({ year: 2026.9 - 100000 + 2500 * i, ra: cr.ra, dec: cr.dec + spreadDeg * (i / 80 - 0.5) })) };
    c.$("hud").texts.length = 0;
    c.frame();
    return c.$("hud").texts.filter(([t]) => /\d (BCE|CE)$/.test(t));
  };
  const crowded = await yearLabels(0.0001);                 // a slow star: the whole trail is a few pixels long
  assert.equal(crowded.length, 1, JSON.stringify(crowded));
  const spread = await yearLabels(8);                       // a fast star: four labels, 2 deg (25 px) apart
  assert.equal(spread.length, 4, spread.map((t) => t[0]).join(" | "));
});
