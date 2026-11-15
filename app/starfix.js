/* Star Fix page: upload, one answer per night, the map. The maths, the words and the photo queue are in
 * starfixcore.js; this file puts them into the page and updates it in place. Nothing is stored: a reload shows
 * the example again. The page is one place (no history entries), so Back always returns to where you came from. */
(() => {
  "use strict";
  const C = window.StarFixCore, $ = (id) => document.getElementById(id);
  const input = $("files"), blocksEl = $("blocks"), exampleEl = $("example"), bar = $("progressBar"), say = $("progressText");
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const blocks = new Map(), rowEls = new Map(), seen = new WeakSet();   // night key (its first photo's id) -> block; photo id -> row
  let cities = null, example = null, wasActive = false, lastDone = null, removed = null, undoTimer = 0;

  const earth = new Image();   // NASA Blue Marble, 2048 x 1024, plate carree (the app already ships it)
  earth.onload = () => repaint();
  earth.src = "data/earth/day.jpg";

  const send = (file, signal) => fetch("api/star-fix", { method: "POST", body: file, signal })
    .then((r) => (r.ok ? r.json() : { status: "error" }));   // 409, 500, 504: "Could not read this photo" + Try again
  const q = C.photoQueue(send, sync);
  const setText = (el, t) => { if (el.textContent !== t) el.textContent = t; };
  const setKm = (el, t) => {   // the same, with each "<number> km" in the mono face of measured values
    if (el.textContent !== t) el.replaceChildren(...t.split(/(\d+ km)/).map((s, i) => (i % 2 ? Object.assign(document.createElement("span"), { className: "mono", textContent: s }) : s)));
  };
  const isUsed = (r, outliers) => !!r.result && r.result.status === "fix" && !outliers.includes(r.result);
  const fmtDate = (local) => {   // the photo's own calendar date, not the date where the browser is
    const [y, m, d] = local.slice(0, 10).split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  };

  // ---- one answer block per night, made once and then updated in place ----
  function makeBlock(isExample) {
    const el = $("blockTpl").content.firstElementChild.cloneNode(true), part = (s) => el.querySelector(s);
    const b = { el, isExample, day: part(".sf-day"), head: part(".sf-headline"), pos: part(".sf-pos"), radius: part(".sf-radius"),
      check: part(".sf-check"), map: part(".sf-map"), canvas: part("canvas"), gpsKey: part(".sf-key-gps-row"), osm: part(".sf-osm"),
      link: part(".sf-osm a"), details: part(".sf-photos"), summary: part(".sf-photos summary"), list: part(".sf-photos ul"),
      hint: part(".sf-hint"), notUsed: new Set(), touched: false, want: null, target: null, drawn: null, anim: 0, gps: null };
    if (isExample) { el.classList.add("sf-example"); part(".sf-ex").hidden = false; }
    b.details.addEventListener("toggle", () => { if (b.details.open !== b.want) b.touched = true; });   // the person's choice wins
    return b;
  }
  const setOpen = (b, open) => { b.want = open; if (b.details.open !== open) b.details.open = open; };

  function fill(b, rows) {
    const fixes = rows.filter((r) => r.result && r.result.status === "fix").map((r) => r.result);
    const c = fixes.length ? C.combine(fixes) : null, outliers = c ? c.outliers : [], pending = rows.some((r) => !r.result);
    const first = (k) => (rows.find((r) => r.result && r.result[k]) || { result: {} }).result[k] || null;
    const gps = first("gps"), local = first("local");
    const h = C.headline(c, c && C.nearestCity(c.lat, c.lon, cities), gps, fixes.length, b.isExample);
    setText(b.day, local ? fmtDate(local) : "");
    setText(b.head, c || !pending ? h.headline : "");   // no sentence while the first photos are still being read
    setText(b.pos, h.position || ""); setKm(b.radius, h.radius || ""); setKm(b.check, h.check || ""); setText(b.hint, h.hint || "");
    b.map.hidden = b.osm.hidden = !c;
    if (c) {
      const lat = c.lat.toFixed(2), lon = c.lon.toFixed(2);
      b.canvas.setAttribute("aria-label", h.headline);
      b.link.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=7/${lat}/${lon}`;
      b.gpsKey.hidden = !gps; b.gps = gps;
      draw(b, { lat: c.lat, lon: c.lon, r: c.radiusKm });
    }
    rows.forEach((r, i) => {
      const e = rowFor(r), out = outliers.includes(r.result);
      if (b.list.children[i] !== e.li) b.list.insertBefore(e.li, b.list.children[i] || null);   // moves only when its place changed
      setText(e.mark, !r.result ? (r.state === "reading" ? "…" : "·") : isUsed(r, outliers) ? "✓" : "!");
      setText(e.text, C.describe(r.result || { status: r.state }, out));
      e.retry.hidden = !r.result || r.result.status !== "error";
    });
    const notUsed = rows.filter((r) => r.result && !isUsed(r, outliers)).map((r) => r.id);
    setText(b.summary, C.photosLine(rows.filter((r) => isUsed(r, outliers)).length, rows.length, pending));
    if (notUsed.some((id) => !b.notUsed.has(id))) setOpen(b, true);   // a photo was not used: show why, without a click
    else if (!b.touched) setOpen(b, pending || notUsed.length > 0);  // open while reading, closed when every photo was used
    b.notUsed = new Set(notUsed);
  }

  function rowFor(r) {
    let e = rowEls.get(r.id);
    if (!e) {
      const li = $("rowTpl").content.firstElementChild.cloneNode(true);
      e = { li, mark: li.querySelector(".sf-mark"), text: li.querySelector(".sf-text"), retry: li.querySelector(".sf-retry") };
      li.querySelector(".sf-name").textContent = r.name;
      e.retry.addEventListener("click", () => { li.focus(); q.retry(r); });   // the button hides; focus stays in its row
      rowEls.set(r.id, e);
    }
    return e;
  }

  // ---- after every change of the photo list ----
  function sync() {
    const rows = q.rows, keep = new Set();
    for (const r of rows) if (r.state === "done" && !seen.has(r)) { seen.add(r); lastDone = r; }
    for (const night of C.sessions(rows)) {
      const key = Math.min(...night.map((r) => r.id));
      let b = blocks.get(key);
      if (!b) { b = makeBlock(false); blocks.set(key, b); blocksEl.prepend(b.el); }   // a new night goes on top
      keep.add(key); fill(b, night);
      night.forEach((r) => (r.block = b));
    }
    for (const [key, b] of blocks) if (!keep.has(key)) { b.el.remove(); blocks.delete(key); }
    const any = rows.some((r) => r.result);   // the example shows until the first real result
    if (exampleEl.hidden !== any) { exampleEl.hidden = any; if (!any) repaint(); }
    $("remove").hidden = !any;
    $("pickFirst").hidden = rows.length > 0; $("pickMore").hidden = !rows.length;
    const p = q.progress();
    if (p.active) {
      wasActive = true; bar.hidden = false; bar.max = p.m; bar.value = Math.max(p.n - 1, 0);
      say.classList.remove("visually-hidden"); setText(say, C.reading(Math.max(p.n, 1), p.m));
    } else if (wasActive) {   // the run ended: screen readers hear the answer once; on screen it is in the block already
      wasActive = false; bar.hidden = true; say.classList.add("visually-hidden");
      setText(say, (lastDone && lastDone.block && lastDone.block.head.textContent) || "");
    }
  }

  // ---- the map: 40 x 20 degrees of the Blue Marble around the answer, the circle, two marks ----
  function draw(b, to) {   // the circle glides to its new place in 400 ms; a newer answer starts from where it is drawn now
    if (b.target && to.lat === b.target.lat && to.lon === b.target.lon && to.r === b.target.r) return;
    b.target = to; cancelAnimationFrame(b.anim);
    const from = b.drawn;
    if (!from || still.matches || !b.canvas.clientWidth) return paint(b, to);
    const t0 = performance.now(), step = (t) => {
      const k = Math.min(1, (t - t0) / 400), e = k * (2 - k);
      paint(b, { lat: from.lat + (to.lat - from.lat) * e, lon: from.lon + (to.lon - from.lon) * e, r: from.r + (to.r - from.r) * e });
      if (k < 1) b.anim = requestAnimationFrame(step);
    };
    b.anim = requestAnimationFrame(step);
  }
  // ponytail: 20 km per pixel and no wrap at 180 degrees; use map tiles if a sharper map is needed
  function paint(b, s) {
    b.drawn = s;
    const cv = b.canvas, k = devicePixelRatio || 1, W = Math.round(cv.clientWidth * k), H = Math.round(W / 2);
    if (!W) return;   // hidden now: drawn again when it shows
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const g = cv.getContext("2d"), css = getComputedStyle(document.documentElement), tok = (n) => css.getPropertyValue(n).trim();
    const x = (lon) => (lon - s.lon + 20) / 40 * W, y = (lat) => (s.lat + 10 - lat) / 20 * H;
    g.fillStyle = tok("--viewer"); g.fillRect(0, 0, W, H);
    if (earth.naturalWidth) {
      const iw = earth.naturalWidth / 360, ih = earth.naturalHeight / 180;
      g.drawImage(earth, (s.lon - 20 + 180) * iw, (90 - s.lat - 10) * ih, 40 * iw, 20 * ih, 0, 0, W, H);
    }
    g.lineWidth = 1.5 * k; g.strokeStyle = g.fillStyle = getComputedStyle(b.map).getPropertyValue("--map-accent").trim();
    g.beginPath(); C.circle(s.lat, s.lon, s.r).forEach((p, i) => g[i ? "lineTo" : "moveTo"](x(p.lon), y(p.lat))); g.closePath(); g.stroke();
    const cx = x(s.lon), cy = y(s.lat);   // the answer: a solid point with a four-tick reticle, as in the emblem ("now")
    g.beginPath(); g.arc(cx, cy, 2.5 * k, 0, 2 * Math.PI); g.fill();
    g.beginPath();
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { g.moveTo(cx + dx * 5 * k, cy + dy * 5 * k); g.lineTo(cx + dx * 9 * k, cy + dy * 9 * k); }
    g.stroke();
    if (b.gps) {   // what the phone recorded: a hollow ring
      g.strokeStyle = tok("--viewer-ink"); g.beginPath(); g.arc(x(b.gps.lon), y(b.gps.lat), 5 * k, 0, 2 * Math.PI); g.stroke();
    }
  }
  function repaint() { for (const b of [example, ...blocks.values()]) if (b && b.drawn) paint(b, b.drawn); }
  document.addEventListener("themechange", repaint);
  addEventListener("resize", repaint);

  // ---- the example: shown first, built by the same code once its data and the city list are here ----
  Promise.all(["data/starfix-sample.json", "data/earth/cities.json"].map((u) => fetch(u).then((r) => r.json())))
    .then(([sample, list]) => {
      cities = list;
      example = makeBlock(true);
      exampleEl.append(example.el);
      fill(example, sample.map((s, i) => ({ id: -1 - i, name: s.name, result: s, utc: s.utc, state: "done" })));
      sync();   // nights read before the city list arrived get their place name now
    })
    .catch(() => {})
    .finally(() => exampleEl.classList.remove("sf-reserve"));

  // ---- adding photos: the button, or a drop anywhere on the page ----
  function add(list) {
    if (input.disabled || !list.length) return;
    dismissUndo();
    q.add([...list]);
  }
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  const dragging = (on) => { $("upload").classList.toggle("is-drag", on); $("dropHint").hidden = on || input.disabled; $("dropNow").hidden = !on; };
  const hasFiles = (e) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  document.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();   // never let the browser open a dropped file: the results would be lost
    e.dataTransfer.dropEffect = input.disabled ? "none" : "copy";
    if (!input.disabled) dragging(true);
  });
  document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) dragging(false); });
  document.addEventListener("drop", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragging(false); add(e.dataTransfer.files); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") dragging(false); });

  // ---- "Remove my photos", with Undo instead of a question ----
  function dismissUndo() { clearTimeout(undoTimer); removed = null; $("undoBox").hidden = true; }
  $("remove").addEventListener("click", () => {
    removed = q.clear();
    for (const b of blocks.values()) { cancelAnimationFrame(b.anim); b.el.remove(); }
    blocks.clear(); rowEls.clear();
    wasActive = false; bar.hidden = true; setText(say, "");
    sync();
    input.focus();
    $("undoBox").hidden = false;
    clearTimeout(undoTimer); undoTimer = setTimeout(dismissUndo, 8000);
  });
  $("undo").addEventListener("click", () => { const copy = removed; dismissUndo(); input.focus(); if (copy) q.restore(copy); });

  // ---- without the local server: keep the example, explain in one line, after the check fails (not before) ----
  fetch("api/health").then((r) => { if (!r.ok) throw new Error("no server"); }).catch(() => {
    input.disabled = true; $("pick").classList.add("is-off"); $("offline").hidden = false; $("dropHint").hidden = true;
  });
})();
