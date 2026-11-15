// HiPS tile arithmetic. Run: node --test test/hips.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const Hips = require("../app/hips.js");
const close = (a, b, tol = 0.01) => Math.abs(a - b) < tol;

test("order 0: the twelve base tiles sit where HEALPix puts them", () => {
  const want = [[45, 41.81], [135, 41.81], [225, 41.81], [315, 41.81], [0, 0], [90, 0], [180, 0], [270, 0],
    [45, -41.81], [135, -41.81], [225, -41.81], [315, -41.81]];
  want.forEach(([ra, dec], n) => {
    const c = Hips.centre(0, n);
    assert.ok(close(c.ra % 360, ra) && close(c.dec, dec), `pixel ${n}: ${c.ra}, ${c.dec}`);
  });
});

test("pixel and centre are inverses for every tile of orders 0 to 4", () => {
  for (let k = 0; k <= 4; k++) for (let n = 0; n < 12 * 4 ** k; n++) {
    const c = Hips.centre(k, n);
    assert.equal(Hips.pixel(k, c.ra, c.dec), n, `order ${k} pixel ${n}`);
  }
});

test("a child tile lies inside its parent", () => {
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 200; i++) {
    const ra = rnd() * 360, dec = Math.asin(2 * rnd() - 1) * 180 / Math.PI;
    for (let k = 1; k <= 5; k++) assert.equal(Hips.pixel(k, ra, dec) >> 2, Hips.pixel(k - 1, ra, dec), `ra ${ra} dec ${dec} order ${k}`);
  }
});

test("the poles fall in the expected corner tiles", () => {
  for (let k = 0; k <= 4; k++) {
    const n = Hips.pixel(k, 10, 90), s = Hips.pixel(k, 10, -90), per = 4 ** k;
    assert.ok(n < 4 * per && n % per === per - 1, `north, order ${k}: ${n}`);
    assert.ok(s >= 8 * per && s % per === 0, `south, order ${k}: ${s}`);
  }
});

// Checked against the real survey on 2026-11-14: the order-3 DSS2 colour tile that this returns for the
// Pleiades (RA 56.75, Dec +24.12) shows the cluster. See artifacts/real-sky/pleiades-order3.jpg.
test("a known place lands in the tile the survey really stores it in", () => {
  assert.equal(Hips.pixel(3, 56.75, 24.12), 7);
});

test("tilesForLatitude covers the whole sky at the equator and only the visible band elsewhere", () => {
  for (let k = 0; k <= 3; k++) assert.equal(Hips.tilesForLatitude(0, k).length, 12 * 4 ** k);
  for (const k of [2, 3]) {
    for (const n of Hips.tilesForLatitude(90, k)) assert.ok(Hips.centre(k, n).dec > -20, `order ${k} pixel ${n}`);
    for (const n of Hips.tilesForLatitude(-90, k)) assert.ok(Hips.centre(k, n).dec < 20, `order ${k} pixel ${n}`);
  }
  const seattle = Hips.tilesForLatitude(47.6, 2).length;
  assert.ok(seattle >= 150 && seattle <= 190, String(seattle));
});

test("no tile that holds visible sky is left out", () => {
  let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (const lat of [47.6, -33.9, 10, 78]) for (const k of [0, 1, 2, 3]) {
    const have = new Set(Hips.tilesForLatitude(lat, k)), [lo, hi] = Hips.band(lat);
    for (let i = 0; i < 4000; i++) {
      const ra = rnd() * 360, dec = lo + rnd() * (hi - lo);
      assert.ok(have.has(Hips.pixel(k, ra, dec)), `lat ${lat} order ${k}: ra ${ra} dec ${dec}`);
    }
  }
});

// Ground truth: the tile files Aladin Lite 3.8.2 asked for at the closest zoom, pointing south at 35 degrees
// from latitude 47.6 (headless Edge, 2026-11-14, artifacts/real-sky/registration.md).
test("the tiles Aladin really asked for are in the plan for that latitude", () => {
  const urls = new Set(Hips.plan("B", 47.6, 2).urls);
  for (const n of [65, 68, 69, 70, 71, 142]) assert.ok(urls.has(`B/Norder2/Dir0/Npix${n}.jpg`), `Npix${n}`);
  assert.ok(urls.has("B/Norder3/Allsky.jpg"));
});

test("plan lists the survey files and the tiles, low orders first", () => {
  const p = Hips.plan("https://x/y", 47.6, 2);
  assert.deepEqual(p.urls.slice(0, 3), ["https://x/y/properties", "https://x/y/Moc.fits", "https://x/y/Norder3/Allsky.jpg"]);
  assert.equal(p.urls.length, p.tiles + 3);
  assert.equal(p.bytes, p.tiles * 38000 + 810000);
  assert.match(p.urls[3], /Norder0\/Dir0\/Npix\d+\.jpg$/);
  assert.match(p.urls[p.urls.length - 1], /Norder2\/Dir0\/Npix\d+\.jpg$/);
  assert.equal(Hips.url("b", 5, 12345), "b/Norder5/Dir10000/Npix12345.jpg");
});

test("orderFor picks the coarsest order that is as sharp as the screen", () => {
  assert.equal(Hips.orderFor(120, 720), 0);
  assert.equal(Hips.orderFor(60, 720), 1);
  assert.equal(Hips.orderFor(20, 720), 3);
  assert.equal(Hips.orderFor(0.001, 720, 9), 9);
});

test("evict drops the oldest entries until both limits hold", () => {
  const e = [1, 2, 3, 4, 5].map((i) => ({ url: "u" + i, bytes: 10 }));
  assert.deepEqual(Hips.evict(e, 5, 50), []);
  assert.deepEqual(Hips.evict(e, 3, 1000), ["u1", "u2"]);
  assert.deepEqual(Hips.evict(e, 99, 25), ["u1", "u2", "u3"]);
  assert.deepEqual(Hips.evict([], 1, 1), []);
});

test("saved places: removing one deletes only the files no other place needs", () => {
  // Basic (orders 0-1) covers the whole sky from both cities, so compare Standard (order 2) saves.
  const seattle = { urls: Hips.plan("B", 47.6, 2).urls }, sydney = { urls: Hips.plan("B", -33.9, 2).urls };
  const gone = Hips.orphans(seattle, [sydney]);
  assert.ok(gone.length > 0 && gone.length < seattle.urls.length, String(gone.length));
  for (const u of gone) assert.ok(!sydney.urls.includes(u));
  assert.ok(!gone.includes("B/properties"));                     // both places need the survey files
  assert.deepEqual(Hips.orphans(seattle, []), seattle.urls);     // the last place takes everything with it
  assert.deepEqual(Hips.orphans(seattle, [seattle]), []);
  const sharp = { urls: Hips.plan("B", 47.6, 3).urls };          // a finer save of the same latitude holds every coarser file
  assert.deepEqual(Hips.orphans(seattle, [sharp]), []);
});

test("manifest addresses are recognisable and one per survey, latitude and detail", () => {
  const u = Hips.manifestUrl("B", 47.6, 2);
  assert.equal(u, "B/__saved__/visible_lat48_order2.json");
  assert.notEqual(Hips.manifestUrl("B", 47.6, 2, "infrared"), u);
  assert.ok(Hips.isManifest(u) && Hips.isManifest(Hips.manifestUrl("B", -33.9, 1, "infrared")));
  assert.ok(!Hips.isManifest("B/Norder2/Dir0/Npix7.jpg") && !Hips.isManifest("B/properties"));
});

test("a survey's issue date is read from its properties file", () => {
  const text = "creator_did          = ivo://CDS/P/DSS2/color\nhips_creation_date   = 2010-05-01T19:05Z\nhips_release_date    = 2019-05-07T10:55Z\nhips_order           = 9\n";
  assert.equal(Hips.releaseDate(text), "2019-05-07T10:55Z");
  assert.equal(Hips.releaseDate("hips_order = 9\n"), "");
  assert.equal(Hips.releaseDate(""), "");
  assert.ok(!Hips.isManifest(Hips.releaseUrl("https://x/y")) && !/\.jpg$/.test(Hips.releaseUrl("https://x/y")));
});

test("the page and the service worker read one set of settings", () => {
  const c = Hips.CONFIG;
  for (const v of Object.values(c.surveys)) {
    assert.ok(c.tileRoots.some((r) => v.hosts[0].startsWith(r)) && c.tileRoots.some((r) => v.hosts[1].startsWith(r)));
    assert.ok(v.tile > 0 && v.allsky > 0);
  }
  assert.equal(new Set(Object.values(c.caches)).size, 4);
  const sw = require("node:fs").readFileSync(require("node:path").join(__dirname, "../app/sw.js"), "utf8");
  assert.ok(!/irsa\.ipac|wanderers-sky-v1|aladin-lite@/.test(sw), "sw.js repeats a setting that belongs in Hips.CONFIG");
});
