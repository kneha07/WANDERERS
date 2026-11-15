/* WANDERERS Space Camera and Story Studio.
 *
 * Privacy: the camera, the compass/tilt sensors and location are each requested only when the person taps the button
 * that needs them. Photos are drawn into a canvas on this device (which also drops any EXIF/GPS data from an uploaded
 * file); nothing is uploaded. A story is downloaded, shared (Web Share API) or saved to IndexedDB in this browser only
 * when the person taps that button. Location is kept in memory for the sky labels and never written to a card.
 *
 * Accuracy: sky labels come from Sky Compass maths (sky.js) and the phone's sensors. They are always labelled as
 * estimates and are never presented as stars identified in the photo. Constellation figures are illustrations. */
(function (root) {
  "use strict";
  const doc = root.document, R = root.StoryRender, Sky = root.Sky, S = root.ShareKit, E = root.Explorer, H = root.ExplorerHome;
  if (!doc || !R || !S || !E || !H) return;
  const $ = (id) => doc.getElementById(id);
  const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); });
  const say = (id, msg) => { const el = $(id); if (el) el.textContent = msg || ""; };
  const tell = (id) => doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id } }));

  const st = { photo: null, estimated: false, tpl: "discovery", sticker: "none", stickerAt: { x: 0.82, y: 0.12 }, cons: null, fact: null };

  /* ================= 1 · photo sources ================= */
  let stream = null;
  async function openCamera() {
    say("photoMsg", ""); say("camMsg", "");
    if (!root.isSecureContext || !root.navigator.mediaDevices || !root.navigator.mediaDevices.getUserMedia) {
      say("photoMsg", "This browser can’t open the camera here. Use “Add a photo” instead: on a phone it can open the camera too.");
      return;
    }
    try {
      stream = await root.navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
    } catch (e) {
      const why = e && e.name === "NotAllowedError" ? "Camera permission was not given." : e && e.name === "NotFoundError" ? "No camera was found." : "The camera could not be opened.";
      say("photoMsg", `${why} You can still add a photo or use a NASA picture.`);
      return;
    }
    const v = $("cam");
    v.srcObject = stream;
    $("camBox").hidden = false;
    $("openCam").setAttribute("aria-pressed", "true");
    try { await v.play(); } catch { /* autoplay with muted video is allowed; ignore */ }
  }
  function closeCamera() {
    stopSky();
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    $("camBox").hidden = true;
    $("openCam").setAttribute("aria-pressed", "false");
  }
  function snap() {
    const v = $("cam");
    if (!v.videoWidth) { say("camMsg", "The camera is still starting. Try again in a moment."); return; }
    const c = doc.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    const g = c.getContext("2d");
    g.drawImage(v, 0, 0);
    const withLabels = sky.on && sky.drawn > 0;
    if (withLabels) g.drawImage($("camOverlay"), 0, 0, c.width, c.height);
    usePhoto(c, { estimated: withLabels });
    closeCamera();
  }
  function fromFile(file) {
    if (!file || !/^image\//.test(file.type)) { say("photoMsg", "Please choose a picture file."); return; }
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const c = doc.createElement("canvas"), max = 2400, k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
      c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);         // redrawn: EXIF and GPS tags are not kept
      URL.revokeObjectURL(url);
      usePhoto(c, { estimated: false });
    };
    img.onerror = () => { URL.revokeObjectURL(url); say("photoMsg", "That picture could not be opened."); };
    img.src = url;
  }
  async function showNasa() {
    const box = $("nasaPick"), btn = $("openNasa");
    if (!box.hidden) { box.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
    box.hidden = false; btn.setAttribute("aria-expanded", "true");
    box.innerHTML = '<p class="small-note">Loading…</p>';
    const d = await H.load().catch(() => null);
    if (!d) { box.innerHTML = '<p class="small-note">Pictures not available.</p>'; return; }
    box.innerHTML = d.list.map((e) => {
      const t = d.targets[e.id], fr = t && ((t.frames.w2 && t.frames.w2.length ? t.frames.w2 : t.frames.w1) || []);
      const last = fr && fr[fr.length - 1];
      return last ? `<button type="button" class="sc-nasa-pick" data-id="${e.id}" data-png="${last.png}"><img src="data/${e.id}/${last.png}" alt="" width="150" height="150"><span>${t.name}</span></button>` : "";
    }).join("");
    box.querySelectorAll(".sc-nasa-pick").forEach((b) => (b.onclick = () => {
      const img = new Image();
      img.onload = () => {
        const c = doc.createElement("canvas"); c.width = c.height = 1200;
        const g = c.getContext("2d"); g.imageSmoothingEnabled = false; g.drawImage(img, 0, 0, 1200, 1200);
        usePhoto(c, { estimated: false, nasa: b.dataset.id });
        const sel = $("fFact"); if (sel && [...sel.options].some((o) => o.value === b.dataset.id)) { sel.value = b.dataset.id; st.fact = b.dataset.id; draw(); }
      };
      img.src = `data/${b.dataset.id}/${b.dataset.png}`;
    }));
  }
  function usePhoto(canvas, meta) {
    st.photo = canvas; st.estimated = !!meta.estimated; st.nasa = meta.nasa || null;
    $("stepDesign").hidden = false; $("stepSave").hidden = false;
    $("nasaPick").hidden = true; $("openNasa").setAttribute("aria-expanded", "false");
    tell("camera-photo");
    draw();
    $("stepDesign").scrollIntoView({ behavior: root.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  /* ================= estimated sky labels on the live camera ================= */
  const sky = { on: false, loc: null, pose: null, decl: 0, objects: [], raf: 0, drawn: 0, listener: null };
  async function startSky() {
    if (!Sky) { say("camMsg", "Sky maths not available."); return; }
    say("camMsg", "Asking for motion sensors and location (used only on this phone)…");
    try {   // iOS needs a tap-time permission for orientation
      const DOE = root.DeviceOrientationEvent;
      if (DOE && typeof DOE.requestPermission === "function" && (await DOE.requestPermission()) !== "granted") throw new Error("orientation");
    } catch { say("camMsg", "Motion sensor permission was not given, so labels can’t follow the camera."); return; }
    const loc = await new Promise((ok) => {
      if (!root.navigator.geolocation) return ok(null);
      root.navigator.geolocation.getCurrentPosition((p) => ok({ lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy }), () => ok(null), { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 });
    });
    if (!loc) { say("camMsg", "Location was not given, so the sky above you can’t be worked out. Labels need your rough location (it is never saved or put on a card)."); return; }
    sky.loc = loc;
    try { await Sky.loadDeclination("data/declination.json"); sky.decl = Sky.declination(loc.lat, loc.lon) || 0; } catch { sky.decl = 0; }
    const stars = await getJSON("data/skystars.json").catch(() => null);
    const now = new Date();
    const objs = [{ name: "Moon", body: "moon", kind: "moon" }, { name: "Sun", body: "sun", kind: "sun" }];
    Sky.planets(now).forEach((p) => objs.push({ name: p.name, ra: p.ra, dec: p.dec, kind: "planet" }));
    if (stars) stars.stars.filter((s) => s[2] <= 1.6 && s[7]).forEach((s) => objs.push({ name: s[7], ra: s[0], dec: s[1], kind: "star" }));
    sky.objects = objs;
    sky.listener = (e) => { const p = R.pose(e); if (p) { sky.pose = p; drawLabels(); } };   // redraw on every sensor update too
    root.addEventListener("deviceorientationabsolute", sky.listener);
    root.addEventListener("deviceorientation", sky.listener);
    sky.on = true;
    $("skyLabels").setAttribute("aria-pressed", "true");
    $("nudgeBox").hidden = false;
    const b = $("estBanner"); b.hidden = false; b.textContent = R.estimateNote();
    say("camMsg", "");
    tick();
    setTimeout(() => { if (sky.on && !sky.pose) say("camMsg", "No compass reading from this device, so labels can’t be placed. Sky labels work on phones with a compass."); }, 2500);
  }
  function stopSky() {
    sky.on = false; cancelAnimationFrame(sky.raf);
    if (sky.listener) { root.removeEventListener("deviceorientationabsolute", sky.listener); root.removeEventListener("deviceorientation", sky.listener); }
    const c = $("camOverlay"); c.getContext("2d").clearRect(0, 0, c.width, c.height);
    $("skyLabels").setAttribute("aria-pressed", "false"); $("nudgeBox").hidden = true; $("estBanner").hidden = true;
  }
  function tick() {
    if (!sky.on) return;
    drawLabels();
    sky.raf = requestAnimationFrame(tick);
  }
  function drawLabels() {
    if (!sky.on) return;
    const v = $("cam"), c = $("camOverlay");
    if (v.videoWidth && (c.width !== v.videoWidth || c.height !== v.videoHeight)) { c.width = v.videoWidth; c.height = v.videoHeight; }
    const g = c.getContext("2d");
    g.clearRect(0, 0, c.width, c.height);
    sky.drawn = 0;
    if (sky.pose && c.width) {
      const now = new Date(), nudge = +$("nudge").value || 0;
      const pose = { heading: (sky.pose.heading + sky.decl + nudge + 360) % 360, pitch: sky.pose.pitch };
      const hfov = c.width >= c.height ? 63 : 48;              // typical phone main camera
      g.font = `${Math.round(c.width / 34)}px Inter, system-ui, sans-serif`;
      g.textBaseline = "middle";
      const boxes = [];                                         // keep labels from overlapping: move a label down until it is clear
      for (const o of sky.objects) {
        const pos = Sky.observe(o.body ? { body: o.body } : { ra: o.ra, dec: o.dec }, now, sky.loc.lat, sky.loc.lon);
        if (pos.alt < -2) continue;
        const pt = R.skyToScreen(pos, pose, hfov, c.width, c.height);
        if (!pt) continue;
        sky.drawn++;
        const r = o.kind === "moon" || o.kind === "sun" ? c.width / 26 : c.width / 70;
        g.strokeStyle = o.kind === "planet" ? "#F2B866" : "#8AB6EF"; g.lineWidth = Math.max(2, c.width / 400);
        g.setLineDash([6, 6]); g.beginPath(); g.arc(pt.x, pt.y, r, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
        const label = `${o.name} (est.)`, w = g.measureText(label).width, bh = c.width / 25;
        const bx = pt.x + r + 6; let by = pt.y - bh / 2;
        for (let k = 0; k < 6 && boxes.some((b) => bx < b.x + b.w && b.x < bx + w + 16 && by < b.y + b.h && b.y < by + bh); k++) by += bh + 4;
        boxes.push({ x: bx, y: by, w: w + 16, h: bh });
        if (by !== pt.y - bh / 2) { g.strokeStyle = "rgba(241,245,250,.5)"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(pt.x + r, pt.y); g.lineTo(bx, by + bh / 2); g.stroke(); }
        g.fillStyle = "rgba(5,11,20,.62)"; g.fillRect(bx, by, w + 16, bh);
        g.fillStyle = "#F1F5FA"; g.fillText(label, bx + 8, by + bh / 2);
      }
    }
  }

  /* ================= 2 · design ================= */
  const STICKERS = { none: "None", star: "Star", moon: "Moon", orbit: "Orbit", comet: "Comet" };
  function drawSticker(g, kind, x, y, s) {
    g.save(); g.translate(x, y); g.lineWidth = s * 0.06; g.lineJoin = "round"; g.lineCap = "round";
    if (kind === "star") {
      g.fillStyle = "#F2B866"; g.beginPath();
      for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? s * 0.22 : s * 0.5; g.lineTo(Math.cos(a) * r, Math.sin(a) * r); }
      g.closePath(); g.fill();
    } else if (kind === "moon") {
      // crescent: clip away the inner disc instead of erasing it, so the photo underneath stays intact
      g.beginPath(); g.rect(-s, -s, 2 * s, 2 * s); g.arc(s * 0.2, -s * 0.12, s * 0.38, 0, Math.PI * 2, true); g.clip("evenodd");
      g.fillStyle = "#E6EEF8"; g.beginPath(); g.arc(0, 0, s * 0.45, 0, Math.PI * 2); g.fill();
    } else if (kind === "orbit") {
      g.strokeStyle = "#8AB6EF"; g.beginPath(); g.ellipse(0, 0, s * 0.5, s * 0.22, -0.5, 0, Math.PI * 2); g.stroke();
      g.fillStyle = "#8AB6EF"; g.beginPath(); g.arc(s * 0.12, -s * 0.28, s * 0.1, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "#F1F5FA"; g.lineWidth = s * 0.08; g.beginPath(); g.arc(0, 0, s * 0.62, 0.35, Math.PI * 1.75); g.stroke();
    } else if (kind === "comet") {
      const grd = g.createLinearGradient(-s * 0.6, s * 0.4, s * 0.25, -s * 0.2); grd.addColorStop(0, "rgba(138,182,239,0)"); grd.addColorStop(1, "rgba(138,182,239,.9)");
      g.strokeStyle = grd; g.lineWidth = s * 0.16; g.beginPath(); g.moveTo(-s * 0.6, s * 0.4); g.lineTo(s * 0.2, -s * 0.15); g.stroke();
      g.fillStyle = "#F1F5FA"; g.beginPath(); g.arc(s * 0.25, -s * 0.2, s * 0.14, 0, Math.PI * 2); g.fill();
    }
    g.restore();
  }
  let consData = null, facts = {};
  async function loadDesignData() {
    const sel = $("fFact"), cs = $("fCons");
    const d = await H.load().catch(() => null);
    if (d) {
      const lv = E.current() === "kids" ? "kids" : "teens";
      H.buildStories(lv, d.targets).forEach((s) => { facts[s.id] = s; sel.add(new Option(`${s.name}: ${s.title}`, s.id)); });
    }
    consData = await getJSON("data/constellations.json").then((j) => j.list).catch(() => []);
    consData.slice().sort((a, b) => a.name.localeCompare(b.name)).forEach((c) => cs.add(new Option(c.name, c.id)));
  }
  function wireDesign() {
    const tp = $("tplPick");
    tp.innerHTML = Object.entries(R.TEMPLATES).map(([k, t]) => `<button type="button" class="chip-btn" data-k="${k}" aria-pressed="${k === st.tpl}">${t.name}</button>`).join("");
    tp.querySelectorAll("button").forEach((b) => (b.onclick = () => { st.tpl = b.dataset.k; tp.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); }));
    const sp = $("stickerPick");
    sp.innerHTML = Object.entries(STICKERS).map(([k, n]) => `<button type="button" class="chip-btn" data-k="${k}" aria-pressed="${k === st.sticker}">${n}</button>`).join("");
    sp.querySelectorAll("button").forEach((b) => (b.onclick = () => { st.sticker = b.dataset.k; sp.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); }));
    const lv = E.current();
    $("fTitle").value = lv === "kids" ? "My space discovery" : lv === "teens" ? "Tonight’s sky" : "Sky notes";
    ["fTitle", "fText", "fDate"].forEach((id) => $(id).addEventListener("input", draw));
    $("fFact").onchange = () => { st.fact = $("fFact").value || null; draw(); };
    $("fCons").onchange = () => { const id = $("fCons").value; st.cons = id ? consData.find((c) => c.id === id) : null; draw(); };
    $("storyCanvas").addEventListener("click", (e) => {
      if (st.sticker === "none") return;
      const r = e.currentTarget.getBoundingClientRect();
      st.stickerAt = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; draw();
    });
  }

  /* ================= card drawing (1080 × 1920) ================= */
  function draw() {
    const c = $("storyCanvas"), g = c.getContext("2d"), T = R.TEMPLATES[st.tpl], W = R.W, Hh = R.H;
    g.clearRect(0, 0, W, Hh);
    g.fillStyle = T.bg; g.fillRect(0, 0, W, Hh);
    if (!st.photo) return;
    const ph = T.photo;
    g.save();
    if (T.radius) { g.beginPath(); g.roundRect(ph.x, ph.y, ph.w, ph.h, T.radius); g.clip(); }
    const fit = R.coverFit(st.photo.width, st.photo.height, ph.w, ph.h);
    g.imageSmoothingEnabled = !st.nasa;
    g.drawImage(st.photo, fit.sx, fit.sy, fit.sw, fit.sh, ph.x, ph.y, ph.w, ph.h);
    g.restore();
    // constellation guide (illustration) over the photo
    const notes = [];
    if (st.cons) {
      const size = Math.min(ph.w, ph.h) * 0.7, f = R.constellationFigure(st.cons, size, 0.08), ox = ph.x + (ph.w - size) / 2, oy = ph.y + (ph.h - size) / 2;
      g.save(); g.strokeStyle = "rgba(242,184,102,.85)"; g.fillStyle = "#FFE6BF"; g.lineWidth = 5; g.lineJoin = "round";
      f.paths.forEach((p) => { g.beginPath(); p.forEach((q, i) => (i ? g.lineTo(ox + q.x, oy + q.y) : g.moveTo(ox + q.x, oy + q.y))); g.stroke(); });
      f.points.forEach((q) => { g.beginPath(); g.arc(ox + q.x, oy + q.y, 9, 0, Math.PI * 2); g.fill(); });
      g.restore();
      notes.push(`${st.cons.name}: constellation guide, illustration only`);
    }
    if (st.estimated) notes.push("Sky labels estimated from phone sensors, not identified in the photo");
    if (st.nasa) notes.push("Image: NASA WISE / SPHEREx via WANDERERS");
    // text panel
    const P = T.panel;
    if (P.scrim) { const gr = g.createLinearGradient(0, P.y - 260, 0, Hh); gr.addColorStop(0, "rgba(5,11,20,0)"); gr.addColorStop(0.35, "rgba(5,11,20,.82)"); gr.addColorStop(1, "rgba(5,11,20,.95)"); g.fillStyle = gr; g.fillRect(0, P.y - 260, W, Hh - P.y + 260); }
    else { g.fillStyle = T.bg; g.fillRect(0, P.y, W, P.h); }
    let y = P.y + 70;
    const x = 84, maxW = W - 168;
    g.fillStyle = T.accent; g.font = "500 30px 'IBM Plex Mono', monospace";
    g.fillText("WANDERERS · SPACE STORY", x, y); y += 72;
    g.fillStyle = T.ink; g.font = "800 76px Manrope, sans-serif";
    R.wrapText((s) => g.measureText(s).width, $("fTitle").value || "", maxW, 2).forEach((l) => { g.fillText(l, x, y); y += 84; });
    g.fillStyle = T.soft; g.font = "400 40px Inter, sans-serif";
    R.wrapText((s) => g.measureText(s).width, $("fText").value || "", maxW, 3).forEach((l) => { g.fillText(l, x, y); y += 54; });
    if (st.fact && facts[st.fact]) {
      const f = facts[st.fact];
      y += 10; g.fillStyle = T.accent; g.font = "600 34px Inter, sans-serif"; g.fillText(`Real data · ${f.name}`, x, y); y += 48;
      g.fillStyle = T.ink; g.font = "500 36px 'IBM Plex Mono', monospace";
      R.wrapText((s) => g.measureText(s).width, f.chip, maxW, 2).forEach((l) => { g.fillText(l, x, y); y += 46; });
    }
    // footer: date (day only) and honesty notes
    g.font = "400 26px 'IBM Plex Mono', monospace"; g.fillStyle = T.soft;
    const noteLines = notes.flatMap((n) => R.wrapText((t) => g.measureText(t).width, n, maxW, 3));
    let fy = Hh - 60 - 34 * noteLines.length;
    if ($("fDate").checked) { g.fillText(R.dayStamp(new Date()), x, fy - 6); }
    noteLines.forEach((n, i) => g.fillText(n, x, fy + 34 * (i + 1)));
    // sticker last, on top
    if (st.sticker !== "none") drawSticker(g, st.sticker, st.stickerAt.x * W, st.stickerAt.y * Hh, 200);
    c.setAttribute("aria-label", `Story card preview: ${$("fTitle").value || "untitled"}${st.fact && facts[st.fact] ? `, with a fact about ${facts[st.fact].name}` : ""}${notes.length ? ". " + notes.join(". ") : ""}`);
  }

  /* ================= 3 · save, share and my stories ================= */
  const toBlob = () => new Promise((ok) => $("storyCanvas").toBlob(ok, "image/png"));
  const fileName = () => S.safeName(`wanderers-story-${$("fTitle").value || "space"}`, "png");
  async function doShare() {
    const blob = await toBlob(), file = new File([blob], fileName(), { type: "image/png" });
    const r = await S.share({ title: $("fTitle").value || "My space story", text: "Made with WANDERERS", file });
    say("saveMsg", r === "shared" ? "Shared." : r === "downloaded" ? "Sharing isn’t available here, so the picture was downloaded instead." : r === "cancelled" ? "" : "Could not share.");
    if (r === "shared" || r === "downloaded") tell("story-made");
  }
  async function doDownload() { S.download(fileName(), await toBlob(), "image/png"); say("saveMsg", "Downloaded."); tell("story-made"); }

  // IndexedDB: one store, records {id, day, title, blob}; nothing leaves the browser
  const DB = { name: "wanderers-stories", store: "stories" };
  const openDB = () => new Promise((ok, no) => {
    if (!root.indexedDB) return no(new Error("no indexedDB"));
    const rq = root.indexedDB.open(DB.name, 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore(DB.store, { keyPath: "id" });
    rq.onsuccess = () => ok(rq.result); rq.onerror = () => no(rq.error);
  });
  const tx = async (mode, fn) => { const db = await openDB(); return new Promise((ok, no) => { const t = db.transaction(DB.store, mode), s = t.objectStore(DB.store), r = fn(s); t.oncomplete = () => ok(r && r.result); t.onerror = () => no(t.error); }); };
  async function saveStory() {
    try {
      const blob = await toBlob(), rec = { id: `s${Date.now()}`, day: R.dayStamp(new Date()), title: $("fTitle").value || "Space story", blob };
      await tx("readwrite", (s) => s.put(rec));
      say("saveMsg", "Saved in this browser only."); tell("story-made"); renderGallery();
    } catch { say("saveMsg", "This browser can’t save stories (private mode?). Use Download instead."); }
  }
  const urls = [];
  async function renderGallery() {
    const g = $("gallery");
    let items = [];
    try { items = (await tx("readonly", (s) => s.getAll())) || []; } catch { g.innerHTML = '<p class="small-note">Saving stories isn’t available in this browser.</p>'; return; }
    urls.splice(0).forEach((u) => URL.revokeObjectURL(u));
    if (!items.length) { g.innerHTML = '<p class="small-note">No saved stories yet.</p>'; return; }
    items.sort((a, b) => (a.id < b.id ? 1 : -1));
    g.innerHTML = items.map((it) => { const u = URL.createObjectURL(it.blob); urls.push(u); return `<figure class="sc-thumb"><img src="${u}" alt="${it.title.replace(/"/g, "&quot;")}" width="108" height="192"><figcaption>${it.day}</figcaption>
      <div class="sc-thumb-act"><a class="btn btn-ghost tiny" href="${u}" download="${S.safeName("wanderers-story-" + it.title, "png")}">Download</a><button type="button" class="btn btn-ghost tiny" data-del="${it.id}">Delete</button></div></figure>`; }).join("");
    g.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { await tx("readwrite", (s) => s.delete(b.dataset.del)); renderGallery(); }));
  }

  /* ================= wiring ================= */
  $("openCam").onclick = openCamera;
  $("closeCam").onclick = closeCamera;
  $("snap").onclick = snap;
  $("skyLabels").onclick = () => (sky.on ? stopSky() : startSky());
  $("nudge").oninput = () => { $("nudgeVal").textContent = `${$("nudge").value}°`; };
  $("upload").onchange = (e) => { fromFile(e.target.files && e.target.files[0]); e.target.value = ""; };
  $("openNasa").onclick = showNasa;
  $("doShare").onclick = doShare;
  $("doDownload").onclick = doDownload;
  $("doSave").onclick = saveStory;
  root.addEventListener("pagehide", closeCamera);
  wireDesign();
  (doc.fonts && doc.fonts.ready ? doc.fonts.ready : Promise.resolve()).then(() => { loadDesignData().then(draw); });
  renderGallery();
  root.StoryStudio = { draw, state: st };   // for tests and debugging
})(typeof window !== "undefined" ? window : globalThis);
