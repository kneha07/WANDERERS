/* WANDERERS Sky Compass: the real sky behind the AR view (docs/specs/sky-compass-real-sky.md).
 *   Eye:  the stars a person can see (data/skystars.json, from the star database), constellation lines and the
 *         planets, drawn in the camera's own projection. Not a photograph.
 *   Deep: survey photographs (DSS2 visible or 2MASS infrared) as HiPS tiles, drawn by Aladin Lite in the TAN
 *         projection, which is the projection of a camera, so the photographs sit under the drawn sky exactly.
 * Also: pictures kept on the phone (sw.js), "Save the sky for a place", and "Drag the sky" calibration.
 * compass.js calls RealSky.init() once and RealSky.draw() every frame, under its own markers. */
(function (root) {
  const $ = (id) => document.getElementById(id);
  const D2R = Math.PI / 180;
  const Q = new URLSearchParams(location.search);
  // Survey hosts, sizes, cache names and the Aladin address live in Hips.CONFIG, shared with sw.js.
  const SURVEYS = Object.fromEntries(Object.entries(Hips.CONFIG.surveys).map(([k, v]) => [k, { ...v, credit: SkyView.CREDITS[k === "visible" ? "deep" : k] }]));
  const surveyOf = (n) => SURVEYS[n] || SURVEYS.visible;
  const ALADIN_URL = Hips.CONFIG.aladin, CACHE_AUTO = Hips.CONFIG.caches.recent, CACHE_SAVED = Hips.CONFIG.caches.saved;
  const TILE_BYTES = Hips.CONFIG.surveys.visible.tile;
  const store = (k, v) => { try { v === undefined ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch {} };
  const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
  const pick = (k, ok, d) => (ok(Q.get(k)) ? Q.get(k) : d);

  const R = {
    sky: pick("sky", (v) => ["off", "eye", "deep"].includes(v), load("wanderers.sky", "eye")),
    limit: pick("limit", (v) => SkyView.LIMITS[v], load("wanderers.skyLimit", "dark")),
    survey: pick("survey", (v) => SURVEYS[v], load("wanderers.skySurvey", "visible")),
    lines: load("wanderers.skyLines", true), mix: load("wanderers.skyMix", 0.8), msg: "", calDrag: null,
  };
  const STILL = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;   // no slow shine on the lines
  let C = null;            // what compass.js gives: pose(), focal(), loc(), now(), camOn(), phoneSteers(), F, S, onStar(key), openSight()
  let LAST = null;         // the latest frame: pose, focal, size, time, place (for taps, the drag and the self-check)

  // ---------- the camera's projection (the same formula as compass.js) ----------
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm = (a) => { const n = Math.hypot(...a) || 1; return a.map((x) => x / n); };
  const vec = (az, alt) => [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
  function projector(P, f, W, H) {
    return (v) => { const z = dot(v, P.forward); if (z < 0.02) return null; return [W / 2 + (f * dot(v, P.right)) / z, H / 2 - (f * dot(v, P.up)) / z]; };
  }
  const unproject = (P, f, W, H, x, y) => norm(P.forward.map((c, i) => f * c + (x - W / 2) * P.right[i] + (H / 2 - y) * P.up[i]));
  // how far the screen's "up" leans from "towards the zenith", clockwise, in degrees
  function rollOf(P) {
    const fw = P.forward;
    let u0 = [-fw[2] * fw[0], -fw[2] * fw[1], 1 - fw[2] * fw[2]];
    if (Math.hypot(...u0) < 1e-6) u0 = vec(P.az, 0);
    u0 = norm(u0);
    const r0 = [fw[1] * u0[2] - fw[2] * u0[1], fw[2] * u0[0] - fw[0] * u0[2], fw[0] * u0[1] - fw[1] * u0[0]];
    return Math.atan2(dot(P.up, r0), dot(P.up, u0)) / D2R;
  }

  // ---------- Eye: stars, lines, planets ----------
  const EYE = { stars: null, cons: [], xyz: null, loading: false, failed: false, key: "", vecs: [] };
  function loadStars() {
    if (EYE.stars || EYE.loading) return;
    EYE.loading = true;
    fetch("data/skystars.json").then((r) => r.json()).then((d) => {
      EYE.xyz = new Float32Array(d.stars.length * 3);
      d.stars.forEach((s, i) => EYE.xyz.set(Sky.unit(s[0], s[1]), 3 * i));
      EYE.cons = d.meta.cons; EYE.stars = d.stars; EYE.key = ""; EYE.failed = false;
    }).catch(() => { EYE.failed = true; }).finally(() => { EYE.loading = false; });
  }
  // stars above the horizon down to a faintness: [east, north, up, mag, letter, row]
  function starsUp(now, L, mag) {
    const fr = Sky.frame(now, L.lat, L.lon), n = SkyView.countToLimit(EYE.stars, mag), out = [], a = EYE.xyz;
    for (let i = 0; i < n; i++) {
      const v = fr.toHorizon(a[3 * i], a[3 * i + 1], a[3 * i + 2]);
      if (v[2] < 0) continue;
      v.push(EYE.stars[i][2], EYE.stars[i][3], i); out.push(v);
    }
    return out;
  }
  const CON = { list: null, loading: false, key: "", figs: [] };
  function loadLines() {
    if (CON.list || CON.loading) return;
    CON.loading = true;
    fetch("data/constellations.json").then((r) => r.json()).then((d) => { CON.list = d.list; CON.key = ""; })
      .catch(() => {}).finally(() => { CON.loading = false; });
  }
  const PLANETS = { t: -1, list: [] };
  function planetsNow(now) {
    const t = Math.floor(now.getTime() / 60000);
    if (t !== PLANETS.t) { PLANETS.t = t; PLANETS.list = Sky.planets(now); }
    return PLANETS.list;
  }

  function drawEye(g, proj, now, L, f) {
    if (!EYE.stars) { loadStars(); return; }
    const key = `${R.limit}|${L.lat.toFixed(2)}|${L.lon.toFixed(2)}|${Math.floor(now.getTime() / 1000)}`;
    if (key !== EYE.key) { EYE.key = key; EYE.vecs = starsUp(now, L, SkyView.limitMag(R.limit)); }
    const zoom = Math.max(0.6, Math.min(1.6, f / 700));             // dots grow a little with a longer lens
    const fade = (C.camOn() ? 0.35 + 0.65 * R.mix : 1) * (1 - cover());   // the photographs fade the drawn stars out
    for (const s of EYE.vecs) {
      const q = proj(s); if (!q) continue;
      g.globalAlpha = SkyView.starAlpha(s[3]) * fade; g.fillStyle = SkyView.starColour(s[4]);
      g.beginPath(); g.arc(q[0], q[1], Math.max(0.7, SkyView.starRadius(s[3], 60) * 0.5 * zoom), 0, 7); g.fill();
    }
    g.globalAlpha = 1;
  }
  function drawLines(g, proj, now, L) {
    if (!CON.list) { loadLines(); return; }
    const key = `${L.lat.toFixed(2)}|${L.lon.toFixed(2)}|${Math.floor(now.getTime() / 1000)}`;
    if (key !== CON.key) {
      CON.key = key;
      const fr = Sky.frame(now, L.lat, L.lon);
      CON.figs = CON.list.map((c) => ({ name: c.name, at: fr.toHorizon(...Sky.unit(c.ra, c.dec)),
        strokes: c.lines.map((l) => { const v = []; for (let i = 0; i < l.length; i += 2) v.push(fr.toHorizon(...Sky.unit(l[i], l[i + 1]))); return v; }) }));
    }
    // the lines shine: a soft cyan glow under a brighter line, slowly brightening and dimming (an 8 s cycle)
    const shine = STILL ? 0.5 : 0.5 + 0.5 * Math.sin(now.getTime() / 8000 * 2 * Math.PI);
    g.save(); g.shadowColor = "rgba(124,196,255,.9)"; g.shadowBlur = 5 + 5 * shine;
    g.strokeStyle = `rgba(150,210,255,${(0.42 + 0.18 * shine).toFixed(3)})`; g.lineWidth = 1.3; g.beginPath();
    for (const c of CON.figs) for (const st of c.strokes) for (let i = 1; i < st.length; i++) {
      if (st[i - 1][2] < 0 && st[i][2] < 0) continue;              // under the ground
      const a = proj(st[i - 1]), b = proj(st[i]); if (!a || !b) continue;
      g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]);
    }
    g.stroke(); g.restore();
    g.fillStyle = "rgba(150,210,255,.75)"; g.font = "600 10px 'JetBrains Mono', monospace"; g.textAlign = "center"; g.textBaseline = "middle";
    for (const c of CON.figs) { if (c.at[2] < 0) continue; const q = proj(c.at); if (q) g.fillText(c.name.toUpperCase(), q[0], q[1]); }
    g.textAlign = "left";
  }
  // ---------- galaxies: well-known galaxies, at their true size and tilt, coloured by type ----------
  // Positions J2000 (deg), size as major x minor axis (arcmin), PA = position angle of the major axis (deg, from north
  // through east). Sources: the Messier and NGC catalogues (NED / SIMBAD values, rounded). Distances in light-years.
  const GALAXIES = [
    ["Andromeda Galaxy", "M31", "spiral", 10.6847, 41.2690, 190, 60, 35, 2.5e6],
    ["Triangulum Galaxy", "M33", "spiral", 23.4621, 30.6602, 73, 45, 23, 2.7e6],
    ["Large Magellanic Cloud", "LMC", "irregular", 80.894, -69.756, 645, 550, 170, 1.6e5],
    ["Small Magellanic Cloud", "SMC", "irregular", 13.187, -72.829, 320, 205, 45, 2.0e5],
    ["Whirlpool Galaxy", "M51", "spiral", 202.4696, 47.1952, 11, 7, 163, 2.3e7],
    ["Bode's Galaxy", "M81", "spiral", 148.8882, 69.0653, 27, 14, 157, 1.2e7],
    ["Cigar Galaxy", "M82", "starburst", 148.9685, 69.6797, 11, 5, 65, 1.2e7],
    ["Pinwheel Galaxy", "M101", "spiral", 210.8023, 54.3489, 29, 27, 0, 2.1e7],
    ["Sombrero Galaxy", "M104", "spiral", 189.9976, -11.6231, 9, 4, 90, 3.1e7],
    ["Centaurus A", "NGC 5128", "elliptical", 201.3651, -43.0191, 26, 20, 35, 1.2e7],
    ["Sculptor Galaxy", "NGC 253", "spiral", 11.888, -25.2883, 27, 7, 52, 1.1e7],
    ["Virgo A", "M87", "elliptical", 187.7059, 12.3911, 8, 6, 0, 5.4e7],
    ["Southern Pinwheel", "M83", "spiral", 204.2538, -29.8658, 13, 12, 0, 1.5e7],
    ["Sunflower Galaxy", "M63", "spiral", 198.9555, 42.0293, 13, 7, 104, 2.9e7],
    ["Black Eye Galaxy", "M64", "spiral", 194.1821, 21.6827, 10, 5, 115, 1.7e7],
    ["Milky Way centre", "Sgr A*", "our galaxy", 266.4168, -29.0078, 60, 30, 58, 2.6e4],
  ].map(([name, id, type, ra, dec, a, b, pa, ly]) => ({ name, id, type, ra, dec, a, b, pa, ly }));
  const GAL_COLOR = { spiral: [170, 200, 255], elliptical: [255, 214, 150], irregular: [255, 170, 210], starburst: [255, 160, 130], "our galaxy": [255, 236, 200] };
  const GAL_KIND = { spiral: "A spiral galaxy", elliptical: "An elliptical galaxy", irregular: "An irregular dwarf galaxy", starburst: "A starburst galaxy: new stars form very fast", "our galaxy": "The centre of our own galaxy, the Milky Way, with its black hole Sagittarius A*" };
  const lyText = (ly) => (ly >= 1e6 ? `${(ly / 1e6).toFixed(ly < 1e7 ? 1 : 0)} million` : `${Math.round(ly / 1000)},000`) + " light-years";
  // screen place, half axes (px) and tilt of one galaxy; null when it is behind the view
  function galaxyOnScreen(gx, proj, now, L, f) {
    const s = Sky.observe(gx, now, L.lat, L.lon), q = proj(vec(s.az, s.alt)); if (!q) return null;
    const n = Sky.observe({ ra: gx.ra, dec: Math.min(89.9, gx.dec + 0.2) }, now, L.lat, L.lon), qn = proj(vec(n.az, n.alt));
    const north = qn ? Math.atan2(qn[0] - q[0], -(qn[1] - q[1])) : 0, px = f * Math.PI / 180 / 60;   // px per arcmin
    return { q, alt: s.alt, rx: Math.max(5, gx.a / 2 * px), ry: Math.max(2.5, gx.b / 2 * px), rot: north - gx.pa * Math.PI / 180 };
  }
  function drawGalaxies(g, proj, now, L, f) {
    g.font = "600 11px 'Space Grotesk', sans-serif"; g.textBaseline = "middle"; g.textAlign = "left";
    for (const gx of GALAXIES) {
      const o = galaxyOnScreen(gx, proj, now, L, f); if (!o || o.alt < -2) continue;
      const [r, gg, b] = GAL_COLOR[gx.type];
      if (R.sky === "eye") {   // a soft glowing ellipse; in Deep the photograph shows the real galaxy, so only an outline
        g.save(); g.translate(o.q[0], o.q[1]); g.rotate(o.rot - Math.PI / 2); g.scale(1, o.ry / o.rx);
        const grad = g.createRadialGradient(0, 0, 0, 0, 0, o.rx);
        grad.addColorStop(0, `rgba(255,255,255,.95)`); grad.addColorStop(0.12, `rgba(${r},${gg},${b},.8)`); grad.addColorStop(0.45, `rgba(${r},${gg},${b},.38)`); grad.addColorStop(1, `rgba(${r},${gg},${b},0)`);   // a white core, then the colour of its type, fading out
        g.fillStyle = grad; g.beginPath(); g.arc(0, 0, o.rx, 0, 7); g.fill(); g.restore();
      }
      g.save(); g.strokeStyle = `rgba(${r},${gg},${b},.55)`; g.lineWidth = 1; g.setLineDash([3, 3]);
      g.beginPath(); g.ellipse(o.q[0], o.q[1], o.rx + 3, o.ry + 3, o.rot - Math.PI / 2, 0, 7); g.stroke(); g.restore();
      g.fillStyle = `rgba(${r},${gg},${b},.95)`; g.fillText(gx.name, o.q[0] + o.rx * 0.7 + 8, o.q[1] - 4);
    }
    g.textAlign = "left";
  }
  function galaxyCard(gx, now, L) {
    const a = Math.round(Sky.observe(gx, now, L.lat, L.lon).alt);
    const size = gx.a >= 60 ? `${(gx.a / 60).toFixed(1)}° across` : `${gx.a}′ across`;
    return { kind: "galaxy", title: `${gx.name} (${gx.id})`, lines: [`${GAL_KIND[gx.type]}, ${lyText(gx.ly)} away.`,
      `${size} in our sky (the full Moon is 0.5°). ${a >= 0 ? `${a}° above the horizon now.` : "Below the horizon now."}`,
      gx.ly > 1e6 ? `The light you see left it about ${lyText(gx.ly).replace(" light-years", " years")} ago.` : "Position: Messier / NGC catalogues."] };
  }

  function drawPlanets(g, proj, now, L) {
    g.font = "600 12px 'Space Grotesk', sans-serif"; g.textBaseline = "middle"; g.textAlign = "left";
    for (const pl of planetsNow(now)) {
      const s = Sky.observe(pl, now, L.lat, L.lon), q = proj(vec(s.az, s.alt)); if (!q) continue;
      g.fillStyle = s.alt < 0 ? "rgba(160,170,190,.45)" : "#ffe9b0";
      g.beginPath(); g.arc(q[0], q[1], 4.5, 0, 7); g.fill(); g.fillText(pl.name, q[0] + 8, q[1]);
    }
  }

  // ---------- Deep: survey photographs under the canvas ----------
  // retryAt: no new start before this time (30 s after a failed one). failed: the last start failed (for the note).
  // op: the opacity last written to #skyDeep, or "hidden".
  const DEEP = { state: "idle", aladin: null, last: null, base: null, survey: null, A: null, retryAt: 0, failed: false, op: null };
  async function pickHost(name) {
    for (const h of surveyOf(name).hosts) {
      if (await fetch(h + "/properties", { signal: AbortSignal.timeout(6000) }).then((r) => r.ok).catch(() => false)) return h;
    }
    throw new Error("archive");
  }
  // Every survey start goes through loadSurvey: the first start and every switch of survey. It finds a host that
  // answers, then runs `more` (the first start loads the Aladin script), and resolves to [host, more's result]. A start
  // that fails, or hangs for 20 s, rejects, and no automatic start comes for 30 s, so a failure while zoomed in does not
  // retry every frame. A hung start that answers late is ignored: the race is already over.
  async function loadSurvey(name, more = async () => null) {
    let late;
    try {
      return await Promise.race([(async () => [await pickHost(name), await more()])(),
        new Promise((ok, no) => { late = setTimeout(() => no(new Error("timeout")), 20000); })]);
    } catch (e) { DEEP.retryAt = Date.now() + 30000; throw e; }
    finally { clearTimeout(late); }
  }
  async function startDeep() {
    if (DEEP.state !== "idle" || Date.now() < DEEP.retryAt) return;
    const survey = R.survey;
    DEEP.state = "loading"; note();
    try {
      const [base, A] = await loadSurvey(survey, async () => { const A = (await import(ALADIN_URL)).default; await A.init; return A; });
      DEEP.base = base; DEEP.survey = survey; DEEP.A = A;
      // log: false. By default Aladin Lite reports this page's full address to a CDS logging server on start.
      DEEP.aladin = A.aladin("#skyDeep", { survey: base, projection: "TAN", fov: 60, cooFrame: "ICRSd", log: false,
        showReticle: false, showLayersControl: false, showGotoControl: false, showFullscreenControl: false, showCooGridControl: false,
        showSimbadPointerControl: false, showProjectionControl: false, showFrame: false, showZoomControl: false, showCooLocation: false,
        showFov: false, showStatusBar: false, showShareControl: false, showContextMenu: false, showSettingsControl: false });
      DEEP.aladin.setBaseImageLayer(A.imageHiPS(base, { name: survey, imgFormat: "jpeg" }));
      DEEP.state = "ready"; DEEP.last = null; DEEP.failed = false; note();
    } catch {
      // Any failure on the way (the probe, the script, Aladin itself, the first layer) waits 30 s, so a browser
      // without WebGL2 does not build Aladin every frame. A half-built Aladin is removed: the next try starts fresh.
      DEEP.state = "idle"; DEEP.failed = true; DEEP.retryAt = Date.now() + 30000;
      DEEP.aladin = null; $("skyDeep").replaceChildren();
      if (R.sky === "deep") setSky("eye", "Sky photographs are not reachable. Showing the Eye view.");
    }
  }
  async function setSurvey(name) {
    R.survey = SURVEYS[name] ? name : "visible"; store("wanderers.skySurvey", R.survey); setSky(R.sky);
    if (DEEP.state !== "ready" || DEEP.survey === R.survey) return;
    const want = R.survey;
    DEEP.state = "loading"; note();
    try {
      const [base] = await loadSurvey(want);
      DEEP.aladin.setBaseImageLayer(DEEP.A.imageHiPS(base, { name: want, imgFormat: "jpeg" }));
      DEEP.base = base; DEEP.survey = want; DEEP.state = "ready"; DEEP.last = null; note();
    } catch {
      DEEP.state = "ready";                          // the old photographs are still on screen
      R.survey = DEEP.survey; store("wanderers.skySurvey", R.survey);
      setSky(R.sky, `The ${want} photographs are not reachable. Kept the ${DEEP.survey} ones.`);
    }
  }
  // Aladin's box is the whole screen. TAN with focal length f: the full width is 2·atan(W / 2f).
  // setRotation takes MINUS the position angle of the screen's "up" (measured 2026-11-14 in the radar version).
  function syncDeep(P, f, W, H, now, L) {
    if (DEEP.state === "idle") startDeep();
    if (DEEP.state !== "ready") return;
    if (DEEP.survey !== R.survey) { setSurvey(R.survey); return; }
    const c = Sky.unobserve(P.az, P.alt, now, L.lat, L.lon), rot = Sky.zenithAngle(P.az, P.alt, now, L.lat, L.lon) - rollOf(P);
    const fov = (2 * Math.atan(W / 2 / f)) / D2R, last = DEEP.last;
    // Skip only a change too small to see: the centre moves under 0.25 px, the scale under 1e-4, and the turn moves
    // a screen corner under 0.25 px. Limits in pixels, not degrees, so they hold at every zoom (300x: 1 deg = 3827 px).
    if (last && Math.abs(last.fov - fov) < 1e-4 * fov && Math.abs(((rot - last.rot + 540) % 360) - 180) < 0.25 / Math.hypot(W / 2, H / 2) / D2R &&
        Math.hypot((c.ra - last.c.ra) * Math.cos(c.dec * D2R), c.dec - last.c.dec) < 0.25 / (f * Math.tan(D2R))) return;
    DEEP.last = { c, rot, fov };
    DEEP.aladin.setFoV(fov); DEEP.aladin.gotoRaDec(c.ra, c.dec); DEEP.aladin.setRotation(-rot);
  }

  // ---------- the telescope view: zooming in fades the photographs in, in every sky mode ----------
  // The amount t is 0 at 3x and 1 at 6x. It never changes the user's own choice (R.sky, R.mix, R.survey).
  const scope = () => Math.max(0, Math.min(1, (C.S.zoom - 3) / 3));
  // Offline the telescope photographs are not shown (only the few saved orders would load, so the view went black):
  // the dark backdrop and the drawn stars stay. Deep keeps its photographs: they can come from a saved place.
  const online = () => navigator.onLine !== false;
  // How much of the view the photographs cover: compass.js fades its dark backdrop by it, drawEye its stars.
  const cover = () => (DEEP.state === "ready" ? (R.sky === "deep" ? 1 : online() ? scope() : 0) : 0);
  // The photographs are wanted in Deep, and from 2x (started early, so they are ready by 3x; on mobile data or with
  // Save-Data on, from 3x, so nothing unseen is fetched). Their opacity is set here every frame, written to the page
  // only when it changes. Aladin must not start in a hidden box, so the box stays shown (at opacity 0 below 3x) while
  // wanted or loading.
  function deepFrame(P, f, W, H, now, L) {
    const net = navigator.connection, from = net && (net.saveData || net.type === "cellular") ? 3 : 2;
    const want = R.sky === "deep" || (online() && C.S.zoom >= from), t = scope();
    const op = R.sky === "deep" ? (C.camOn() ? R.mix + (1 - R.mix) * t : 1) : online() ? t : 0;
    const key = want || DEEP.state === "loading" ? op : "hidden";
    if (key !== DEEP.op) { DEEP.op = key; $("skyDeep").hidden = key === "hidden"; $("skyDeep").style.opacity = op; }
    if (want) syncDeep(P, f, W, H, now, L);
  }

  // ---------- one frame, called by compass.js before its own markers ----------
  function draw(g, P, f, W, H, now, L) {
    LAST = { P, f, W, H, now, L };
    deepFrame(P, f, W, H, now, L);
    note();
    if (R.sky === "off") return;
    const proj = projector(P, f, W, H);
    if (R.lines) drawLines(g, proj, now, L);
    drawGalaxies(g, proj, now, L, f);
    if (R.sky === "eye") drawEye(g, proj, now, L, f);
    drawPlanets(g, proj, now, L);
  }

  // ---------- controls ----------
  function seg(id, attr, value) { $(id).querySelectorAll("button").forEach((b) => { const on = b.dataset[attr] === String(value); b.classList.toggle("on", on); b.setAttribute("aria-checked", on); }); }
  function setSky(mode, msg) {
    R.sky = mode; R.msg = msg || ""; store("wanderers.sky", mode);
    seg("skySeg", "sky", mode); seg("limitSeg", "limit", R.limit); seg("surveySeg", "survey", R.survey);
    $("limitSeg").hidden = mode !== "eye"; $("surveySeg").hidden = mode !== "deep";
    $("linesBtn").hidden = mode === "off"; $("linesBtn").classList.toggle("on", R.lines); $("linesBtn").setAttribute("aria-pressed", R.lines);
    if (mode !== "off") { loadStars(); if (R.lines) loadLines(); }   // Deep needs the star list too, for taps
    if (mode === "deep") DEEP.retryAt = 0;                           // choosing Deep tries the archive again at once
    $("mixWrap").hidden = !C.camOn() || mode === "off";
    $("mix").value = Math.round(R.mix * 100);
    DEEP.last = null; DEEP.op = null; NOTE = ""; note();              // the next frame sets the photographs' opacity
  }
  let NOTE = "", PILL = null;
  // The note always names what is on screen. Zoomed in, it names the survey, says it is an archive photograph,
  // and says when the direction is only approximate (no sight check, no snap to a target).
  function note() {
    const F = C.F, S = C.S, t = scope(), pt = SkyView.pointing({ haveSensor: S.sensors, accuracy: F.compassAccuracy, calibrated: !!F.compassFrozen });
    const loading = DEEP.state === "loading" && (S.zoom >= 3 ? "Loading telescope photographs… " : R.sky === "deep" ? "Loading sky photographs… " : "");
    const state = loading || (R.sky === "eye" && EYE.failed ? "The star list could not be loaded. " : "");
    const scoped = t > 0 && DEEP.state === "ready" && (R.sky === "deep" || online()), approx = scoped && S.sensors && !F.compassFrozen && !S.snapped;
    const text = [R.msg,
      scoped ? `Telescope view: ${surveyOf(R.survey).name}. Archive photograph, not live.`
        : (state + (R.sky === "deep" ? `Background: ${surveyOf(R.survey).name}. ` : "") + SkyView.LABELS[R.sky]).trim(),
      approx && "Your compass is good to a few degrees, so this is near where you point, not exactly it.",
      // one message per problem: with no connection, that is the reason
      t > 0 && (!online() ? (R.sky === "deep" ? "No connection: no finer photographs." : "No connection: telescope photographs are not available.")
        : DEEP.failed && "Telescope photographs are not reachable now."),
      !approx && pt.text].filter(Boolean).join(" · ");                 // one accuracy claim only
    const pill = cover() > 0;                        // on the photographs: a dark pill keeps the note readable
    if (pill !== PILL) { PILL = pill; $("skyNote").classList.toggle("on-photo", pill); }
    const key = text + pt.needsCal;
    if (key === NOTE) return;
    NOTE = key;
    const el = $("skyNote"); el.textContent = text;
    if (pt.needsCal) { const b = document.createElement("button"); b.textContent = "Sight check"; b.onclick = C.openSight; el.append(" ", b); }
  }

  // ---------- taps: a planet, the Moon or the Sun gets a small card; a star opens the star sheet ----------
  function pickAt(x, y) {
    if (!LAST) return null;
    const { P, f, W, H, now, L } = LAST, proj = projector(P, f, W, H), reach = 22;
    const t = C.targetAt && C.targetAt(x, y);   // a WANDERERS target (the bracketed ones) wins: it is what the user aimed for
    if (t) return { kind: "target", title: t.name, target: t };
    const off = (o) => { const s = Sky.observe(o, now, L.lat, L.lon), q = proj(vec(s.az, s.alt)); return q ? Math.hypot(q[0] - x, q[1] - y) : 1e9; };
    const where = (o) => { const a = Math.round(Sky.observe(o, now, L.lat, L.lon).alt); return a >= 0 ? `${a}° above the horizon now.` : "Below the horizon now."; };
    for (const b of [{ name: "Moon", body: "moon" }, { name: "Sun", body: "sun" }]) if (off(b) < reach) return { kind: "body", title: b.name, lines: [where(b), "Its place is worked out for this moment, not taken from a picture."] };
    for (const gx of GALAXIES) {
      const o = galaxyOnScreen(gx, proj, now, L, f); if (!o) continue;
      if (Math.hypot(o.q[0] - x, o.q[1] - y) < Math.max(18, Math.min(o.rx, 120))) { var galaxyHit = galaxyCard(gx, now, L); break; }
    }
    for (const pl of planetsNow(now)) if (off(pl) < reach) return { kind: "planet", title: pl.name, lines: ["A planet. " + where(pl), "Its place is worked out from JPL's orbital elements, not taken from a picture."] };
    if (galaxyHit && R.sky !== "off") return galaxyHit;   // after the Moon, Sun and planets, before single stars
    if (EYE.stars && R.sky !== "off") {
      let best = null;
      for (const s of starsUp(now, L, R.sky === "eye" ? SkyView.limitMag(R.limit) : 6.5)) {
        const q = proj(s); if (!q) continue;
        if (Math.hypot(q[0] - x, q[1] - y) < 18 && (!best || s[3] < best[3])) best = s;   // the brightest one within reach
      }
      if (best) { const row = EYE.stars[best[5]], card = SkyView.starCard(row, EYE.cons); return { kind: "star", key: card.key, title: card.title, lines: card.lines, ra: row[0], dec: row[1] }; }
    }
    return null;
  }
  function showCard(pk) {
    $("skyCard").hidden = !pk;
    if (!pk) return;
    $("skyCardName").textContent = pk.title;
    $("skyCardLines").replaceChildren(...pk.lines.map((t) => { const p = document.createElement("p"); p.textContent = t; return p; }));
  }
  function onTap(x, y) {
    const pk = pickAt(x, y);
    if (pk && pk.kind === "target") { showCard(null); C.onTarget(pk.target); }
    else if (pk && pk.kind === "star") { showCard(null); C.onStar(pk); } else showCard(pk);
    return pk;
  }

  // ---------- drag the sky: the sky point under the finger stays under the finger ----------
  // With motion sensors it moves the sight-check offsets (F.fineAz, F.fineAlt), like tapping a landmark does;
  // without them, or while the view is held (zoomed in), it aims the view. A small 2-by-2 Newton solve, so it is
  // exact whatever the phone's roll.
  // The pose after turning by A degrees of azimuth (about the vertical) and then tilting by T degrees about the
  // camera's right axis: what F.fineAz and F.fineAlt do in orient.js, and what a change of S.manual does.
  function turned(P, A, T) {
    const ca = Math.cos(A * D2R), sa = Math.sin(A * D2R), ct = Math.cos(T * D2R), st = Math.sin(T * D2R);
    const rz = (v) => [v[0] * ca + v[1] * sa, -v[0] * sa + v[1] * ca, v[2]];      // clockwise seen from above
    const f0 = rz(P.forward), u0 = rz(P.up);
    const fw = norm(f0.map((x, i) => x * ct + u0[i] * st)), up = norm(u0.map((x, i) => x * ct - f0[i] * st));
    const right = [fw[1] * up[2] - fw[2] * up[1], fw[2] * up[0] - fw[0] * up[2], fw[0] * up[1] - fw[1] * up[0]];
    return { forward: fw, up, right };
  }
  // Find (A, T) that draws the grabbed point v at the finger (tx, ty): a 2-by-2 Newton solve on the modelled pose.
  // The motion sensors are smoothed, so the real pose catches up a few frames later.
  function follow(g, tx, ty) {
    const W = innerWidth, H = innerHeight, f = C.focal(W, H), at = (A, T) => projector(turned(g.P0, A, T), f, W, H)(g.v), h = 0.05;
    let A = g.A, T = g.T;
    for (let i = 0; i < 6; i++) {
      const q0 = at(A, T); if (!q0) break;
      const ex = tx - q0[0], ey = ty - q0[1]; if (Math.hypot(ex, ey) < 0.05) break;
      const qa = at(A + h, T), qb = at(A, T + h); if (!qa || !qb) break;
      const a = (qa[0] - q0[0]) / h, c = (qa[1] - q0[1]) / h, b = (qb[0] - q0[0]) / h, d = (qb[1] - q0[1]) / h, det = a * d - b * c;
      if (Math.abs(det) < 1e-9) break;
      const lim = (x) => Math.max(-20, Math.min(20, x));
      A += lim((d * ex - b * ey) / det); T += lim((a * ey - c * ex) / det);
    }
    g.A = A; g.T = T;
    if (C.phoneSteers()) { C.F.fineAz = Orient.wrap180(g.fine[0] + A); C.F.fineAlt = Math.max(-30, Math.min(30, g.fine[1] + T)); }
    else { const m = C.S.manual; m.az = (g.manual.az + A + 720) % 360; m.alt = Math.max(-85, Math.min(85, g.manual.alt + T)); }
  }
  function startDrag() {
    if (R.sky === "off") setSky("eye");
    R.calDrag = { az: C.F.fineAz, alt: C.F.fineAlt, frozen: C.F.compassFrozen, manual: { ...C.S.manual } };
    $("north").hidden = true; $("dragBar").hidden = false;
  }
  function endDrag(keep) {
    const b = R.calDrag; R.calDrag = null; $("dragBar").hidden = true;
    if (!b) return;
    if (!keep) { C.F.fineAz = b.az; C.F.fineAlt = b.alt; C.F.compassFrozen = b.frozen; Object.assign(C.S.manual, b.manual); return; }
    if (C.phoneSteers()) C.F.compassFrozen = true;      // the sky the user sees is the truth now, as after a sight check
  }

  // ---------- pictures kept on the phone, and "Save the sky for a place" ----------
  const cacheOk = "caches" in window;
  async function cacheStats(name) {
    if (!cacheOk || !(await caches.has(name))) return { n: 0, bytes: 0 };
    const c = await caches.open(name), keys = (await c.keys()).filter((k) => /\.jpg$/.test(k.url));
    let bytes = 0;
    for (const k of keys) { const r = await c.match(k); bytes += +(r && r.headers.get("content-length")) || TILE_BYTES; }
    return { n: keys.length, bytes };
  }
  // What sw.js recorded for the survey on screen: { release, at } (its issue date, and when that was last checked).
  async function surveyVersion() {
    if (!cacheOk || !(await caches.has(Hips.CONFIG.caches.pinned))) return null;
    const c = await caches.open(Hips.CONFIG.caches.pinned);
    for (const h of [DEEP.survey === R.survey && DEEP.base, ...surveyOf(R.survey).hosts].filter(Boolean)) {
      const r = await c.match(Hips.releaseUrl(h)), v = r ? await r.json() : null;
      if (v && v.release) return v;
    }
    return null;
  }
  const DETAIL = { 1: "Basic", 2: "Standard", 3: "Sharp" };
  const planFor = (lat, order, survey) => { const v = surveyOf(survey); return Hips.plan(v.hosts[0], lat, order, v); };
  const SAVE = { order: 2, running: false, stop: false };
  // The saved places, read from their manifests. Pictures in the saved cache that no manifest lists (a save from
  // before manifests, or one that was stopped) are shown as one extra entry that can be removed too.
  async function savedPlaces() {
    if (!cacheOk || !(await caches.has(CACHE_SAVED))) return { places: [], loose: { n: 0, bytes: 0 } };
    const c = await caches.open(CACHE_SAVED), keys = await c.keys(), places = [];
    for (const k of keys) if (Hips.isManifest(k.url)) { const r = await c.match(k); if (r) places.push({ ...(await r.json()), manifest: k.url }); }
    const listed = new Set(places.flatMap((p) => p.urls)), loose = keys.filter((k) => /\.jpg$/.test(k.url) && !listed.has(k.url));
    let bytes = 0;
    for (const k of loose) { const r = await c.match(k); bytes += +(r && r.headers.get("content-length")) || TILE_BYTES; }
    places.sort((a, b) => b.lat - a.lat || a.order - b.order);
    return { places, loose: { n: loose.length, bytes, urls: loose.map((k) => k.url) } };
  }
  async function removePlace(i) {
    const { places, loose } = await savedPlaces(), c = await caches.open(CACHE_SAVED);
    if (i === "loose") { for (const u of loose.urls) await c.delete(u); }
    else {
      const gone = places[i]; if (!gone) return;
      for (const u of Hips.orphans(gone, places.filter((_, k) => k !== i))) await c.delete(u);
      await c.delete(gone.manifest);
    }
    $("saveMsg").textContent = ""; renderSaved();
  }
  async function renderSaved() {
    if (!cacheOk) { $("savedRow").textContent = "This browser cannot keep pictures on the device."; $("saveGo").disabled = true; return; }
    const [auto, saved, mine, ver] = await Promise.all([cacheStats(CACHE_AUTO), cacheStats(CACHE_SAVED), savedPlaces(), surveyVersion()]);
    const day = (iso, year) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year });
    $("savedRow").textContent = `Recent: ${auto.n ? `${auto.n} pictures, ${SkyView.fmtBytes(auto.bytes)} (cleared after 7 days)` : "none"}. ` +
      `Saved: ${saved.n ? `${saved.n} pictures, ${SkyView.fmtBytes(saved.bytes)}` : "none"}.` +
      (ver ? ` The archive last updated its ${R.survey} photographs on ${day(ver.release, "numeric")}. Checked for newer ones on ${day(ver.at)}, at most once a day.` : "");
    const rows = mine.places.map((p, i) => [i, `Latitude ${SkyView.fmtLat(p.lat)}, ${DETAIL[p.order]}${p.survey === "infrared" ? ", infrared" : ""}, ` +
      `${p.tiles} pictures, saved ${day(p.savedAt)}`]);
    if (mine.loose.n) rows.push(["loose", `${mine.loose.n} pictures from a save that did not finish (${SkyView.fmtBytes(mine.loose.bytes)})`]);
    $("savedList").replaceChildren(...rows.map(([i, text]) => {
      const li = document.createElement("li"), b = document.createElement("button");
      b.className = "btn ghost"; b.textContent = "Remove"; b.dataset.place = i; b.onclick = () => removePlace(i === "loose" ? "loose" : +i);
      li.append(text + " ", b); return li;
    }));
    $("clearAuto").disabled = !auto.n;
    seg("saveSeg", "order", SAVE.order);
    planSave();
  }
  function saveLat() {
    const t = $("savePlace").value.trim();
    if (!t) return C.loc().lat;
    const m = t.match(/-?\d+(?:\.\d+)?/);
    return m && Math.abs(+m[0]) <= 90 ? +m[0] : null;
  }
  async function planSave() {
    const lat = saveLat();
    if (lat == null) { $("savePlan").textContent = "Type a latitude between -90 and 90, or coordinates like 47.62, -122.35."; return null; }
    const plan = planFor(lat, SAVE.order, R.survey), est = navigator.storage && navigator.storage.estimate ? await navigator.storage.estimate().catch(() => null) : null;
    $("savePlan").textContent = `Latitude ${SkyView.fmtLat(lat)}, ${R.survey === "infrared" ? "Infrared" : "Visible"}: ${plan.tiles} pictures, about ${SkyView.fmtBytes(plan.bytes)}` +
      ` (${Math.round(Hips.skyShare(lat) * 100)}% of the whole sky). It also works anywhere near this latitude, on any night.` +
      (est && est.quota ? ` Free space here: ${SkyView.fmtBytes(Math.max(0, est.quota - (est.usage || 0)))}.` : "");
    return { lat, plan };
  }
  async function saveSky() {
    if (SAVE.running) return;
    const got = await planSave(); if (!got) return;
    const { lat, plan } = got, net = navigator.connection, survey = R.survey;
    if (net && (net.saveData || net.type === "cellular") && !SAVE.askedData) {   // ask once (a page dialog may be blocked)
      SAVE.askedData = true; $("saveMsg").textContent = `This uses about ${SkyView.fmtBytes(plan.bytes)} of mobile data. Press Save again to go ahead.`; return;
    }
    SAVE.running = true; SAVE.stop = false; $("saveGo").disabled = true; $("saveStop").hidden = false;
    const cache = await caches.open(CACHE_SAVED), urls = [ALADIN_URL, ...plan.urls], total = urls.length;
    let next = 0, done = 0, row = 0, halted = "";
    const failed = [], recent = await caches.open(CACHE_AUTO);
    const say = () => { $("saveMsg").textContent = `${done} of ${total} pictures`; };
    const worker = async () => {
      while (next < total && !SAVE.stop && !halted) {
        const u = urls[next++];
        try {
          if (!(await cache.match(u))) {
            const r = await fetch(u, { mode: "cors", credentials: "omit" });
            if (r.ok) await cache.put(u, r);
            else if (/Npix\d+\.jpg$/.test(u)) throw new Error(String(r.status));   // only the tiles are required
          }
          done++; row = 0; say();
        } catch { failed.push(u); if (++row >= 3) halted = "The archive is not answering. Your saved pictures are kept. Try again later."; }
      }
    };
    say();
    await Promise.all([1, 2, 3, 4].map(worker));
    if (failed.length && !halted && !SAVE.stop) { urls.push(...failed.splice(0)); row = 0; await Promise.all([1, 2].map(worker)); }
    await new Promise((r) => setTimeout(r, 400));   // a saved picture needs no "recent" copy from the service worker
    for (const u of urls) if (await cache.match(u)) await recent.delete(u, { ignoreVary: true });
    SAVE.running = false; $("saveGo").disabled = false; $("saveStop").hidden = true;
    if (done === total) {
      // The manifest is written last, so a place is listed only when all of its pictures are stored.
      const m = { lat, order: SAVE.order, survey, tiles: plan.tiles, savedAt: new Date().toISOString(), urls };
      await cache.put(Hips.manifestUrl(surveyOf(survey).hosts[0], lat, SAVE.order, survey), new Response(JSON.stringify(m), { headers: { "content-type": "application/json" } }));
      store("wanderers.skySaved");                    // the old list in localStorage, before manifests
      const kept = navigator.storage && navigator.storage.persist ? await navigator.storage.persist().catch(() => false) : false;
      $("saveMsg").textContent = `Saved for latitude ${SkyView.fmtLat(lat)}.` + (kept ? "" :
        " On an iPhone, add this page to the Home Screen, or Safari may delete saved pictures after 7 days without a visit.");
    } else $("saveMsg").textContent = halted || (SAVE.stop ? `Paused at ${done} of ${total}. Press Save to carry on from here.`
      : `${total - done} of ${total} pictures could not be fetched. Press Save to try those again.`);
    renderSaved();
  }

  // ---------- self-check: do the photographs and the canvas put stars on the same pixel? ----------
  function selfTest() {
    const { P, f, W, H, now, L } = LAST, proj = projector(P, f, W, H), box = $("skyDeep").getBoundingClientRect(), rows = [];
    const bright = EYE.stars ? EYE.stars.slice(0, 400).map((s) => ({ name: s[7] || "star", ra: s[0], dec: s[1] })) : [];
    for (const o of [...bright, ...planetsNow(now)]) {
      const s = Sky.observe(o, now, L.lat, L.lon), q = proj(vec(s.az, s.alt));
      // Near the horizon refraction lifts the drawn stars (by 0.5° at the horizon); the photographs cannot follow that.
      if (s.alt < 5) continue;
      if (!q || q[0] < 0 || q[0] > W || q[1] < 0 || q[1] > H) continue;
      const a = DEEP.aladin.world2pix(o.ra, o.dec); if (!a) continue;
      const ax = a[0] + box.left, ay = a[1] + box.top;
      rows.push({ name: o.name, canvas: [Math.round(q[0]), Math.round(q[1])], aladin: [Math.round(ax), Math.round(ay)], off: +Math.hypot(ax - q[0], ay - q[1]).toFixed(1) });
    }
    // compared: how many stars were measured. worst is 0 when none was, so every check must also ask for compared >= 1.
    return { worst: Math.max(0, ...rows.map((r) => r.off)), compared: rows.length, stars: rows, roll: +rollOf(P).toFixed(1), fov: DEEP.aladin.getFov(), base: DEEP.base,
      pxPerDeg: +(f * Math.tan(D2R)).toFixed(1) };
  }

  // ---------- wiring ----------
  let grab = null, tap = null;                       // the finger dragging the sky, and the press that may be a tap
  const cancelGesture = () => { grab = null; tap = null; };   // compass.js: a second finger came down (pinch to zoom)
  const cancelDrag = () => { grab = null; endDrag(false); };   // compass.js: hold mode starts or ends during Drag the sky
  function init(ctx) {
    C = ctx;
    $("skySeg").querySelectorAll("button").forEach((b) => (b.onclick = () => setSky(b.dataset.sky)));
    $("limitSeg").querySelectorAll("button").forEach((b) => (b.onclick = () => { R.limit = b.dataset.limit; store("wanderers.skyLimit", R.limit); EYE.key = ""; setSky(R.sky); }));
    $("surveySeg").querySelectorAll("button").forEach((b) => (b.onclick = () => setSurvey(b.dataset.survey)));
    $("linesBtn").onclick = () => { R.lines = !R.lines; store("wanderers.skyLines", R.lines); setSky(R.sky); };
    $("mix").oninput = (e) => { R.mix = e.target.value / 100; store("wanderers.skyMix", R.mix); };   // the next frame applies it
    $("skyCardClose").onclick = () => showCard(null);
    $("dragSky").onclick = startDrag;
    $("dragDone").onclick = () => endDrag(true);
    $("dragCancel").onclick = () => endDrag(false);
    $("saveGo").onclick = saveSky;
    $("saveStop").onclick = () => { SAVE.stop = true; };
    $("savePlace").oninput = planSave;
    $("saveSeg").querySelectorAll("button").forEach((b) => (b.onclick = () => { SAVE.order = +b.dataset.order; renderSaved(); }));
    $("clearAuto").onclick = async () => { await caches.delete(CACHE_AUTO); renderSaved(); };

    $("skyCredit").textContent = [SkyView.CREDITS.eye, SkyView.CREDITS.deep, SkyView.CREDITS.infrared].join(" ");

    // Gestures on the AR canvas. Registered before compass.js's own drag-to-look, so "drag the sky" can take them.
    const hud = $("hud");
    hud.addEventListener("pointerdown", (e) => {
      tap = { x: e.clientX, y: e.clientY, t: Date.now() };
      if (!R.calDrag || !LAST) return;
      e.stopImmediatePropagation(); hud.setPointerCapture(e.pointerId);
      const W = innerWidth, H = innerHeight;
      const P0 = C.pose();
      grab = { P0, A: 0, T: 0, v: unproject(P0, C.focal(W, H), W, H, e.clientX, e.clientY), fine: [C.F.fineAz, C.F.fineAlt], manual: { ...C.S.manual } };
    });
    hud.addEventListener("pointermove", (e) => { if (grab) { e.stopImmediatePropagation(); follow(grab, e.clientX, e.clientY); } });
    // a mouse over a star, planet or target shows its name; a click on it opens it (onTap)
    let hoverAt = null, hoverT = null;
    const hoverName = (x, y) => {
      const pk = R.calDrag ? null : pickAt(x, y), el = $("hoverName");
      el.hidden = !pk; hud.style.cursor = pk ? "pointer" : "";
      if (pk) { el.textContent = pk.title; el.style.left = `${x + 14}px`; el.style.top = `${y + 14}px`; }
    };
    hud.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse" || e.buttons) { $("hoverName").hidden = true; return; }
      hoverAt = { x: e.clientX, y: e.clientY };
      if (!hoverT) hoverT = setTimeout(() => { hoverT = null; hoverName(hoverAt.x, hoverAt.y); }, 40);   // at most 25 times a second
    });
    hud.addEventListener("pointerleave", () => { $("hoverName").hidden = true; hud.style.cursor = ""; });
    hud.addEventListener("pointerup", (e) => {
      if (grab) { e.stopImmediatePropagation(); grab = null; }
      if (tap && Date.now() - tap.t < 600 && Math.hypot(e.clientX - tap.x, e.clientY - tap.y) < 8) onTap(e.clientX, e.clientY);
      tap = null;
    });
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    setSky(R.sky);
  }

  const api = { GALAXIES, init, draw, cover, cancelGesture, cancelDrag, setSky, renderSaved, R, DEEP, EYE, CON, SAVE, selfTest, pickAt, onTap, rollOf, surveyOf, projector };
  root.RealSky = api;
})(window);
