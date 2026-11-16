// Browser checks for the real sky behind the Sky Compass (app/realsky.js), in a real headless browser over the
// DevTools protocol. The page runs with a fixed time and place and skips the intro (see FIXED below).
// No packages: Node 22+ (global WebSocket and fetch) and Edge or Chrome.
//
//   node test/browser/realsky.mjs              (in this workspace: node.exe from WSL, so it can reach Windows Edge)
//   BROWSER="/path/to/chrome" node test/browser/realsky.mjs
//
// It needs the network (IRSA tiles, the Aladin Lite script) for parts 1 and 2. It then proves the offline
// behaviour by starting the browser again with those hosts mapped to nowhere:
//   1. registration: photographs and canvas put the same star on the same pixel, on a phone-sized screen,
//      for dragged views and for fed phone poses that lean (roll); then Infrared, the cache trim, Eye, taps, drag the sky,
//      and the telescope view (Eye at 12x on Capella, small moves at 150x and 300x, a pinch, hold with fed phone poses)
//   2. save the sky for a latitude; the saved cache fills and the "recent" cache holds no copy of it
//   3. same profile, archive unreachable AND our own server stopped: the page still opens, Eye and Deep work
//   4. fresh profile, archive unreachable: Deep falls back to Eye and says so
// Results and screenshots go to artifacts/real-sky/. Exit code 1 if any check fails.
import { spawn } from "node:child_process";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = path.join(ROOT, "artifacts", "real-sky"), PROFILE = path.join(OUT, "prof"), PROFILE2 = path.join(OUT, "prof2");
const BROWSER = process.env.BROWSER || ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find((p) => fs.existsSync(p));
// Ports are chosen per run, so two copies of this check (two agents, two worktrees) cannot talk to each other's
// server or browser. That happened once with fixed ports: the page came from the other worktree.
let PORT = 0;
const DEBUG_PORT = 9300 + (process.pid % 600);
const HOSTS_DOWN = ["irsa.ipac.caltech.edu", "cdn.skies.esac.esa.int", "cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com", "gibs.earthdata.nasa.gov"].map((h) => `MAP ${h} 127.0.0.1:9`).join(",");
const FIXED = "debug=1&go=1&intro=skip&cam=0&at=2026-11-15T06:00:00Z&lat=47.6&lon=-122.3";
const PHONE = { width: 390, height: 844, deviceScaleFactor: 3, mobile: true };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [], browsers = [];   // every browser started, so a failed run still closes them
const wipe = () => { try { for (const p of [PROFILE, PROFILE2]) fs.rmSync(p, { recursive: true, force: true, maxRetries: 8, retryDelay: 500 }); } catch { /* the browser may still hold a file */ } };
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };

// ---- a static server for app/ ----
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png" };
const server = http.createServer((req, res) => {
  const file = path.join(ROOT, "app", decodeURIComponent(new URL(req.url, "http://x").pathname));
  fs.readFile(file, (err, body) => {
    if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" }); res.end(body);
  });
});

// ---- a minimal DevTools-protocol client for one page ----
async function launch(extra = [], profile = PROFILE) {
  // CI runners (Ubuntu 24.04) block the sandbox's user namespaces, so Chrome must run without it there.
  const proc = spawn(BROWSER, [...(process.env.CI ? ["--no-sandbox"] : []), "--headless=new", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--no-first-run",
    // Keep the test browser apart from the user: Edge can sign a new profile in with the Windows account and
    // sync its extensions into it (seen 2026-11-14: wallet and sign-up pages opened in the test profile).
    "--disable-sync", "--disable-extensions", "--no-default-browser-check",
    `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profile}`, ...extra, "about:blank"], { stdio: "ignore" });
  browsers.push(proc);
  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(250);
    const list = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`).then((r) => r.json()).catch(() => []);
    // Edge's own components run as extension background pages; a user extension shows up as a page (its welcome tab).
    if (list.some((t) => t.type === "page" && /^chrome-extension:/.test(t.url))) { proc.kill(); throw new Error("the test browser loaded extensions, so it is not isolated from the user; stopped"); }
    target = list.find((t) => t.type === "page" && t.url === "about:blank") || null;
  }
  if (!target) throw new Error("the browser did not open a debugging port");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
  let id = 0; const waiting = new Map(), failed = [], requested = [], errors = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
    if (msg.method === "Network.requestWillBeSent") requested.push(msg.params.request.url);
    if (msg.method === "Network.loadingFailed") failed.push(msg.params.requestId);
    if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((ok, no) => {
    const n = ++id; waiting.set(n, (msg) => (msg.error ? no(new Error(`${method}: ${msg.error.message}`)) : ok(msg.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  await send("Page.enable"); await send("Network.enable"); await send("Runtime.enable"); await send("Emulation.setDeviceMetricsOverride", PHONE);
  const page = {
    requested, failed, errors,
    goto: async (query) => { await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/compass.html?${FIXED}&${query}` }); await send("Page.bringToFront").catch(() => {}); },
    eval: async (expr) => {
      const r = await send("Runtime.evaluate", { expression: `(async () => (${expr}))()`, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    },
    until: async (expr, ms = 60000, what = expr) => {
      for (const t0 = Date.now(); Date.now() - t0 < ms; await sleep(300)) { if (await page.eval(expr).catch(() => false)) return true; }
      throw new Error(`timed out waiting for: ${what}`);
    },
    // A mouse drag in CSS pixels, from (x, y) by (dx, dy). Mouse events also fire pointer events.
    drag: async (x, y, dx, dy) => {
      await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
      for (let i = 1; i <= 6; i++) await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + (dx * i) / 6, y: y + (dy * i) / 6, button: "left", buttons: 1 });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x + dx, y: y + dy, button: "left", buttons: 0, clickCount: 1 });
    },
    tap: async (x, y) => {
      for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
    },
    shot: async (name) => fs.writeFileSync(path.join(OUT, name), Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64")),
    close: async () => { await send("Browser.close").catch(() => {}); await sleep(1500); proc.kill(); },
  };
  return page;
}

const deepReady = `window.RealSky && RealSky.DEEP.state === "ready"`;
const note = `document.getElementById("skyNote").textContent`;
const W8 = "window.__wanderers";
// Aim the view. Without sensors this is the drag-to-look direction; with fake sensors it is a fed phone pose.
const aim = (az, alt) => `(${W8}.S.sensors = false, ${W8}.S.manual.az = ${az}, ${W8}.S.manual.alt = ${alt}, true)`;
// A phone pose fed as gyroscope events (W3C angles). Fed many times so the smoothing settles on it.
const feed = (alpha, beta, gamma) => `(() => { const w = ${W8}; w.S.sensors = true; const t0 = performance.now();
  for (let i = 0; i < 80; i++) w.F.feed({ alpha: ${alpha}, beta: ${beta}, gamma: ${gamma}, t: t0 + i * 16 }); return true; })()`;

async function main() {
  if (!BROWSER) throw new Error("No Edge or Chrome found. Set BROWSER to its path.");
  wipe(); fs.mkdirSync(OUT, { recursive: true });
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  PORT = server.address().port;
  const report = { when: new Date().toISOString(), browser: BROWSER, screen: PHONE, registration: [] };

  // ---- 1. Deep: the photographs and the drawn sky put each star on the same pixel ----
  let page = await launch();
  await page.goto("sky=deep");
  await page.until(deepReady, 60000, "the photographs to load");
  await page.until(`!!RealSky.EYE.stars`, 30000, "the star list");
  const reg = async (label) => {
    await sleep(3500);
    const r = await page.eval(`RealSky.selfTest()`);
    report.registration.push({ label, objects: r.stars.length, worst: r.worst, roll: r.roll, pxPerDeg: r.pxPerDeg });
    check(`registration ${label}`, r.worst <= 3 && r.stars.length >= 3, `${r.stars.length} objects, worst ${r.worst} px (1° = ${r.pxPerDeg} px), roll ${r.roll}°`);
    return r;
  };
  for (const [az, alt] of [[180, 30], [0, 60], [90, 10], [300, 45], [200, 84]]) { await page.eval(aim(az, alt)); await reg(`az ${az} alt ${alt}`); }
  for (const [a, b, gm] of [[30, 120, 25], [200, 130, -35], [60, 140, -20], [300, 125, 30]]) { await page.eval(feed(a, b, gm)); await reg(`phone pose alpha ${a} beta ${b} gamma ${gm}`); }
  check("registration covered a leaning phone", report.registration.some((r) => Math.abs(r.roll) > 15));
  await page.eval(aim(300, 45)); const z0 = await reg("az 300 alt 45 again, before zooming"); await page.shot("deep-phone.png");

  // ---- 1b. Infrared ----
  await page.eval(`(document.querySelector('#surveySeg [data-survey="infrared"]').click(), true)`);
  await page.until(`${deepReady} && RealSky.DEEP.survey === "infrared" && /2MASS/.test(RealSky.DEEP.base)`, 40000, "the infrared photographs");
  await reg("infrared, az 300 alt 45");
  check("Infrared: the note names the survey", /2MASS/.test(await page.eval(note)));
  await page.shot("deep-infrared-phone.png");
  await page.eval(`(document.querySelector('#surveySeg [data-survey="visible"]').click(), true)`);
  await page.until(`${deepReady} && RealSky.DEEP.survey === "visible" && /DSS/.test(RealSky.DEEP.base)`, 30000, "the switch back to visible");
  check("switching back to Visible works without a reload", true);

  // ---- 1c. the service worker keeps the newest pictures and drops all of them after the age limit ----
  await page.eval(`(RealSky.setSky("off"), true)`); await sleep(2500);    // no tile may arrive while the cache is checked
  const sw = await page.eval(`(async () => {
    const keys = async () => (await caches.has("wanderers-sky-v1")) ? (await (await caches.open("wanderers-sky-v1")).keys()).map((k) => k.url).filter((u) => !u.includes("__wanderers_meta__")) : [];
    const ask = (msg) => navigator.serviceWorker.ready.then((r) => new Promise((ok) => { const ch = new MessageChannel(); ch.port1.onmessage = () => ok(); r.active.postMessage(msg, [ch.port2]); }));
    const before = await keys();
    await ask({ op: "expire", files: 5 });
    const kept = await keys();
    await ask({ op: "expire", ageMs: 0 });
    return { before: before.length, newest: before.slice(-5), kept, gone: !(await caches.has("wanderers-sky-v1")) };
  })()`);
  check("service worker trim keeps the 5 newest pictures, oldest dropped first", sw.before > 5 && JSON.stringify(sw.kept) === JSON.stringify(sw.newest), `${sw.before} → ${sw.kept.length}`);
  check("service worker drops the recent cache once it is older than the age limit", sw.gone);

  // ---- 1c2. zoom, and a survey that the archive has reissued ----
  await page.eval(`(RealSky.setSky("deep"), ${W8}.setZoom(4), true)`); await page.eval(aim(300, 45));
  await sleep(4000);
  const z = await page.eval(`RealSky.selfTest()`), wide = (r) => [].concat(r.fov)[0];
  report.registration.push({ label: "zoomed in 4 times, az 300 alt 45", objects: z.stars.length, worst: z.worst, roll: z.roll, pxPerDeg: z.pxPerDeg });
  check("zoom: photographs and canvas still agree when zoomed in 4 times", z.worst <= 3 && z.stars.length >= 1 && Math.abs(z.pxPerDeg / z0.pxPerDeg - 4) < 0.05,
    `${z.stars.length} objects, worst ${z.worst} px (1° = ${z.pxPerDeg} px)`);
  check("zoom: the photographs show a quarter of the view", Math.abs(wide(z) - 2 * Math.atan(Math.tan(wide(z0) * Math.PI / 360) / 4) * 180 / Math.PI) < 0.05, `${wide(z0).toFixed(2)}° → ${wide(z).toFixed(2)}°`);
  await page.shot("deep-zoom-phone.png");
  await page.eval(`(RealSky.setSky("off"), ${W8}.setZoom(1), true)`); await sleep(2500);
  const rel = await page.eval(`(async () => {
    const base = RealSky.DEEP.base, data = await caches.open(Hips.CONFIG.caches.pinned), stamp = Hips.releaseUrl(base);
    const read = async () => { const r = await data.match(stamp); return r ? r.json() : null; };
    const tiles = async () => (await caches.has("wanderers-sky-v1")) ? (await (await caches.open("wanderers-sky-v1")).keys()).filter((k) => k.url.startsWith(base + "/Norder")).length : 0;
    const first = await read(), before = await tiles();
    await fetch(base + "/properties"); await new Promise((r) => setTimeout(r, 1500));
    const same = await tiles();                                    // checked less than a day ago: nothing happens
    await data.put(stamp, new Response(JSON.stringify({ at: 0, release: "1999-01-01T00:00Z" })));
    await fetch(base + "/properties");
    let now = null;
    for (let i = 0; i < 60 && !(now && now.at); i++) { await new Promise((r) => setTimeout(r, 250)); now = await read(); }
    return { first, before, same, after: await tiles(), now };
  })()`);
  check("the survey's issue date is recorded with its pictures", !!rel.first && /^\d{4}-\d\d-\d\d/.test(rel.first.release), rel.first && rel.first.release);
  check("a survey checked less than a day ago is left alone", rel.before > 0 && rel.same === rel.before, `${rel.before} pictures`);
  check("a reissued survey: its recent pictures are dropped and the new date is recorded", rel.after === 0 && !!rel.now && rel.now.release === rel.first.release,
    `${rel.before} → ${rel.after}, ${JSON.stringify(rel.now)}`);

  // ---- 1d. Eye ----
  await page.goto("sky=eye&limit=dark");
  await page.until(`window.RealSky && !!RealSky.EYE.stars && !!RealSky.CON.list`, 30000, "the star list and the lines");
  await page.eval(aim(165, 35)); await sleep(1500);
  await page.shot("eye-phone.png");
  const n = await page.eval(`RealSky.EYE.vecs.length`);
  check("Eye, dark site: about 2,500 stars above the horizon", n > 1800 && n < 3300, String(n));

  // ---- 1e. taps: a planet gets a card, a star opens the star sheet ----
  // Aim 8 degrees beside an object that is up, so it is on the screen but not under the crosshair, then tap it.
  const aimBeside = async (ra, dec) => page.eval(`(() => { const L = { lat: 47.6, lon: -122.3 }, o = Sky.observe({ ra: ${ra}, dec: ${dec} }, ${W8}.nowDate(), L.lat, L.lon);
    ${W8}.S.sensors = false; ${W8}.S.manual.az = (o.az + 8) % 360; ${W8}.S.manual.alt = Math.min(80, o.alt); return true; })()`);
  const planet = await page.eval(`(() => { const now = ${W8}.nowDate(); return Sky.planets(now).map((p) => ({ name: p.name, ra: p.ra, dec: p.dec, alt: Sky.observe(p, now, 47.6, -122.3).alt }))
    .filter((p) => p.alt > 12).sort((x, y) => y.alt - x.alt)[0] || null; })()`);
  if (planet) {
    await aimBeside(planet.ra, planet.dec); await sleep(400);
    const q = await page.eval(`${W8}.screenOf(${planet.ra}, ${planet.dec})`);
    await page.tap(q[0], q[1]); await sleep(300);
    const card = await page.eval(`({ shown: !document.getElementById("skyCard").hidden, name: document.getElementById("skyCardName").textContent })`);
    check("tap a planet: the card names it", card.shown && card.name === planet.name, JSON.stringify(card));
    await page.shot("tap-planet-phone.png");
    await page.eval(`(document.getElementById("skyCardClose").click(), true)`);
  } else check("tap a planet: the card names it", false, "no planet is up at the fixed time");
  const star = await page.eval(`RealSky.EYE.stars.slice(0, 60).filter((s) => s[7]).map((s) => ({ name: s[7], ra: s[0], dec: s[1], alt: Sky.observe({ ra: s[0], dec: s[1] }, ${W8}.nowDate(), 47.6, -122.3).alt }))
    .filter((s) => s.alt > 20)[0] || null`);
  if (star) {
    await aimBeside(star.ra, star.dec); await sleep(400);
    const q = await page.eval(`${W8}.screenOf(${star.ra}, ${star.dec})`);
    await page.tap(q[0], q[1]);
    const ok = await page.until(`!document.getElementById("details").hidden`, 8000, "the star sheet").then(() => true).catch(() => false);
    const name = await page.eval(`document.getElementById("dName").textContent`);
    check("tap a star: the star sheet opens on it", ok && name === star.name, `${star.name} → ${name}`);
    await page.shot("tap-star-phone.png");
    await page.eval(`(document.getElementById("dClose").click(), true)`);
  } else check("tap a star: the star sheet opens on it", false, "no named star is up");

  // ---- 1f. drag the sky, with a phone pose that leans: the grabbed point follows the finger ----
  await page.eval(feed(60, 140, -20)); await sleep(300);
  await page.eval(`(document.getElementById("northBtn").click(), document.getElementById("dragSky").click(), true)`);
  const mid = await page.eval(`[innerWidth / 2, innerHeight / 2]`);
  const ref = await page.eval(`(() => { const w = ${W8}, P = w.pose(), L = { lat: 47.6, lon: -122.3 }, c = Sky.unobserve(P.az, P.alt, w.nowDate(), L.lat, L.lon);
    return { ra: c.ra, dec: c.dec, q: w.screenOf(c.ra, c.dec), fine: [w.F.fineAz, w.F.fineAlt] }; })()`);
  await page.drag(mid[0], mid[1], 60, 40);
  await page.eval(feed(60, 140, -20)); await sleep(200);          // the next sensor events apply the new offsets (smoothed)
  const after = await page.eval(`${W8}.screenOf(${ref.ra}, ${ref.dec})`);
  const shift = after ? [after[0] - ref.q[0], after[1] - ref.q[1]] : null;
  check("drag the sky: the grabbed point follows the finger", !!shift && Math.abs(shift[0] - 60) < 2 && Math.abs(shift[1] - 40) < 2,
    shift ? `moved ${shift.map((v) => v.toFixed(1)).join(", ")} px for a drag of 60, 40` : "the point left the screen");
  await page.shot("drag-sky-phone.png");
  await page.eval(`(document.getElementById("dragDone").click(), true)`);
  const fine = await page.eval(`({ az: ${W8}.F.fineAz, alt: ${W8}.F.fineAlt, frozen: ${W8}.F.compassFrozen })`);
  check("drag the sky: Done keeps it as the sight check", fine.frozen && (Math.abs(fine.az - ref.fine[0]) > 1 || Math.abs(fine.alt - ref.fine[1]) > 1),
    `direction ${fine.az.toFixed(2)}°, tilt ${fine.alt.toFixed(2)}°`);

  // ---- 1g. the telescope view: Eye mode, no camera, zoomed in on Capella ----
  // The photographs cover the view and stay on the canvas's pixels while the view moves by small steps at 150x and
  // 300x and while it is pinched (each step is checked 2 frames later). Then hold mode with fed phone poses: the held
  // view does not move when the phone turns. selfTest's worst is 0 when it compares nothing, so each check asks for
  // compared >= 1.
  await page.goto("sky=eye&limit=dark");
  await page.until(`window.RealSky && !!RealSky.EYE.stars && !document.getElementById("ar").hidden`, 30000, "the star list");
  const twoFrames = `new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => ok(true))))`;
  await page.eval(`(() => { const o = Sky.observe({ ra: 79.172, dec: 45.998 }, ${W8}.nowDate(), 47.6, -122.3);
    ${W8}.S.sensors = false; ${W8}.S.manual = { az: o.az, alt: o.alt }; ${W8}.setZoom(12); return true; })()`);
  await page.until(deepReady, 60000, "the telescope photographs");
  await sleep(3500);
  const t12 = await page.eval(`({ cover: RealSky.cover(), r: RealSky.selfTest() })`);
  check("telescope, Eye at 12x on Capella: the photographs cover the view", t12.cover === 1, `cover ${t12.cover}`);
  check("telescope, Eye at 12x on Capella: photographs and canvas agree", t12.r.compared >= 1 && t12.r.worst <= 3,
    `${t12.r.compared} compared (${t12.r.stars.map((s) => s.name).join(", ")}), worst ${t12.r.worst} px (1° = ${t12.r.pxPerDeg} px)`);
  await page.shot("telescope-12x-phone.png");
  const step = async (label, move) => {
    await page.eval(`(${move}, ${twoFrames})`);
    const r = await page.eval(`RealSky.selfTest()`);
    check(`telescope: ${label}`, r.compared >= 1 && r.worst <= 3, `${r.compared} compared, worst ${r.worst} px (1° = ${r.pxPerDeg} px)`);
  };
  for (const z of [150, 300]) {
    await page.eval(`(${W8}.setZoom(${z}), true)`); await sleep(2000);
    for (let i = 1; i <= 4; i++) await step(`${z}x, step ${i} of 0.003° in azimuth`, `${W8}.S.manual.az += 0.003`);
  }
  await page.shot("telescope-300x-phone.png");
  await step("a pinch from 300x to 280x", `${W8}.setZoom(280)`);
  await page.eval(`(${W8}.setZoom(1), true)`);
  await page.eval(feed(30, 120, 25)); await sleep(300);
  await page.eval(`(${W8}.setZoom(10), ${twoFrames})`);
  const held = `(() => { const w = ${W8}, p = w.pose(), q = w.F.pointing(); return { az: p.az, alt: p.alt, hold: w.S.hold, phone: q.az }; })()`;
  const h0 = await page.eval(held);
  await page.eval(feed(33, 120, 25)); await page.eval(twoFrames);
  const h1 = await page.eval(held), turned = ((h1.phone - h0.phone) % 360 + 540) % 360 - 180;
  check("telescope: held at 10x, a phone pose 3° away does not move the view",
    h0.hold && h1.hold && h1.az === h0.az && h1.alt === h0.alt && Math.abs(turned) > 2,
    `view ${h0.az.toFixed(4)}°, ${h0.alt.toFixed(4)}° -> ${h1.az.toFixed(4)}°, ${h1.alt.toFixed(4)}°; the phone turned ${turned.toFixed(2)}°`);
  check("no script errors on the page (online)", page.errors.length === 0, page.errors.slice(0, 2).join(" | "));

  // ---- layers: one at a time, and the back button closes the top one instead of leaving the compass ----
  const layers = await page.eval(`(async () => {
    const $ = (id) => document.getElementById(id), wait = () => new Promise((ok) => setTimeout(ok, 300));
    const shown = () => ["searchPane", "learnMenu", "learnPanel", "info"].filter((id) => !$(id).hidden).join(",");
    const out = {};
    $("learnBtn").click(); await wait(); $("searchBtn").click(); await wait(); out.one = shown();
    history.back(); await wait(); out.afterBack = shown(); out.page = location.pathname;
    WanderersLearn.open("time"); await wait(); $("infoBtn").click(); await wait(); out.stack = shown();
    history.back(); await wait(); out.back1 = shown(); history.back(); await wait(); out.back2 = shown();
    $("infoBtn").click(); await wait(); $("infoClose").click(); await wait(); out.closed = shown(); out.state = history.state;
    // a layer that opens in the same task as another one closes (menu -> mode, Details -> Webb) still owns an entry
    $("learnBtn").click(); await wait(); $("learnMenu").querySelector('[data-mode="log"]').click(); await wait();
    out.mode = shown(); out.modeEntry = !!(history.state && history.state.layer);
    history.back(); await wait(); out.modeBack = shown(); out.modePage = location.pathname;
    $("details").hidden = false; await wait(); $("details").hidden = true; $("webb").hidden = false; await wait();
    out.webbEntry = !!(history.state && history.state.layer);
    history.back(); await wait(); out.webbBack = $("webb").hidden; out.webbPage = location.pathname; out.endState = history.state;
    return out; })()`);
  check("layers: the Learn menu closes when the search opens", layers.one === "searchPane", JSON.stringify(layers));
  check("layers: back closes the search and stays on the compass", layers.afterBack === "" && /compass\.html$/.test(layers.page), JSON.stringify(layers));
  check("layers: a sheet over the time machine closes first, then the time machine",
    layers.stack === "learnPanel,info" && layers.back1 === "learnPanel" && layers.back2 === "", JSON.stringify(layers));
  check("layers: a sheet closed by × leaves no history entry behind", layers.closed === "" && layers.state === null, JSON.stringify(layers));
  check("layers: a mode picked from the Learn menu owns an entry; back closes it on the compass",
    layers.mode === "learnPanel" && layers.modeEntry && layers.modeBack === "" && /compass\.html$/.test(layers.modePage), JSON.stringify(layers));
  check("layers: Details -> Webb owns an entry; back closes Webb on the compass, with no entry left",
    layers.webbEntry && layers.webbBack && /compass\.html$/.test(layers.webbPage) && layers.endState === null, JSON.stringify(layers));

  // ---- 2. save the sky for places, through the info sheet; then remove one place ----
  // Basic for Seattle's latitude stays for part 3. Standard for Sydney's is saved, then removed again: that must
  // leave every Seattle picture in place. SHARP=1 also saves and removes Sharp for Seattle (about 690 pictures).
  await page.goto("sky=deep");
  await page.until(deepReady, 60000, "the photographs to load");
  await page.eval(`(document.getElementById("infoBtn").click(), true)`); await sleep(500);
  const cacheState = `(async () => {
    const urls = async (n) => (await caches.has(n)) ? (await (await caches.open(n)).keys()).map((k) => k.url) : [];
    const s = await urls("wanderers-sky-saved-v1"), a = await urls("wanderers-sky-v1");
    const man = [];
    if (await caches.has("wanderers-sky-saved-v1")) { const c = await caches.open("wanderers-sky-saved-v1");
      for (const u of s.filter((u) => Hips.isManifest(u))) man.push(await (await c.match(u)).json()); }
    return { msg: document.getElementById("saveMsg").textContent, saved: s, tiles: s.filter((u) => /Npix/.test(u)).length,
      both: s.filter((u) => a.includes(u)).length, places: man.map((m) => ({ lat: m.lat, order: m.order, n: m.urls.length, urls: m.urls })),
      list: [...document.querySelectorAll("#savedList li")].map((li) => li.textContent) };
  })()`;
  const saveFor = async (lat, order, label) => {
    const t = Date.now();
    await page.eval(`(document.getElementById("savePlace").value = "${lat}, 0", document.getElementById("savePlace").dispatchEvent(new Event("input")),
      document.querySelector('#saveSeg [data-order="${order}"]').click(), true)`);
    await sleep(800);
    const plan = await page.eval(`document.getElementById("savePlan").textContent`);
    await page.eval(`(document.getElementById("saveMsg").textContent = "", document.getElementById("saveGo").click(), true)`);   // not the last save's message
    await page.until(`/^(Saved for|.*could not|The archive)/.test(document.getElementById("saveMsg").textContent)`, 600000, `the ${label} save to end`);
    // the list is redrawn from the manifests after the save: wait until it has caught up
    await page.until(`(async () => { const c = await caches.open("wanderers-sky-saved-v1"); return (await c.keys()).filter((k) => Hips.isManifest(k.url)).length === document.querySelectorAll("#savedList li").length; })()`, 20000, "the saved list");
    const st = await page.eval(cacheState);
    report.saves.push({ label, lat, order, seconds: Math.round((Date.now() - t) / 1000), plan, msg: st.msg, tiles: st.tiles });
    check(`save ${label}: finished`, /^Saved for latitude/.test(st.msg), `${st.msg.slice(0, 60)} (${Math.round((Date.now() - t) / 1000)} s; ${plan.slice(0, 70)})`);
    return st;
  };
  report.saves = [];
  let st = await saveFor(47.6, 1, "Basic, 48° N");
  report.save = { tiles: st.tiles, files: st.saved.length, places: st.places.map((p) => ({ lat: p.lat, order: p.order, n: p.n })) };
  check("saved cache holds the 60 Basic tiles, the survey files, the Aladin script and the place's manifest", st.tiles === 60 && st.saved.length === 65, `${st.tiles} tiles, ${st.saved.length} files`);
  check("no saved picture is also kept as a recent one", st.both === 0, `${st.both} duplicates`);
  check("the place is listed from its manifest", st.places.length === 1 && st.places[0].order === 1 && Math.round(st.places[0].lat) === 48 && st.list.length === 1, JSON.stringify(st.list));
  // the archive reissues the survey: every saved picture is fetched again, in place (one is spoiled first, as proof)
  const renew = await page.eval(`(async () => {
    const base = Hips.CONFIG.surveys.visible.hosts[0], data = await caches.open(Hips.CONFIG.caches.pinned), stamp = Hips.releaseUrl(base);
    const saved = await caches.open("wanderers-sky-saved-v1"), tile = (await saved.keys()).map((k) => k.url).find((u) => /Npix\\d+\\.jpg$/.test(u));
    const size = async () => (await (await saved.match(tile)).blob()).size, files = async () => (await saved.keys()).length;
    await saved.put(tile, new Response("old"));
    const spoiled = await size(), before = await files();
    await data.put(stamp, new Response(JSON.stringify({ at: 0, release: "1999-01-01T00:00Z" })));
    await fetch(base + "/properties");
    let now = null;
    for (let i = 0; i < 480 && !(now && now.at && !now.savedDue); i++) { await new Promise((r) => setTimeout(r, 250)); const r = await data.match(stamp); now = r ? await r.json() : null; }
    return { spoiled, size: await size(), before, after: await files(), now };
  })()`);
  check("a reissued survey: the saved pictures are fetched again in place", renew.spoiled === 3 && renew.size > 1000 && renew.after === renew.before && !!renew.now && renew.now.savedDue === false,
    `spoiled tile ${renew.spoiled} → ${renew.size} bytes, ${renew.before} → ${renew.after} files, ${JSON.stringify(renew.now)}`);
  const seattle = st.places[0].urls;
  st = await saveFor(-33.9, 2, "Standard, 34° S");
  check("Standard, 34° S: about 190 tiles of its own on top", st.places.length === 2 && st.tiles > 200 && st.list.length === 2, `${st.tiles} tiles in all; ${st.list.join(" | ")}`);
  const sydney = st.places.find((p) => p.lat < 0);
  // remove the Sydney place with its own button
  await page.eval(`([...document.querySelectorAll("#savedList li")].find((li) => /34° S/.test(li.textContent)).querySelector("button").click(), true)`);
  await page.until(`document.querySelectorAll("#savedList li").length === 1`, 20000, "the list to show one place");
  st = await page.eval(cacheState);
  const lost = seattle.filter((u) => !st.saved.includes(u)), stay = sydney.urls.filter((u) => st.saved.includes(u) && !seattle.includes(u));
  check("remove one place: the other place keeps every picture", lost.length === 0 && st.places.length === 1 && Math.round(st.places[0].lat) === 48, `${lost.length} Seattle files lost`);
  check("remove one place: its own pictures are gone", stay.length === 0 && st.tiles === 60, `${stay.length} Sydney-only files left, ${st.tiles} tiles`);
  if (process.env.SHARP) {
    st = await saveFor(47.6, 3, "Sharp, 48° N");
    check("Sharp, 48° N: 924 tiles (orders 0 to 3)", st.tiles > 880 && st.places.length === 2, `${st.tiles} tiles`);
    await page.eval(`([...document.querySelectorAll("#savedList li")].find((li) => /Sharp/.test(li.textContent)).querySelector("button").click(), true)`);
    await page.until(`document.querySelectorAll("#savedList li").length === 1`, 60000, "the Sharp place to go");
    st = await page.eval(cacheState);
    check("remove Sharp: the Basic place for the same latitude is untouched", st.tiles === 60 && seattle.every((u) => st.saved.includes(u)), `${st.tiles} tiles`);
  }
  await page.close();

  // ---- 3. same profile; the archive, the CDNs and our own server are all unreachable (a cold open with no signal) ----
  await new Promise((ok) => server.close(ok));
  page = await launch([`--host-resolver-rules=${HOSTS_DOWN}`]);
  await page.goto("sky=eye&limit=dark");
  const cold = await page.until(`window.RealSky && !!RealSky.EYE.stars && !!RealSky.CON.list && !document.getElementById("ar").hidden`, 30000, "the page to open from the phone's own copy").then(() => true).catch((e) => e.message);
  check("no signal at all: the page opens and Eye has its stars and lines", cold === true, cold === true ? "" : cold);
  await page.eval(aim(165, 35)).catch(() => {}); await sleep(800);
  await page.shot("eye-cold-offline-phone.png");
  await page.goto("sky=deep");
  const ok3 = await page.until(deepReady, 40000, "Deep to start from saved pictures").then(() => true).catch((e) => e.message);
  check("offline with a saved place: Deep starts", ok3 === true, ok3 === true ? "" : `${ok3}; note: ${await page.eval(note).catch(() => "")}`);
  if (ok3 === true) {
    await page.until(`!!RealSky.EYE.stars`, 20000, "the star list");
    await page.eval(aim(90, 25));
    const r = await reg("offline, az 90 alt 25");
    await page.shot("deep-offline-phone.png");
    report.offline = { worst: r.worst, objects: r.stars.length };
  }
  await page.close();

  // ---- 4. a profile of its own, unreachable: Deep falls back to Eye ----
  await new Promise((ok) => server.listen(PORT, "127.0.0.1", ok));
  page = await launch([`--host-resolver-rules=${HOSTS_DOWN}`], PROFILE2);
  await page.goto("sky=deep");
  const t0 = Date.now();
  const ok4 = await page.until(`window.RealSky && RealSky.R.sky === "eye"`, 30000, "the fallback to Eye").then(() => true).catch((e) => e.message);
  const text = await page.eval(note).catch(() => "");
  check("offline with nothing saved: falls back to Eye and says so", ok4 === true && /not reachable/.test(text), `${((Date.now() - t0) / 1000).toFixed(1)} s; note: ${text}`);
  await page.shot("fallback-phone.png");
  await page.close();

  report.results = results;
  fs.writeFileSync(path.join(OUT, "browser-checks.json"), JSON.stringify(report, null, 1));
}

main().catch((e) => { check("run completed", false, e.message); })
  .finally(async () => { for (const b of browsers) b.kill(); await sleep(1500); server.close(); wipe(); process.exit(results.every((r) => r.ok) ? 0 : 1); });
