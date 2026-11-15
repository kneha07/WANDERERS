// Story cards and sky drawing geometry (app/story-render.js), and the Story Studio's privacy rules.
// node --test test/story-render.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const R = require("../app/story-render.js");
const Sky = require("../app/sky.js");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);

test("gnomonic: centre maps to 0,0; east is to the left; 1° north is ~1° up", () => {
  const c = R.gnomonic(83.8, -5.4, 83.8, -5.4);
  near(c.x, 0, 1e-9, "x"); near(c.y, 0, 1e-9, "y");
  assert.ok(R.gnomonic(84.8, -5.4, 83.8, -5.4).x < 0, "larger RA is to the left");
  near(R.gnomonic(83.8, -4.4, 83.8, -5.4).y, 1, 0.001, "1° north");
  assert.equal(R.gnomonic(263.8, 5.4, 83.8, -5.4), null, "far side is not drawn");
});

test("constellation figures: real Orion fits the box, keeps its shape, Betelgeuse above Rigel", () => {
  const list = JSON.parse(read("app/data/constellations.json")).list;
  const ori = list.find((c) => c.id === "Ori");
  const f = R.constellationFigure(ori, 200, 0.1);
  assert.ok(f.paths.length > 3);
  for (const p of f.paths.flat()) { assert.ok(p.x >= 19.9 && p.x <= 180.1 && p.y >= 19.9 && p.y <= 180.1, JSON.stringify(p)); }
  // Betelgeuse (RA 88.79, Dec +7.41) and Rigel (RA 78.63, Dec -8.20) are vertices of the figure
  const g = (ra, dec) => { const q = R.gnomonic(ra, dec, ori.ra, ori.dec); return q; };
  assert.ok(g(88.79, 7.41).y > g(78.63, -8.2).y, "Betelgeuse is north of Rigel");
  assert.ok(f.spanDeg > 15 && f.spanDeg < 40, `Orion spans ${f.spanDeg}°`);
  for (const c of list) assert.doesNotThrow(() => R.constellationFigure(c, 120), c.id);
});

test("coverFit and wrapText", () => {
  const a = R.coverFit(1920, 1080, 1080, 1920);              // landscape photo into a portrait card
  near(a.sh, 1080, 1e-6, "uses full height"); near(a.sw, 607.5, 1e-6, "crops width"); near(a.sx, 656.25, 1e-6, "centred");
  const m = (s) => s.length * 10;
  assert.deepEqual(R.wrapText(m, "one two three four", 100), ["one two", "three four"]);
  assert.deepEqual(R.wrapText(m, "one two three four", 90), ["one two", "three", "four"]);
  const cut = R.wrapText(m, "a b c d e f g h i j k l", 30, 2);
  assert.equal(cut.length, 2); assert.match(cut[1], /…$/);
  assert.deepEqual(R.wrapText(m, "", 100), []);
});

test("cards carry a day only: no time, no place", () => {
  assert.equal(R.dayStamp(new Date("2026-11-15T23:59:59Z")), "2026-11-15");
  assert.equal(R.dayStamp("not a date"), "");
  for (const t of Object.values(R.TEMPLATES)) { assert.ok(t.photo.w <= R.W && t.panel.y + t.panel.h <= R.H + 1, t.name); }
});

test("pose: iOS compass heading, absolute alpha, or nothing", () => {
  assert.deepEqual(R.pose({ alpha: 10, beta: 120, gamma: 0, webkitCompassHeading: 200 }), { heading: 200, pitch: 30, roll: 0 });
  assert.deepEqual(R.pose({ alpha: 90, beta: 90, gamma: 5, absolute: true }), { heading: 270, pitch: 0, roll: 5 });
  assert.equal(R.pose({ alpha: 90, beta: 90, gamma: 0 }), null, "relative alpha is not a compass heading");
  assert.equal(R.pose(null), null);
});

test("skyToScreen: straight ahead is the centre; left/right/up follow the sky; behind is hidden", () => {
  const p = { heading: 180, pitch: 30 }, W = 1000, Hh = 1500;
  const c = R.skyToScreen({ az: 180, alt: 30 }, p, 60, W, Hh);
  near(c.x, 500, 1e-9, "x"); near(c.y, 750, 1e-9, "y");
  assert.ok(R.skyToScreen({ az: 190, alt: 30 }, p, 60, W, Hh).x > 500, "east of the heading is to the right (facing south)");
  assert.ok(R.skyToScreen({ az: 180, alt: 40 }, p, 60, W, Hh).y < 750, "higher is up");
  const edge = R.skyToScreen({ az: 210, alt: 30 }, p, 60, W, Hh);
  near(edge.x, 1000, 1e-6, "half the field of view lands on the edge");
  assert.equal(R.skyToScreen({ az: 0, alt: 30 }, p, 60, W, Hh), null);
  assert.equal(R.skyToScreen({ az: 179, alt: -60 }, p, 60, W, Hh), null);
  // wrap around north: heading 350, object at az 5 is 15° to the right
  assert.ok(R.skyToScreen({ az: 5, alt: 0 }, { heading: 350, pitch: 0 }, 60, W, Hh).x > 500);
});

test("labels use the Sky Compass maths: a star straight ahead lands at the centre", () => {
  const date = new Date("2026-11-15T06:00:00Z"), lat = 47.6062, lon = -122.3321;
  const vega = Sky.observe({ ra: 279.2347, dec: 38.7837 }, date, lat, lon);
  const c = R.skyToScreen(vega, { heading: vega.az, pitch: vega.alt }, 63, 1080, 1920);
  if (vega.alt > 0) { near(c.x, 540, 1e-6, "x"); near(c.y, 960, 1e-6, "y"); } else assert.equal(c.x, 540);
});

test("the estimate note never claims identification", () => {
  const n = R.estimateNote();
  assert.match(n, /Estimated/); assert.match(n, /Not identified from the photo/); assert.match(n, /10–30° or more/);
});

test("Story Studio privacy: camera, sensors and location only on tap; nothing uploaded; no place on the card", () => {
  const js = read("app/stories.js"), code = js.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const inFn = (name, call) => { const i = code.indexOf(`function ${name}(`), j = code.indexOf(call); return i >= 0 && j > i && j < code.indexOf("\n  }\n", i) + 4; };
  assert.equal((code.match(/getUserMedia\(/g) || []).length, 1); assert.ok(inFn("openCamera", "getUserMedia("), "camera only in openCamera");
  assert.equal((code.match(/getCurrentPosition\(/g) || []).length, 1); assert.ok(inFn("startSky", "getCurrentPosition("), "location only in startSky");
  assert.ok(inFn("startSky", "requestPermission()"), "orientation permission only in startSky");
  assert.match(code, /\$\("openCam"\)\.onclick = openCamera/); assert.match(code, /\$\("skyLabels"\)\.onclick/);
  assert.doesNotMatch(code, /fetch\(\s*["'`]https?:|XMLHttpRequest|sendBeacon|method:\s*["']POST/i, "nothing is sent anywhere");
  assert.doesNotMatch(code, /localStorage\.setItem/, "no location or photo in localStorage");
  assert.doesNotMatch(code, /fillText\([^)]*(lat|lon|loc)\b/, "coordinates are never drawn on a card");
  assert.match(code, /Sky labels estimated from phone sensors, not identified in the photo/);
  assert.match(code, /constellation guide, illustration only/);
  assert.match(read("app/stories.html"), /Private by default/);
});
