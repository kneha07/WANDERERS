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
  const setKm = (el, t) => {   // the same, with each km value in the mono face of measured values
    if (el.textContent !== t) el.replaceChildren(...t.split(/(\d+)(?= km)/).map((s, i) => (i % 2 ? Object.assign(document.createElement("span"), { className: "mono", textContent: s }) : s)));
  };

  // ---- one answer block per night, made once and then updated in place ----
  function makeBlock(isExample) {
    const el = $("blockTpl").content.firstElementChild.cloneNode(true), part = (s) => el.querySelector(s);
    const b = { el, isExample, day: part(".sf-day"), head: part(".sf-headline"), pos: part(".sf-pos"), radius: part(".sf-radius"),
      check: part(".sf-check"), map: part(".sf-map"), canvas: part("canvas"), gpsKey: part(".sf-key-gps-row"), osm: part(".sf-osm"),
      link: part(".sf-osm a"), details: part(".sf-photos"), summary: part(".sf-photos summary"), list: part(".sf-photos ul"),
      hint: part(".sf-hint"), touched: false, target: null, drawn: null, anim: 0, gps: null };
    if (isExample) { el.classList.add("sf-example"); part(".sf-ex").hidden = false; }
    b.summary.addEventListener("click", () => { b.touched = true; });   // mouse, Enter or Space: from now on the person decides
    return b;
  }

  function fill(b, rows) {   // the rules are in StarFixCore.night(); this only writes its answer into the block
    const v = C.night(rows, { cities, example: b.isExample });
    setText(b.day, v.day); setText(b.head, v.headline); setText(b.pos, v.position);
    setKm(b.radius, v.radius); setKm(b.check, v.check); setText(b.hint, v.hint);
    b.map.hidden = b.osm.hidden = !v.map;
    if (v.map) {
      b.canvas.setAttribute("aria-label", v.headline);
      b.link.href = v.osm;
      b.gpsKey.hidden = !v.gps; b.gps = v.gps;
      draw(b, v.map);
    }
    v.rows.forEach((x, i) => {
      const e = rowFor(x.row);
      if (b.list.children[i] !== e.li) b.list.insertBefore(e.li, b.list.children[i] || null);   // moves only when its place changed
      setText(e.mark, x.mark); setText(e.text, x.text); e.retry.hidden = !x.retry;
    });
    setText(b.summary, v.summary);
    if (!b.touched && b.details.open !== v.open) b.details.open = v.open;   // until the person opens or closes the list
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

  // ---- the map: the Blue Marble around the answer (window sized from the data), the circle, two marks ----
  function draw(b, to) {   // map and circle glide to the new answer in 400 ms; a newer answer starts from what is drawn now
    const t = b.target;
    if (t && to.lat === t.lat && to.lon === t.lon && to.r === t.r && to.span === t.span) return;
    b.target = to; cancelAnimationFrame(b.anim);
    const from = b.drawn;
    if (!from || still.matches || !b.canvas.clientWidth) return paint(b, to);
    const t0 = performance.now(), mix = (a, z, e) => a + (z - a) * e, step = (now) => {
      const k = Math.min(1, (now - t0) / 400), e = k * (2 - k);
      paint(b, { lat: mix(from.lat, to.lat, e), lon: mix(from.lon, to.lon, e), r: mix(from.r, to.r, e), span: mix(from.span, to.span, e) });
      if (k < 1) b.anim = requestAnimationFrame(step);
    };
    b.anim = requestAnimationFrame(step);
  }
  // ponytail: day.jpg has about 20 km per image pixel (blurry when zoomed in) and no wrap at 180 degrees; use map tiles if a sharper map is needed
  function paint(b, s) {
    b.drawn = s;
    const cv = b.canvas, k = devicePixelRatio || 1, W = Math.round(cv.clientWidth * k), H = Math.round(W / 2);
    if (!W) return;   // hidden now: drawn again when it shows
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const g = cv.getContext("2d"), css = getComputedStyle(document.documentElement), tok = (n) => css.getPropertyValue(n).trim();
    const w = s.span, h = s.span / 2;   // degrees across and down: 2:1, like the canvas
    const x = (lon) => (lon - s.lon + w / 2) / w * W, y = (lat) => (s.lat + h / 2 - lat) / h * H;
    g.fillStyle = tok("--viewer"); g.fillRect(0, 0, W, H);
    if (earth.naturalWidth) {
      const iw = earth.naturalWidth / 360, ih = earth.naturalHeight / 180;
      g.imageSmoothingQuality = "high";
      g.drawImage(earth, (s.lon - w / 2 + 180) * iw, (90 - s.lat - h / 2) * ih, w * iw, h * ih, 0, 0, W, H);
    }
    g.lineWidth = 1.5 * k; g.strokeStyle = g.fillStyle = getComputedStyle(b.map).getPropertyValue("--map-accent").trim();
    g.beginPath(); C.circle(s.lat, s.lon, s.r).forEach((p, i) => g[i ? "lineTo" : "moveTo"](x(p.lon), y(p.lat))); g.closePath(); g.stroke();
    const cx = x(s.lon), cy = y(s.lat);   // the answer: a solid point with a four-tick reticle, as in the emblem ("now")
    g.beginPath(); g.arc(cx, cy, 2.5 * k, 0, 2 * Math.PI); g.fill();
    g.beginPath();
    const t = C.RETICLE_PX * k;   // ticks from 5 px to the reticle size (9 px), the size night() tests the circle against
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { g.moveTo(cx + dx * 5 * k, cy + dy * 5 * k); g.lineTo(cx + dx * t, cy + dy * t); }
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
    const again = q.add([...list]);   // files already in the list: say so in the status line (no new layer)
    $("dupNames").textContent = again.join(", "); $("dupBox").hidden = !again.length;
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
    removed = q.clear(); $("dupBox").hidden = true;
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
