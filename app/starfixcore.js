/* StarFixCore: the maths and the words of the Star Fix page, pure, no DOM.
 * Input: the results of POST /api/star-fix (pipeline/star_fix.py), one per photo.
 * Works in the browser (window.StarFixCore) and in Node (module.exports), like starcore.js.
 */
(function (root) {
  "use strict";
  const R = 6371, DEG = Math.PI / 180;
  const vec = (p) => [Math.cos(p.lat * DEG) * Math.cos(p.lon * DEG), Math.cos(p.lat * DEG) * Math.sin(p.lon * DEG), Math.sin(p.lat * DEG)];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

  // Great-circle distance in km between {lat, lon} points (atan2 form: exact for near and far points).
  function distKm(a, b) {
    const x = vec(a), y = vec(b);
    return R * Math.atan2(Math.hypot(x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]), dot(x, y));
  }

  // Photos -> nights. Sorted by time; a gap of more than 60 minutes starts a new night. Rows without a time
  // (not read yet, or no time in the file) join the newest night.
  function sessions(rows) {
    const out = [];
    let last = -Infinity;
    for (const r of rows.filter((x) => x.utc).sort((a, b) => Date.parse(a.utc) - Date.parse(b.utc))) {
      if (Date.parse(r.utc) - last > 3600e3) out.push([]);
      out[out.length - 1].push(r);
      last = Date.parse(r.utc);
    }
    const untimed = rows.filter((x) => !x.utc);
    if (untimed.length) { if (!out.length) out.push([]); out[out.length - 1].push(...untimed); }
    return out;
  }

  const median = (a) => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  // The photos of one night -> one place: the median of each unit-vector component, normalised. The median ignores one
  // bad photo by itself; with 3 or more photos one that is more than 300 km away is also listed as not used.
  // Radius ("usually right to about"): 150 km for one photo, else max(50, median distance of the photos from the place).
  function combine(fixes) {
    const v = fixes.map(vec), m = [0, 1, 2].map((i) => median(v.map((x) => x[i]))), n = Math.hypot(...m);
    const at = { lat: Math.asin(m[2] / n) / DEG, lon: Math.atan2(m[1], m[0]) / DEG };
    const d = fixes.map((f) => distKm(f, at));
    return { ...at, radiusKm: fixes.length === 1 ? 150 : Math.max(50, median(d)),
      outliers: fixes.length >= 3 ? fixes.filter((f, i) => d[i] > 300) : [] };
  }

  // The error circle for the map: n points `km` from the centre (destination-point formula).
  function circle(lat, lon, km, n = 64) {
    const p = lat * DEG, d = km / R, out = [];
    for (let i = 0; i < n; i++) {
      const b = 2 * Math.PI * i / n, q = Math.asin(Math.sin(p) * Math.cos(d) + Math.cos(p) * Math.sin(d) * Math.cos(b));
      out.push({ lat: q / DEG, lon: lon + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p), Math.cos(d) - Math.sin(p) * Math.sin(q)) / DEG });
    }
    return out;
  }

  // ---- words: every sentence the person reads comes from here or from starfix.html (one test checks them all) ----
  const TEXT = { no_solve: "Too few stars to recognise. Use a darker, clearer photo.", bad_file: "This file is not a photo. Choose a .heic or .jpg file.",
    too_large: "This file is too large (30 MB limit). Use the original photo.", error: "Could not read this photo.", setup: "Star Fix is not set up on this computer. Start the app with start.cmd.", waiting: "waiting", reading: "reading" };
  const MISSING = { gravity: "the file has no tilt data. Use the original iPhone file.", time: "the file has no time data. Use the original iPhone file.",
    rear_camera: "this camera is not supported. Use the main rear camera." };
  const WARN = { zone_mismatch: "The place does not match the photo's time zone. The file may be edited.",
    untested_lens: "Zoom or wide lens: the result may be less exact.", small_photo: "This photo is small. Use the original file for a better result." };

  // The row text for one photo, with its warnings. Page-only statuses: too_large, setup (500, solver missing), error (409, other 500, 504, network), waiting, reading.
  function describe(r, isOutlier) {
    const base = r.status === "sky_only" ? `Stars recognised (${r.sky.constellation}), but ${MISSING[r.missing[0]]}`
      : r.status === "fix" ? (isOutlier ? "Not used: it disagrees with the other photos" : `Used · stars of ${r.sky.constellation}`)
        : TEXT[r.status] || TEXT.error;
    const warn = (r.warnings || []).map((w) => WARN[w]).filter(Boolean);
    return [base + (warn.length && !base.endsWith(".") ? "." : ""), ...warn].join(" ");
  }

  // Nearest row of data/earth/cities.json ([name, country, lat, lon]) -> {name, country, lat, lon, km}, or null.
  function nearestCity(lat, lon, cities) {
    let best = null;
    for (const [name, country, la, lo] of cities || []) {
      const km = distKm({ lat, lon }, { lat: la, lon: lo });
      if (!best || km < best.km) best = { name, country, lat: la, lon: lo, km };
    }
    return best;
  }

  const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
  function direction(a, b) {   // compass word for the initial bearing from a to b
    const p = a.lat * DEG, q = b.lat * DEG, dl = (b.lon - a.lon) * DEG;
    const deg = Math.atan2(Math.sin(dl) * Math.cos(q), Math.cos(p) * Math.sin(q) - Math.sin(p) * Math.cos(q) * Math.cos(dl)) / DEG;
    return COMPASS[(Math.round(deg / 45) + 8) % 8];
  }
  const fmtPos = (p) => `${Math.abs(p.lat).toFixed(1)}° ${p.lat < 0 ? "S" : "N"}, ${Math.abs(p.lon).toFixed(1)}° ${p.lon < 0 ? "W" : "E"}`;

  // The lines above the map for one night. c: combine() result or null; city: nearestCity(); gps: the first photo's
  // own GPS or null; count: photos used for the place; example: the built-in example says "The phone's GPS";
  // pending: photos of this night are still waiting or being read.
  function headline(c, city, gps, count, example = false, pending = false) {
    if (!c) return { headline: `No place found from these photos${pending ? " yet" : ""}.` };
    const where = !city ? `at ${fmtPos(c)}` : city.km <= c.radiusKm ? `near ${city.name}, ${city.country}`
      : `about ${Math.round(city.km / 10) * 10} km ${direction(city, c)} of ${city.name}, ${city.country}`;
    const out = { headline: `The stars place ${count === 1 ? "this photo" : "these photos"} ${where}.`, position: fmtPos(c),
      radius: `Usually right to about ${Math.round(c.radiusKm / 5) * 5} km.` };
    if (gps) {
      const d = distKm(gps, c), who = example ? "The phone's GPS" : "Your phone's GPS";
      out.check = d <= c.radiusKm ? `✓ ${who} recorded a spot ${Math.round(d)} km from here.`
        : `${who} recorded a spot ${Math.round(d)} km from here. Add more photos from the same night.`;
    }
    if (count <= 2) out.hint = "Add 2 or more photos from the same night for a better result.";
    return out;
  }

  // Summary of the photo list of one night, and the progress line.
  const photosLine = (used, total, pending) => (pending ? "Photos"
    : `${used === total ? "" : used + " of "}${total} photo${total === 1 ? "" : "s"} used`);
  const reading = (n, m) => `Reading photo ${n} of ${m}`;

  const fmtDay = (local) => {   // the photo's own calendar date ("14 June 2026"), not the date where the browser is
    const [y, m, d] = local.slice(0, 10).split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  };
  const RETICLE_PX = 9;   // the reticle's ticks end this far from the answer on the page's map (CSS px)

  // One night of page rows -> everything its answer block shows; the page only writes it out (spec 8, 10.2).
  // Refused files (not a photo, too large) are listed but are not photos of the night, so they are not counted.
  // A photo that disagrees (outlier) counts as a photo, but not as used. opts: cities (rows of data/earth/cities.json),
  // example (the built-in example says "The phone's GPS").
  const REFUSED = ["bad_file", "too_large"];
  function night(rows, { cities = null, example = false } = {}) {
    const fixes = rows.filter((r) => r.result && r.result.status === "fix").map((r) => r.result);
    const c = fixes.length ? combine(fixes) : null, outliers = c ? c.outliers : [];
    const first = (k) => (rows.find((r) => r.result && r.result[k]) || { result: {} }).result[k] || null;
    const isUsed = (r) => !!r.result && r.result.status === "fix" && !outliers.includes(r.result);
    const gps = first("gps"), local = first("local"), pending = rows.some((r) => !r.result), used = fixes.length - outliers.length;
    const total = rows.filter((r) => !(r.result && REFUSED.includes(r.result.status))).length;
    const h = headline(c, c && nearestCity(c.lat, c.lon, cities), gps, used, example, pending);
    const lat = c && c.lat.toFixed(2), lon = c && c.lon.toFixed(2);
    return { c, outliers, used, total, pending, gps, local,
      day: local ? fmtDay(local) : "",
      headline: c || rows.some((r) => r.result) ? h.headline : "",   // no sentence before the first answer of this night
      position: h.position || "", radius: h.radius || "", check: h.check || "", hint: h.hint || "",
      // map window: half-height 4 x the larger of the radius and the GPS distance; 16 to 40 degrees across, 2:1.
      // 16 at least: a closer crop of the 2048 px day.jpg blurs the coastline and the place is lost
      map: c && { lat: c.lat, lon: c.lon, r: c.radiusKm, span: Math.min(40, Math.max(16, 16 * Math.max(c.radiusKm, gps ? distKm(gps, c) : 0) / (R * DEG))) },
      osm: c ? `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=7/${lat}/${lon}` : "",
      rows: rows.map((r) => ({ row: r, used: isUsed(r), retry: !!r.result && r.result.status === "error",
        mark: !r.result ? (r.state === "reading" ? "…" : "·") : isUsed(r) ? "✓" : "!",
        text: describe(r.result || { status: r.state }, outliers.includes(r.result)) })),
      summary: photosLine(used, total, pending),
      open: pending || rows.some((r) => r.result && !isUsed(r)) };   // the list until the person opens or closes it
  }

  // ---- the photo list and its queue: one request at a time, in order. No DOM and no fetch: the page passes
  // send(file, signal) -> Promise of a result, and onChange(), which runs after every change of the list.
  const MAX_BYTES = 30 * 1024 * 1024, PHOTO = /\.(heic|heif|jpe?g|png)$/i;
  function photoQueue(send, onChange) {
    const rows = [], queue = [];
    let running = false, gen = 0, nextId = 1, n = 0, m = 0, current = null;
    const finish = (row, result) => Object.assign(row, { state: "done", result, utc: result.utc });
    const enqueue = (row) => { Object.assign(row, { state: "waiting", result: null }); queue.push(row); m++; };

    function add(files) {   // returns the names of files that were already in the list
      const again = [];
      for (const file of files) {
        if (rows.some((r) => r.name === file.name && r.size === file.size)) { again.push(file.name); continue; }
        const row = { id: nextId++, name: file.name, size: file.size, file };
        rows.push(row);
        if (!PHOTO.test(file.name)) finish(row, { status: "bad_file" });
        else if (file.size > MAX_BYTES) finish(row, { status: "too_large" });
        else enqueue(row);
      }
      onChange();   // every row shows before the first request starts
      pump();
      return again;
    }

    async function pump() {
      if (running) return;   // one loop only
      running = true;
      for (let row; (row = queue.shift());) {
        const g = gen, ctrl = new AbortController(), timer = setTimeout(() => ctrl.abort(), 75e3);   // every wait ends
        row.state = "reading"; n++; current = ctrl; onChange();
        let result = null;
        try { result = await send(row.file, ctrl.signal); } catch { /* network, timeout or removed: below */ }
        clearTimeout(timer);
        if (g !== gen) continue;   // the photos were removed meanwhile: drop this answer
        finish(row, result && result.status ? result : { status: "error" });
        onChange();
      }
      running = false; n = m = 0; onChange();
    }

    function retry(row) {   // "Try again": the same File object goes to the end of the queue
      if (!rows.includes(row) || !row.result || row.result.status !== "error") return;
      enqueue(row); onChange(); pump();
    }
    function clear() {      // "Remove my photos": returns the rows, so that Undo can bring them back
      gen++; if (current) current.abort();
      queue.length = 0; n = m = 0;
      return rows.splice(0);
    }
    function restore(copy) {   // results come back as they were; photos not read yet are read again
      for (const row of copy) { rows.push(row); if (!row.result) enqueue(row); }
      onChange(); pump();
    }
    return { rows, add, retry, clear, restore, progress: () => ({ n, m, active: m > 0 }) };
  }

  const api = { distKm, sessions, combine, circle, describe, nearestCity, headline, night, photosLine, reading, photoQueue, RETICLE_PX };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.StarFixCore = api;
})(typeof window !== "undefined" ? window : globalThis);
