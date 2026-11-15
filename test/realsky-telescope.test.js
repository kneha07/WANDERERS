// The real app/realsky.js (the photographs behind the Sky Compass, and the telescope view) run in Node with a small
// fake page, a fake archive, a fake clock and a fake Aladin.  node --test test/realsky-telescope.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const Sky = require("../app/sky.js"), SkyView = require("../app/skyview.js"), Hips = require("../app/hips.js"), Orient = require("../app/orient.js");
const SRC = fs.readFileSync(path.join(__dirname, "..", "app", "realsky.js"), "utf8").replace("(await import(ALADIN_URL)).default", "__A");
assert.ok(SRC.includes("__A"), "the Aladin import is replaced by the fake");
const D2R = Math.PI / 180, NOW = new Date("2026-11-15T06:00:00Z"), HERE = { lat: 47.6, lon: -122.3 };
const CAPELLA = Sky.observe({ ra: 79.172, dec: 45.998 }, NOW, HERE.lat, HERE.lon);   // 52 deg up in the north-east
const STARS = { stars: [[101.29, -16.72, -1.46, "A"], [79.172, 45.998, 0.08, "G"]], meta: { cons: [] }, list: [] };

// a level camera pose (no roll) looking at az/alt
function poseAt(az, alt) {
  const f = [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
  let up = [0, 0, 1].map((z, i) => z - f[2] * f[i]); const n = Math.hypot(...up); up = up.map((x) => x / n);
  return { az, alt, forward: f, up, right: [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]] };
}

// archive (calls.archive, can change in a test): "ok", "down" (the probe fails) or "hang" (the probe answers only when
// calls.release() is called)
function load({ sky = "eye", camOn = false, archive = "ok", online = true, connection } = {}) {
  const els = {}, timers = [], clock = { t: Date.parse("2026-11-15T06:00:00Z") };
  const calls = { archive, probes: 0, aladins: 0, views: [], release: null };
  const buttons = { surveySeg: ["visible", "infrared"].map((survey) => ({ dataset: { survey }, classList: { toggle() {} }, setAttribute() {} })) };
  const el = (id) => els[id] || (els[id] = {
    id, hidden: id === "skyDeep" || id === "dragBar", style: {}, textContent: "", value: "", dataset: {}, listeners: {}, children: [],
    classes: new Set(), setAttribute() {}, querySelectorAll: () => buttons[id] || [], setPointerCapture() {},
    get classList() { const k = this.classes; return { toggle: (c, on) => ((on ?? !k.has(c)) ? k.add(c) : k.delete(c)), contains: (c) => k.has(c) }; },
    replaceChildren(...nodes) { this.children = nodes; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    dispatch(type, e) { for (const fn of this.listeners[type] || []) fn({ stopImmediatePropagation() {}, ...e }); },
    append(...a) { this.textContent += a.map((x) => (typeof x === "string" ? x : `[${x.textContent}]`)).join(""); },
  });
  const aladin = { setBaseImageLayer() {}, setFoV: (v) => calls.views.push(["fov", v]), gotoRaDec: (ra, dec) => calls.views.push(["goto", ra, dec]),
    setRotation: (r) => calls.views.push(["rot", r]) };
  const env = {
    document: { getElementById: el, createElement: () => ({ textContent: "" }) },
    location: new URL(`https://wanderers.test/compass.html?sky=${sky}`),
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async (u) => {
      if (!/\/properties$/.test(u)) return { json: async () => STARS };      // the star list
      calls.probes++;                                                        // the archive probe before Aladin starts
      if (calls.archive === "down") throw new Error("unreachable");
      if (calls.archive === "hang") return new Promise((ok) => (calls.release = () => ok({ ok: true })));
      return { ok: true };
    },
    navigator: { onLine: online, connection }, AbortSignal: { timeout: () => undefined }, innerWidth: 390, innerHeight: 844,
    setTimeout: (fn, ms) => timers.push({ fn, ms }), clearTimeout: (h) => { if (timers[h - 1]) timers[h - 1].fn = null; },
    Date: class extends Date { constructor(...a) { super(...(a.length ? a : [clock.t])); } static now() { return clock.t; } },
    Hips, SkyView, Sky, Orient,
    // a build puts Aladin's canvas into #skyDeep; with calls.aladinThrows it then fails (a browser without WebGL2)
    __A: { init: Promise.resolve(), imageHiPS: () => ({}),
      aladin: () => { calls.aladins++; el("skyDeep").children.push("aladin canvas"); if (calls.aladinThrows) throw new Error("no WebGL2"); return aladin; } },
  };
  const win = {};
  new Function(...Object.keys(env), "window", SRC)(...Object.values(env), win);
  const RS = win.RealSky, S = { zoom: 1, sensors: false, hold: false, snapped: false, manual: { az: CAPELLA.az, alt: CAPELLA.alt } };
  const F = { compassFrozen: false, compassAccuracy: null, fineAz: 0, fineAlt: 0 };
  let P = poseAt(CAPELLA.az, CAPELLA.alt);
  const focal = () => 422 / Math.tan(30 * D2R) * S.zoom;              // compass.js with no camera: 60 deg tall at 1x
  RS.init({ pose: () => P, focal, loc: () => HERE, camOn: () => camOn, phoneSteers: () => S.sensors && !S.hold, F, S, onStar() {}, openSight() {} });
  const g = new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => ((t[k] = v), true) });
  return {
    RS, S, F, el, calls, timers, clock,
    frame: () => RS.draw(g, P, focal(), 390, 844, NOW, HERE),
    aim: (az, alt) => { P = poseAt(az, alt); },
    settle: async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); },
    note: () => el("skyNote").textContent,
    opacity: () => (el("skyDeep").hidden ? "hidden" : +el("skyDeep").style.opacity),
  };
}

test("cover(): 0 until the photographs load; then 1 in Deep, and the telescope amount (3x to 6x) in Eye and Off", async () => {
  for (const sky of ["eye", "off", "deep"]) {
    const c = load({ sky });
    c.S.zoom = 4.5; c.frame();
    assert.equal(c.RS.cover(), 0, `${sky}: still loading`);
    await c.settle();
    assert.equal(c.RS.DEEP.state, "ready");
    const at = (z) => { c.S.zoom = z; c.frame(); return c.RS.cover(); };
    assert.deepEqual([at(1), at(3), at(4.5), at(6), at(300)], sky === "deep" ? [1, 1, 1, 1, 1] : [0, 0, 0.5, 1, 1], sky);
  }
});

test("the photographs: started unseen at 2x, faded in from 3x to 6x; zooming never changes the user's own choice", async () => {
  const c = load();
  const op = (z) => { c.S.zoom = z; c.frame(); return c.opacity(); };
  assert.equal(op(1), "hidden");
  assert.equal(c.calls.probes, 0, "nothing is fetched at 1x");
  assert.equal(op(2), 0);
  assert.equal(c.RS.DEEP.state, "loading", "started at 2x, so they are ready by 3x");
  await c.settle();
  assert.deepEqual([op(3), op(4.5), op(6), op(300), op(1)], [0, 0.5, 1, 1, "hidden"]);
  assert.deepEqual([c.RS.R.sky, c.RS.R.mix, c.RS.R.survey], ["eye", 0.8, "visible"]);
});

test("on mobile data or with Save-Data on, the photographs start at 3x, not 2x", async () => {
  for (const connection of [{ type: "cellular" }, { saveData: true }]) {
    const c = load({ connection });
    c.S.zoom = 2; c.frame();
    assert.deepEqual([c.RS.DEEP.state, c.opacity(), c.calls.probes], ["idle", "hidden", 0], JSON.stringify(connection));
    c.S.zoom = 3; c.frame();
    assert.equal(c.RS.DEEP.state, "loading", JSON.stringify(connection));
  }
  const wifi = load({ connection: { type: "wifi" } });
  wifi.S.zoom = 2; wifi.frame();
  assert.equal(wifi.RS.DEEP.state, "loading", "otherwise from 2x");
});

test("with the camera on, Deep's own camera mix rises to 1 as you zoom in", async () => {
  const c = load({ sky: "deep", camOn: true });
  c.frame(); await c.settle();
  const op = (z) => { c.S.zoom = z; c.frame(); return c.opacity(); };
  assert.equal(op(1), 0.8);
  assert.ok(Math.abs(op(4.5) - 0.9) < 1e-12);
  assert.equal(op(6), 1);
});

test("a failed start waits 30 s before the next one; in Deep it falls back to Eye and says so; choosing Deep tries at once", async () => {
  const c = load({ archive: "down" });
  c.S.zoom = 5; c.frame(); await c.settle();
  const tried = c.calls.probes;
  assert.ok(tried >= 1);
  for (let i = 0; i < 10; i++) c.frame();
  await c.settle();
  assert.equal(c.calls.probes, tried, "no new try within 30 s");
  assert.match(c.note(), /Telescope photographs are not reachable now\./);
  c.clock.t += 30001; c.frame(); await c.settle();
  assert.ok(c.calls.probes > tried, "a new try after 30 s");

  const d = load({ sky: "deep", archive: "down" });
  d.frame(); await d.settle();
  assert.equal(d.RS.R.sky, "eye");
  assert.match(d.note(), /^Sky photographs are not reachable\. Showing the Eye view\./);
  const before = d.calls.probes;
  d.RS.setSky("deep"); d.frame(); await d.settle();
  assert.ok(d.calls.probes > before, "choosing Deep tries again at once");
});

test("Aladin itself failing (no WebGL2) waits 30 s as well: one build and one probe in 20 frames, then a fresh try", async () => {
  const c = load();
  c.calls.aladinThrows = true;
  c.S.zoom = 5;
  for (let i = 0; i < 20; i++) { c.frame(); await c.settle(); }
  assert.deepEqual([c.calls.aladins, c.calls.probes], [1, 1]);
  assert.deepEqual(c.el("skyDeep").children, [], "the half-built Aladin is removed, so the next try starts fresh");
  assert.match(c.note(), /Telescope photographs are not reachable now\./);
  c.clock.t += 30001; c.frame(); await c.settle();
  assert.deepEqual([c.calls.aladins, c.calls.probes], [2, 2], "a second try after 30 s");
});

test("a start that hangs for 20 s counts as failed, and its late answer changes nothing", async () => {
  const c = load({ archive: "hang" });
  c.S.zoom = 4; c.frame(); await c.settle();
  assert.equal(c.RS.DEEP.state, "loading");
  assert.match(c.note(), /^Loading telescope photographs… /);
  const guard = c.timers.find((t) => t.ms === 20000 && t.fn);
  assert.ok(guard, "a 20 s guard is set");
  guard.fn(); await c.settle();
  assert.equal(c.RS.DEEP.state, "idle");
  assert.equal(c.RS.DEEP.retryAt, c.clock.t + 30000, "the same 30 s wait as a failed start");
  c.frame();
  assert.match(c.note(), /Telescope photographs are not reachable now\./);
  c.calls.release(); await c.settle();
  assert.equal(c.RS.DEEP.state, "idle", "the late answer does not make it ready");
  assert.equal(c.calls.aladins, 0, "and starts no Aladin");

  const ok = load();
  ok.S.zoom = 4; ok.frame(); await ok.settle();
  assert.equal(ok.RS.DEEP.state, "ready");
  assert.ok(!ok.timers.some((t) => t.ms === 20000 && t.fn), "a start in time clears its guard");
});

test("a survey switch that hangs ends after 20 s and keeps the photographs on screen; a late answer changes nothing", async () => {
  const c = load({ sky: "deep" });
  c.frame(); await c.settle();
  assert.equal(c.RS.DEEP.survey, "visible");
  c.calls.archive = "hang";
  c.el("surveySeg").querySelectorAll("button")[1].onclick();          // Infrared
  c.frame(); await c.settle();
  assert.match(c.note(), /^Loading sky photographs… /);
  const guard = c.timers.find((t) => t.ms === 20000 && t.fn);
  assert.ok(guard, "the switch has the same 20 s guard as the first start");
  guard.fn(); await c.settle(); c.frame();
  assert.deepEqual([c.RS.DEEP.state, c.RS.DEEP.survey, c.RS.R.survey, c.opacity()], ["ready", "visible", "visible", 1]);
  assert.match(c.note(), /^The infrared photographs are not reachable\. Kept the visible ones\./);
  c.calls.release(); await c.settle(); c.frame();
  assert.deepEqual([c.RS.DEEP.state, c.RS.DEEP.survey, c.RS.DEEP.base], ["ready", "visible", Hips.CONFIG.surveys.visible.hosts[0]]);
});

test("the note zoomed in names the survey and says 'archive photograph'; 'approximate' only without a sight check or snap", async () => {
  const c = load();
  c.S.zoom = 12; c.frame(); await c.settle(); c.frame();
  assert.match(c.note(), /^Telescope view: Digitized Sky Survey 2 \(visible light\)\. Archive photograph, not live\./);
  const approx = /Your compass is good to a few degrees, so this is near where you point, not exactly it\./;
  assert.doesNotMatch(c.note(), approx, "drag mode, no sensors");
  const claim = /Direction good to about/;
  c.S.sensors = true; c.frame();
  assert.match(c.note(), approx);
  assert.doesNotMatch(c.note(), claim, "one accuracy claim only: not also 'Direction good to about ...'");
  c.S.snapped = true; c.frame();
  assert.doesNotMatch(c.note(), approx, "snapped to a target");
  assert.match(c.note(), claim, "then the usual direction text is back");
  c.S.snapped = false; c.F.compassFrozen = true; c.frame();
  assert.doesNotMatch(c.note(), approx, "after a sight check");
  assert.match(c.note(), claim);
});

test("at 150x and 300x the photographs follow every move of a quarter pixel or more: small steps and a pinch", async () => {
  const c = load();
  c.S.zoom = 300; c.frame(); await c.settle(); c.frame();
  const synced = (move) => { c.calls.views.length = 0; move(); c.frame(); return c.calls.views.length > 0; };
  let az = CAPELLA.az;
  for (const z of [150, 300]) {
    c.S.zoom = z; c.frame();
    for (let i = 1; i <= 3; i++) assert.ok(synced(() => c.aim((az += 0.003), CAPELLA.alt)), `${z}x: 0.003 deg step ${i} (several pixels)`);
    assert.equal(synced(() => c.aim(az + 1e-6, CAPELLA.alt)), false, `${z}x: a move far under a quarter pixel is skipped`);
  }
  assert.ok(synced(() => { c.S.zoom = 280; }), "a pinch from 300x to 280x reaches the photographs");
});

test("with no connection the note gives one reason: 'No connection', not 'not reachable'", async () => {
  const c = load({ online: false, archive: "down" });
  c.S.zoom = 4; c.frame(); await c.settle(); c.frame();
  assert.match(c.note(), /No connection: no finer photographs\./);
  assert.doesNotMatch(c.note(), /not reachable/);
});

test("while the view is held the note says nothing about it: the hint and HELD sit by the crosshair (compass.js)", async () => {
  const c = load();
  c.S.sensors = true; c.S.zoom = 12; c.frame(); await c.settle();
  Object.assign(c.S, { hold: true, holds: 1 }); c.frame();
  assert.doesNotMatch(c.note(), /held/i);
});

test("the note sits on a dark pill while the photographs cover the view, so it can be read on them", async () => {
  const c = load();
  const pill = () => c.el("skyNote").classList.contains("on-photo");
  c.frame();
  assert.equal(pill(), false, "1x: drawn stars, no photographs");
  c.S.zoom = 12; c.frame(); await c.settle(); c.frame();
  assert.equal(pill(), true, "12x: on the photographs");
  c.S.zoom = 1; c.frame();
  assert.equal(pill(), false, "back at 1x");
});

test("Drag the sky aims a held view and leaves the sight-check offsets and the compass alone", async () => {
  const c = load();
  c.S.sensors = true; c.S.hold = true; c.S.zoom = 10; c.frame();
  c.el("dragSky").onclick();
  const before = { ...c.S.manual }, hud = c.el("hud");
  hud.dispatch("pointerdown", { clientX: 195, clientY: 422, pointerId: 1 });
  hud.dispatch("pointermove", { clientX: 215, clientY: 432, pointerId: 1 });
  hud.dispatch("pointerup", { clientX: 215, clientY: 432, pointerId: 1 });
  assert.notDeepEqual(c.S.manual, before, "the held view moved");
  assert.deepEqual([c.F.fineAz, c.F.fineAlt], [0, 0]);
  c.el("dragDone").onclick();
  assert.equal(c.F.compassFrozen, false, "Done does not freeze the compass while held");
});

test("cancelDrag() ends a running Drag the sky as Cancel does, and the finger stops moving the view", async () => {
  const c = load();
  c.frame();
  c.el("dragSky").onclick();
  const before = { ...c.S.manual }, hud = c.el("hud");
  hud.dispatch("pointerdown", { clientX: 195, clientY: 422, pointerId: 1 });
  hud.dispatch("pointermove", { clientX: 215, clientY: 432, pointerId: 1 });
  c.RS.cancelDrag();
  assert.deepEqual(c.S.manual, before, "the view is back where Drag the sky started");
  assert.deepEqual([c.RS.R.calDrag, c.el("dragBar").hidden], [null, true]);
  hud.dispatch("pointermove", { clientX: 260, clientY: 470, pointerId: 1 });
  assert.deepEqual(c.S.manual, before, "the finger still down no longer moves it");
});
