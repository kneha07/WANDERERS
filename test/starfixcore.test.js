// Star Fix page maths and words (app/starfixcore.js): nights, the combined place, the error circle, the sentences.
// node --test test/starfixcore.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const C = require("../app/starfixcore.js");

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ""} ${a} vs ${b} (±${tol})`);

test("distKm: one degree along a meridian is 111.2 km, the far side of the Earth 20 015 km", () => {
  near(C.distKm({ lat: 0, lon: 0 }, { lat: 1, lon: 0 }), 111.19, 0.01);
  near(C.distKm({ lat: -38.5, lon: 145.2 }, { lat: 38.5, lon: -34.8 }), 20015.1, 0.1);
  assert.equal(C.distKm({ lat: 10, lon: 20 }, { lat: 10, lon: 20 }), 0);
});

test("sessions: sorted by time; photos 2 h apart make two nights; a photo without a time joins the newest night", () => {
  const a = { utc: "2026-06-14T08:20:51Z" }, b = { utc: "2026-06-14T08:10:50Z" }, c = { utc: "2026-06-14T10:21:00Z" }, d = {};
  assert.deepEqual(C.sessions([a, c, d, b]), [[b, a], [c, d]]);
  assert.deepEqual(C.sessions([d]), [[d]]);
  assert.deepEqual(C.sessions([]), []);
});

test("sessions: a gap of exactly 60 minutes stays in the night, 61 minutes starts a new one", () => {
  const t0 = { utc: "2026-06-14T08:00:00Z" }, t60 = { utc: "2026-06-14T09:00:00Z" }, t121 = { utc: "2026-06-14T10:01:00Z" };
  assert.deepEqual(C.sessions([t0, t60, t121]), [[t0, t60], [t121]]);
});

test("combine: one photo is the answer itself, usually right to 150 km", () => {
  const c = C.combine([{ lat: -38.78, lon: 145.34 }]);
  near(c.lat, -38.78, 1e-9); near(c.lon, 145.34, 1e-9);
  assert.equal(c.radiusKm, 150);
  assert.deepEqual(c.outliers, []);
});

test("combine: two photos meet in the middle; the radius is their distance from it, at least 50 km", () => {
  const c = C.combine([{ lat: 0, lon: 0 }, { lat: 0, lon: 2 }]);
  near(c.lat, 0, 1e-9); near(c.lon, 1, 1e-9);
  near(c.radiusKm, 111.19, 0.01);
  assert.equal(C.combine([{ lat: 0, lon: 0 }, { lat: 0, lon: 0.2 }]).radiusKm, 50);
  assert.deepEqual(C.combine([{ lat: 0, lon: 0 }, { lat: 0, lon: 20 }]).outliers, [], "two photos never outvote each other");
});

test("combine: one far photo among four hardly moves the answer and is not used", () => {
  const good = [{ lat: -38.5, lon: 145.2 }, { lat: -38.9, lon: 145.6 }, { lat: -38.2, lon: 144.8 }];
  const far = { lat: -33.9, lon: 151.2 };   // about 800 km away (Sydney)
  const all = C.combine([good[0], far, good[1], good[2]]), three = C.combine(good);
  assert.ok(C.distKm(all, three) < 50, `${C.distKm(all, three)} km`);
  assert.deepEqual(all.outliers, [far]);
  assert.deepEqual(three.outliers, []);
});

test("circle: n points, each the given distance from the centre within 1 %, also across 180 degrees and near a pole", () => {
  for (const [lat, lon, km] of [[-38.5, 145.2, 65], [0, 179.9, 150], [85, 0, 300]]) {
    const pts = C.circle(lat, lon, km);
    assert.equal(pts.length, 64);
    for (const p of pts) near(C.distKm(p, { lat, lon }), km, km * 0.01, `${lat},${lon}`);
  }
  assert.equal(C.circle(0, 0, 50, 8).length, 8);
});

const SAMPLE = require("../app/data/starfix-sample.json");
const PHILLIP_ISLAND = { lat: -38.5, lon: 145.2 };   // the only public true place; tests compare distances only

test("the example: four 14 June photos, the public GPS only, one night within 120 km of Phillip Island (A6, A15)", () => {
  assert.equal(SAMPLE.length, 4);
  for (const r of SAMPLE) assert.deepEqual(r.gps, PHILLIP_ISLAND, r.name);
  const nights = C.sessions(SAMPLE);
  assert.equal(nights.length, 1);
  const c = C.combine(nights[0]), d = C.distKm(c, PHILLIP_ISLAND);
  assert.ok(d < 120, `${d} km`);
  assert.ok(c.radiusKm >= 50 && c.radiusKm <= 150, `radius ${c.radiusKm} km`);
  assert.deepEqual(c.outliers, []);
});

const fix = (extra = {}) => ({ status: "fix", lat: -38.78, lon: 145.34, sky: { constellation: "Carina" }, warnings: [], ...extra });
const skyOnly = (missing) => ({ status: "sky_only", sky: { constellation: "Carina" }, missing });

test("describe: the exact row text of the design for every case (A14)", () => {
  assert.equal(C.describe(fix(), false), "Used · stars of Carina");
  assert.equal(C.describe(fix(), true), "Not used: it disagrees with the other photos");
  assert.equal(C.describe(skyOnly(["gravity", "time"])), "Stars recognised (Carina), but the file has no tilt data. Use the original iPhone file.");
  assert.equal(C.describe(skyOnly(["time"])), "Stars recognised (Carina), but the file has no time data. Use the original iPhone file.");
  assert.equal(C.describe(skyOnly(["rear_camera"])), "Stars recognised (Carina), but this camera is not supported. Use the main rear camera.");
  assert.equal(C.describe({ status: "no_solve", stars: 11 }), "Too few stars to recognise. Use a darker, clearer photo.");
  assert.equal(C.describe({ status: "bad_file" }), "This file is not a photo. Choose a .heic or .jpg file.");
  assert.equal(C.describe({ status: "too_large" }), "This file is too large (30 MB limit). Use the original photo.");
  assert.equal(C.describe({ status: "error" }), "Could not read this photo.");   // the row has a "Try again" button
  assert.equal(C.describe({ status: "waiting" }), "waiting");
  assert.equal(C.describe({ status: "reading" }), "reading");
});

test("describe: warnings are added to the row", () => {
  assert.equal(C.describe(fix({ warnings: ["zone_mismatch"] }), false),
    "Used · stars of Carina. The place does not match the photo's time zone. The file may be edited.");
  assert.equal(C.describe(fix({ warnings: ["untested_lens"] }), false), "Used · stars of Carina. Zoom or wide lens: the result may be less exact.");
  assert.equal(C.describe(fix({ warnings: ["zone_mismatch", "untested_lens"] }), true),
    "Not used: it disagrees with the other photos. The place does not match the photo's time zone. The file may be edited. Zoom or wide lens: the result may be less exact.");
  assert.equal(C.describe(fix({ warnings: ["small_photo"] }), false), "Used · stars of Carina. This photo is small. Use the original file for a better result.");
  assert.equal(C.describe({ status: "no_solve", stars: 9, warnings: ["small_photo"] }),
    "Too few stars to recognise. Use a darker, clearer photo. This photo is small. Use the original file for a better result.");
  assert.equal(C.describe({ ...skyOnly(["gravity", "time"]), warnings: ["small_photo"] }),
    "Stars recognised (Carina), but the file has no tilt data. Use the original iPhone file. This photo is small. Use the original file for a better result.");
});

const CITIES = require("../app/data/earth/cities.json");

test("nearestCity: the example place is 134 km from Geelong, the nearest of the 6204 listed cities", () => {
  const city = C.nearestCity(-39.02, 145.43, CITIES);
  assert.deepEqual([city.name, city.country], ["Geelong", "Australia"]);
  near(city.km, 134, 1);
  assert.equal(C.nearestCity(0, 0, []), null);
});

test("headline: the example reads as the design says, with the phone's GPS 61 km away", () => {
  const c = C.combine(SAMPLE), city = C.nearestCity(c.lat, c.lon, CITIES);
  assert.deepEqual(C.headline(c, city, SAMPLE[0].gps, 4, true), {
    headline: "The stars place these photos about 130 km south-east of Geelong, Australia.",
    position: "39.0° S, 145.4° E",
    radius: "Usually right to about 65 km.",
    check: "✓ The phone's GPS recorded a spot 61 km from here.",
  });
  assert.equal(C.headline(c, city, SAMPLE[0].gps, 4).check, "✓ Your phone's GPS recorded a spot 61 km from here.");
});

test("headline: near a city inside the circle, one photo, GPS outside the circle, no GPS, nothing found", () => {
  const one = C.combine([{ lat: -37.81, lon: 144.96 }]), city = C.nearestCity(one.lat, one.lon, CITIES);
  const h = C.headline(one, city, { lat: -36.0, lon: 144.96 }, 1);
  assert.equal(h.headline, "The stars place this photo near Melbourne, Australia.");
  assert.equal(h.position, "37.8° S, 145.0° E");
  assert.equal(h.radius, "Usually right to about 150 km.");
  assert.equal(h.check, "Your phone's GPS recorded a spot 201 km from here. Add more photos from the same night.");
  assert.equal(h.hint, "Add 2 or more photos from the same night for a better result.");
  assert.equal(C.headline(one, city, null, 1).check, undefined);
  assert.equal(C.headline({ lat: 47.6, lon: -122.3, radiusKm: 50 }, null, null, 3).headline, "The stars place these photos at 47.6° N, 122.3° W.");
  assert.deepEqual(C.headline(null, null, null, 0), { headline: "No place found from these photos." });
  assert.deepEqual(C.headline(null, null, null, 0, false, true), { headline: "No place found from these photos yet." }, "only while photos are read");
});

test("photosLine and reading: the photo list summary and the progress line", () => {
  assert.equal(C.photosLine(4, 4, false), "4 photos used");
  assert.equal(C.photosLine(3, 4, false), "3 of 4 photos used");
  assert.equal(C.photosLine(1, 1, false), "1 photo used");
  assert.equal(C.photosLine(0, 1, false), "0 of 1 photo used");
  assert.equal(C.photosLine(1, 4, true), "Photos");
  assert.equal(C.reading(2, 4), "Reading photo 2 of 4");
});

// Words the person must never read (design 10.0 rule 5). "Star Fix", the name, is the only place "fix" may appear.
const FORBIDDEN = /plate|solve|zenith|session|outlier|exif|makernote|gravity|fix/i;
const clean = (s) => !FORBIDDEN.test(String(s).replace(/Star Fix/g, ""));

test("no sentence from starfixcore holds a technical word (A14)", () => {
  const texts = [];
  for (const r of [fix(), fix({ warnings: ["zone_mismatch", "untested_lens", "small_photo"] }), skyOnly(["gravity"]), skyOnly(["time"]), skyOnly(["rear_camera"]),
    { status: "no_solve" }, { status: "bad_file" }, { status: "too_large" }, { status: "error" }, { status: "waiting" }, { status: "reading" }])
    texts.push(C.describe(r, false), C.describe(r, true));
  const c = C.combine(SAMPLE), city = C.nearestCity(c.lat, c.lon, CITIES);
  for (const [gps, n, ex] of [[SAMPLE[0].gps, 4, true], [{ lat: 0, lon: 0 }, 1, false], [null, 2, false]]) texts.push(...Object.values(C.headline(c, city, gps, n, ex)));
  texts.push(...Object.values(C.headline(c, null, null, 3)), ...Object.values(C.headline(null, null, null, 0)));
  texts.push(C.photosLine(3, 4, false), C.photosLine(4, 4, false), C.photosLine(1, 4, true), C.reading(1, 4));
  for (const t of texts) assert.ok(clean(t), t);
  assert.ok(!clean("Fixed"), "the check itself works");
});

// ---- the photo list and its queue (the page gives it fetch as `send`; here a fake server answers by hand) ----
function fakeServer() {
  const calls = [];
  const send = (file, signal) => new Promise((resolve, reject) => {
    calls.push({ file, signal, resolve, reject });
    signal.addEventListener("abort", () => reject(new Error("aborted")));
  });
  return { calls, send };
}
const file = (name, size = 1000) => ({ name, size });
const tick = () => new Promise((r) => setImmediate(r));

test("photoQueue: every row shows at once, one request at a time, in order; photos added during a run join the end (U1, U2)", async () => {
  const s = fakeServer(), seen = [], q = C.photoQueue(s.send, () => seen.push(q.rows.map((r) => r.state).join()));
  const a = file("a.heic"), b = file("b.heic"), c = file("c.jpg");
  q.add([a, b]);
  assert.equal(seen[0], "waiting,waiting", "both rows exist before the first request");
  assert.deepEqual(q.rows.map((r) => r.state), ["reading", "waiting"]);
  assert.deepEqual(q.progress(), { n: 1, m: 2, active: true });
  q.add([c]);
  assert.equal(s.calls.length, 1, "never a second request in flight");
  s.calls[0].resolve(fix({ utc: "2026-06-14T08:20:51Z" })); await tick();
  assert.equal(s.calls[1].file, b);
  assert.deepEqual(q.progress(), { n: 2, m: 3, active: true });
  s.calls[1].resolve({ status: "no_solve", stars: 11 }); await tick();
  assert.equal(s.calls[2].file, c);
  s.calls[2].resolve({ status: "bad_file" }); await tick();
  assert.deepEqual(q.rows.map((r) => [r.state, r.result.status]), [["done", "fix"], ["done", "no_solve"], ["done", "bad_file"]]);
  assert.equal(q.rows[0].utc, "2026-06-14T08:20:51Z");
  assert.equal(q.progress().active, false);
});

test("photoQueue: the same file (name and size) is added once, also while it still waits (U2)", async () => {
  const q = C.photoQueue(async () => fix(), () => {});   // a server that answers at once
  q.add([file("a.heic"), file("b.heic")]);
  assert.deepEqual(q.add([file("b.heic"), file("a.heic", 2000), file("a.heic")]), ["b.heic", "a.heic"], "the duplicates, for the status line");   // b still waits
  assert.deepEqual(q.rows.map((r) => r.name + " " + r.size), ["a.heic 1000", "b.heic 1000", "a.heic 2000"]);
  await tick();
  assert.deepEqual(q.rows.map((r) => r.state), ["done", "done", "done"]);
});

test("photoQueue: no image extension or above 30 MB gets its row at once, with no request (U8)", () => {
  const s = fakeServer(), q = C.photoQueue(s.send, () => {});
  q.add([file("notes.txt"), file("big.heic", 31 * 1024 * 1024), file("ok.HEIC")]);
  assert.deepEqual(q.rows.map((r) => r.result && r.result.status), ["bad_file", "too_large", null]);
  assert.deepEqual(s.calls.map((c) => c.file.name), ["ok.HEIC"]);
  s.calls[0].resolve(fix());
});

test("photoQueue: a failed request ends as 'error'; Try again sends the same File object again, nothing else does (U3)", async () => {
  const s = fakeServer(), q = C.photoQueue(s.send, () => {}), a = file("a.heic");
  q.add([a]);
  s.calls[0].reject(new TypeError("Failed to fetch")); await tick();
  const row = q.rows[0];
  assert.equal(row.result.status, "error");
  q.retry(row);
  assert.equal(row.state, "reading");
  assert.equal(s.calls[1].file, a);
  s.calls[1].resolve({ status: "no_solve", stars: 3 }); await tick();
  q.retry(row);
  assert.equal(s.calls.length, 2, "only an error row can be tried again");
});

test("photoQueue: clear() stops the run and returns the rows; restore() brings results back without a new request (U7)", async () => {
  const s = fakeServer(), q = C.photoQueue(s.send, () => {});
  q.add([file("a.heic"), file("b.heic"), file("c.heic")]);
  s.calls[0].resolve(fix()); await tick();               // a done, b being read, c waiting
  const copy = q.clear();
  assert.equal(s.calls[1].signal.aborted, true);
  assert.deepEqual([q.rows.length, q.progress().active], [0, false]);
  await tick();
  assert.equal(s.calls.length, 2, "nothing more is sent");
  q.restore(copy);
  assert.deepEqual(q.rows.map((r) => r.name), ["a.heic", "b.heic", "c.heic"]);
  assert.equal(q.rows[0].result.status, "fix");
  assert.deepEqual(s.calls.slice(2).map((c) => c.file.name), ["b.heic"], "only the unfinished photos are read again");
  s.calls[2].resolve(fix()); await tick();
  s.calls[3].resolve(fix()); await tick();
  assert.deepEqual(q.rows.map((r) => r.state), ["done", "done", "done"]);
});

test("photoQueue: restore() right after clear() drops the old answer and reads the photo again once", async () => {
  const s = fakeServer(), q = C.photoQueue(s.send, () => {});
  q.add([file("a.heic")]);
  q.restore(q.clear());
  await tick();
  assert.equal(s.calls.length, 2);
  assert.equal(q.rows[0].state, "reading");
  s.calls[1].resolve(fix()); await tick();
  assert.equal(q.rows[0].result.status, "fix");
});

// ---- the page: app/starfix.html words and controls (behaviour is checked in a browser, see the build report) ----
const fs = require("node:fs"), path = require("node:path");
const page = (f) => fs.readFileSync(path.join(__dirname, "..", "app", f), "utf8");
function visibleText(html) {   // text between tags, plus what screen readers read from attributes; no head, scripts, comments
  const body = html.replace(/<head>[\s\S]*?<\/head>/, "").replace(/<script[\s\S]*?<\/script>/g, "").replace(/<!--[\s\S]*?-->/g, "");
  const attrs = [...body.matchAll(/\b(?:aria-label|title|alt|placeholder)="([^"]*)"/g)].map((m) => m[1]);
  return (body.replace(/<[^>]+>/g, " ") + " " + attrs.join(" ")).replace(/\s+/g, " ");
}

test("starfix.html: the exact words of the design, and no technical word (A14)", () => {
  const text = visibleText(page("starfix.html"));
  for (const s of ["Star Fix", "Find where you were, from the stars in your photo.", "Choose star photos", "Add more photos", "or drop them here",
    "Your photos stay on this computer.", "Which photos work?",
    "Night-sky photos from an iPhone, with many stars. Use the original file (AirDrop, cable or iCloud). Chat apps remove the data that this needs.",
    "To use your own photos, start WANDERERS on a computer (start.cmd).", "How does this work?",
    "The app recognises the stars in your photo.", "Your phone stored which way was down and the exact time.",
    "Together they give the one place on Earth where those stars were overhead.",
    "Stars give the place to about 50 to 150 km. GPS is 10 000 times better. Navigators worked like this before GPS.",
    "Remove my photos", "Example ·", "stars", "phone GPS", "Open in OpenStreetMap", "Drop to add", "Photos removed.", "Undo", "Try again", "Already added:"])
    assert.ok(text.includes(s), s);
  assert.ok(clean(text), text.match(new RegExp(`.{0,40}(${FORBIDDEN.source}).{0,40}`, "i"))?.[0]);
});

test("starfix.html: one primary button, native controls, no confirm dialog and no history entries (A16, U7)", () => {
  const html = page("starfix.html"), js = page("starfix.js");
  assert.equal((html.match(/btn-primary/g) || []).length, 1);
  assert.match(html, /<input type="file" id="files" multiple accept="\.heic,\.heif,\.jpg,\.jpeg,image\/heic,image\/jpeg">/);
  assert.match(html, /<progress /);
  assert.match(html, /aria-live="polite"/);
  assert.doesNotMatch(js, /confirm\(|alert\(|pushState|location\.hash/);
  assert.doesNotMatch(page("sw.js"), /starfix/, "the offline list is for the Sky Compass only");
});

test("night: refused files are listed but not counted; a photo that disagrees counts, but is not used (L-c)", () => {
  const near = (lat, lon, utc) => ({ result: { status: "fix", lat, lon, utc, sky: { constellation: "Carina" }, warnings: [] }, utc });
  const rows = [near(-38.5, 145.2, "2026-06-14T08:10:00Z"), near(-38.9, 145.6, "2026-06-14T08:11:00Z"), near(-33.9, 151.2, "2026-06-14T08:12:00Z"),
    { result: { status: "no_solve", stars: 3 } }, { result: { status: "bad_file" } }, { result: { status: "too_large" } }];
  const n = C.night(rows);
  assert.deepEqual([n.used, n.total, n.pending, n.outliers.length], [2, 4, false, 1]);
  assert.equal(C.photosLine(n.used, n.total, n.pending), "2 of 4 photos used");
  assert.equal(C.night([rows[0], rows[4]]).total, 1);
  assert.equal(C.night([rows[0], { state: "waiting" }]).pending, true);
  assert.equal(C.night([rows[4]]).c, null);
});

// ---- night(rows, {cities, example}): everything one answer block shows; the page only writes it out ----
const row = (result, extra = {}) => ({ result, utc: result && result.utc, state: result ? "done" : "waiting", name: "x.heic", ...extra });
const at = (lat, lon, utc) => ({ status: "fix", lat, lon, utc, sky: { constellation: "Carina" }, warnings: [] });

test("night: the example block, as one call (A6, A11 words)", () => {
  const v = C.night(SAMPLE.map((s) => row(s)), { cities: CITIES, example: true });
  assert.equal(v.day, "14 June 2026");
  assert.equal(v.headline, "The stars place these photos about 130 km south-east of Geelong, Australia.");
  assert.deepEqual([v.position, v.radius, v.check, v.hint], ["39.0° S, 145.4° E", "Usually right to about 65 km.", "✓ The phone's GPS recorded a spot 61 km from here.", ""]);
  assert.deepEqual([v.summary, v.open], ["4 photos used", false]);
  assert.equal(v.osm, "https://www.openstreetmap.org/?mlat=-39.02&mlon=145.41#map=7/-39.02/145.41");
  assert.deepEqual(v.rows.map((x) => [x.mark, x.text, x.retry]), SAMPLE.map((s) => ["✓", `Used · stars of ${s.sky.constellation}`, false]));
});

test("night: the map window is 16 degrees across at least, 40 at most, else 4 x the larger of radius and GPS distance", () => {
  const v = C.night(SAMPLE.map((s) => row(s)), { cities: CITIES });
  assert.equal(v.map.span, 16, "65 km and a GPS 61 km away: the 16 degree minimum keeps the coastline readable");
  near(v.map.r, 65.5, 0.1);
  const pxPerDeg = 608 / v.map.span, circlePx = v.map.r / 111.195 * pxPerDeg;   // the circle radius on a 608 px wide map
  assert.ok(circlePx >= 2 * C.RETICLE_PX, `circle ${circlePx.toFixed(1)} px vs reticle ${C.RETICLE_PX} px`);
  const one = C.night([row(at(-38.5, 145.2, "2026-06-14T08:00:00Z"))]);   // one photo: radius 150 km, no GPS
  near(one.map.span, 16 * 150 / 111.195, 0.01);
  const far = C.night([row({ ...at(-38.5, 145.2, "2026-06-14T08:00:00Z"), gps: { lat: -20, lon: 120 } })]);   // GPS thousands of km away
  assert.equal(far.map.span, 40);
  assert.equal(C.night([row({ status: "no_solve", stars: 3 })]).map, null, "no place, no map");
});

test("night: each row says used or not, with a mark and words; only an error row offers Try again", () => {
  const good = [at(-38.5, 145.2, "2026-06-14T08:10:00Z"), at(-38.9, 145.6, "2026-06-14T08:11:00Z")], far = at(-33.9, 151.2, "2026-06-14T08:12:00Z");
  const v = C.night([row(good[0]), row(far), row(good[1]), row({ status: "error" }), row(null), row(null, { state: "reading" }), row({ status: "bad_file" })]);
  assert.deepEqual(v.rows.map((x) => [x.used, x.mark, x.retry]),
    [[true, "✓", false], [false, "!", false], [true, "✓", false], [false, "!", true], [false, "·", false], [false, "…", false], [false, "!", false]]);
  assert.equal(v.rows[1].text, "Not used: it disagrees with the other photos");
  assert.deepEqual([v.used, v.total, v.summary], [2, 6, "Photos"]);
});

test("night: the list is open while photos are read or one was not used, else closed; the headline waits for a first answer", () => {
  const ok = row(at(-38.5, 145.2, "2026-06-14T08:10:00Z"));
  assert.deepEqual([C.night([ok, row(null)]).open, C.night([ok]).open, C.night([ok, row({ status: "no_solve" })]).open], [true, false, true]);
  assert.equal(C.night([row(null), row(null, { state: "reading" })]).headline, "", "no sentence before the first answer");
  assert.equal(C.night([row({ status: "no_solve" }), row(null)]).headline, "No place found from these photos yet.");
  assert.equal(C.night([row({ status: "no_solve" })]).headline, "No place found from these photos.");
});
