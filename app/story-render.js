/* WANDERERS story cards and sky drawings: pure geometry and layout, shared by the homepage constellation cards,
 * Space Camera and Story Studio. No DOM, no network: browser (window.StoryRender) and Node (module.exports).
 *
 * Honesty rules built in:
 *  - Constellation figures are drawn from real J2000 star positions (data/constellations.json), but on a story card
 *    they are an illustration: the caller must label them "Constellation guide · illustration".
 *  - Sky labels on a camera view are ESTIMATES from the phone's compass, tilt, clock and location (Sky Compass maths in
 *    sky.js). They are never "identified" from the photo. estimateNote() is the wording to show beside them.
 *  - A story's date stamp is a day only. Coordinates never go on a card. */
(function (root) {
  "use strict";
  const D2R = Math.PI / 180, R2D = 180 / Math.PI;
  const wrap180 = (d) => ((((d + 180) % 360) + 360) % 360) - 180;

  /* ---------- sky shapes ---------- */
  /** Gnomonic (tangent-plane) projection about (ra0, dec0), in degrees on the sky. East is to the LEFT, as the sky
   *  looks from the ground. Returns null for points 90° or more from the centre. */
  function gnomonic(ra, dec, ra0, dec0) {
    const a = ra * D2R, d = dec * D2R, a0 = ra0 * D2R, d0 = dec0 * D2R;
    const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
    if (cosc <= 0.05) return null;
    const x = (Math.cos(d) * Math.sin(a - a0)) / cosc, y = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc;
    return { x: -x * R2D, y: y * R2D };
  }
  /** A constellation's stick figure fitted into a size×size box (y down, padding pad). lines: [[ra,dec,ra,dec,…],…]. */
  function constellationFigure(c, size, pad = 0.1) {
    const segs = (c.lines || []).map((l) => { const pts = []; for (let i = 0; i + 1 < l.length; i += 2) pts.push(gnomonic(l[i], l[i + 1], c.ra, c.dec)); return pts.filter(Boolean); }).filter((p) => p.length > 1);
    const all = segs.flat();
    if (!all.length) return { paths: [], points: [], scale: 0 };
    const xs = all.map((p) => p.x), ys = all.map((p) => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const span = Math.max(maxX - minX, maxY - minY) || 1, inner = size * (1 - 2 * pad), k = inner / span;
    const ox = (size - (maxX - minX) * k) / 2, oy = (size - (maxY - minY) * k) / 2;
    const P = (p) => ({ x: ox + (p.x - minX) * k, y: oy + (maxY - p.y) * k });
    const paths = segs.map((s) => s.map(P));
    const seen = new Map();
    paths.flat().forEach((p) => seen.set(`${p.x.toFixed(1)},${p.y.toFixed(1)}`, p));
    return { paths, points: [...seen.values()], scale: k, spanDeg: span };
  }

  /* ---------- card layout ---------- */
  /** Source rectangle that fills dst like CSS object-fit: cover. */
  function coverFit(sw, sh, dw, dh) {
    const s = Math.max(dw / sw, dh / sh), w = dw / s, h = dh / s;
    return { sx: (sw - w) / 2, sy: (sh - h) / 2, sw: w, sh: h };
  }
  /** Greedy word wrap with a width measurer; at most maxLines (the last line ends with … when cut). */
  function wrapText(measure, text, maxWidth, maxLines = 6) {
    const words = String(text || "").split(/\s+/).filter(Boolean), lines = [];
    let cur = "";
    for (const w of words) {
      const t = cur ? cur + " " + w : w;
      if (measure(t) <= maxWidth || !cur) cur = t; else { lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    if (lines.length > maxLines) { const keep = lines.slice(0, maxLines); keep[maxLines - 1] = keep[maxLines - 1].replace(/\s*\S*$/, "") + "…"; return keep; }
    return lines;
  }
  /** Day-only stamp for a card (never a time or a place). */
  const dayStamp = (date) => { const d = date instanceof Date ? date : new Date(date); return isNaN(d) ? "" : d.toISOString().slice(0, 10); };

  /* Story templates: 1080×1920 (9:16). Colours are fixed on the card so it looks the same in either site theme. */
  const W = 1080, H = 1920;
  const TEMPLATES = {
    discovery: { name: "Discovery card", photo: { x: 0, y: 0, w: W, h: 1240 }, panel: { y: 1180, h: 740 }, bg: "#0B1422", ink: "#F1F5FA", soft: "#B5C9DE", accent: "#8AB6EF", radius: 0 },
    night: { name: "Night sky", photo: { x: 0, y: 0, w: W, h: H }, panel: { y: 1340, h: 580, scrim: true }, bg: "#050B14", ink: "#F1F5FA", soft: "#C9D8E8", accent: "#F2B866", radius: 0 },
    report: { name: "Mission report", photo: { x: 72, y: 300, w: W - 144, h: 980 }, panel: { y: 1330, h: 590 }, bg: "#F6F8FB", ink: "#172B45", soft: "#52677D", accent: "#2864C5", radius: 36 },
  };

  /* ---------- estimated sky labels on a camera view ---------- */
  /** Phone orientation from a DeviceOrientationEvent, for a phone held upright with the back camera facing out.
   *  heading: degrees from north (iOS webkitCompassHeading, else 360 − alpha when the event is absolute);
   *  pitch: camera elevation above the horizon (beta 90° = level). Returns null when there is no usable heading. */
  function pose(e) {
    if (!e || e.beta == null) return null;
    let heading = null;
    if (typeof e.webkitCompassHeading === "number" && !isNaN(e.webkitCompassHeading)) heading = e.webkitCompassHeading;
    else if (e.absolute && typeof e.alpha === "number") heading = (360 - e.alpha) % 360;
    if (heading == null) return null;
    return { heading, pitch: e.beta - 90, roll: e.gamma || 0 };
  }
  /** Screen position of an object at (az, alt) for a camera pointing at (heading, pitch) with horizontal field of
   *  view hfov (deg), on a w×h view. Simple pinhole model, roll ignored. null when off screen or behind. */
  function skyToScreen(obj, p, hfov, w, h) {
    const dAz = wrap180(obj.az - p.heading), dAlt = obj.alt - p.pitch;
    if (Math.abs(dAz) >= 89 || Math.abs(dAlt) >= 89) return null;
    const fx = (w / 2) / Math.tan((hfov / 2) * D2R), x = w / 2 + Math.tan(dAz * D2R) * fx, y = h / 2 - Math.tan(dAlt * D2R) * fx;
    if (x < -20 || x > w + 20 || y < -20 || y > h + 20) return null;
    return { x, y };
  }
  /** Same idea with the Sky Compass orientation engine (orient.js): `pt` is Fusion.pointing(), the camera's forward,
   *  up and right vectors in the east-north-up frame, so roll is included. `screenAngle` is screen.orientation.angle
   *  (90 = phone turned anticlockwise into landscape): the picture's "up" is then the phone's right-hand side.
   *  `nudge` (deg) turns the labels by hand, like the old slider. null when off screen or behind the camera. */
  function projectPointing(obj, pt, hfov, w, h, screenAngle, nudge) {
    if (!pt || !pt.forward) return null;
    const az = (obj.az - (nudge || 0)) * D2R, alt = obj.alt * D2R;
    const v = [Math.sin(az) * Math.cos(alt), Math.cos(az) * Math.cos(alt), Math.sin(alt)];
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const a = (screenAngle || 0) * D2R, c = Math.cos(a), s = Math.sin(a);
    const up = pt.up.map((x, i) => c * x + s * pt.right[i]), right = pt.right.map((x, i) => c * x - s * pt.up[i]);
    const z = dot(v, pt.forward);
    if (z < 0.02) return null;
    const fx = (w / 2) / Math.tan((hfov / 2) * D2R), x = w / 2 + fx * dot(v, right) / z, y = h / 2 - fx * dot(v, up) / z;
    if (x < -20 || x > w + 20 || y < -20 || y > h + 20) return null;
    return { x, y };
  }
  const estimateNote = (accuracyDeg) =>
    `Estimated positions from your phone’s compass, tilt, clock and location (Sky Compass maths). Not identified from the photo; phone compasses can be off by ${accuracyDeg || "10–30"}° or more.`;

  const api = { gnomonic, constellationFigure, coverFit, wrapText, dayStamp, TEMPLATES, W, H, pose, skyToScreen, projectPointing, estimateNote, wrap180 };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.StoryRender = api;
})(typeof window !== "undefined" ? window : globalThis);
