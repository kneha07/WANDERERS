// Sky Compass astronomy (app/sky.js) against astropy, and the crosshair -> RA/Dec inverse used for Webb (app/compass.js).
// node --test test/sky.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Sky = require("../app/sky.js");

const D2R = Math.PI / 180;
const sep = (az1, alt1, az2, alt2) => {
  const v = (az, alt) => [Math.sin(az * D2R) * Math.cos(alt * D2R), Math.cos(az * D2R) * Math.cos(alt * D2R), Math.sin(alt * D2R)];
  const a = v(az1, alt1), b = v(az2, alt2);
  return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))) / D2R;
};
const sepRaDec = (ra1, d1, ra2, d2) => sep(90 - ra1, d1, 90 - ra2, d2);

// astropy 6 (ICRS -> AltAz, no refraction; get_body for the Sun and Moon), generated once by hand
const ASTROPY = [
  { utc: "2026-11-14T06:00:00Z", lat: 47.61, lon: -122.33, name: "Sirius", ra: 101.28722, dec: -16.71612, az: 108.1763, alt: -6.1369, gmst: 143.35719 },
  { utc: "2026-11-14T06:00:00Z", lat: 47.61, lon: -122.33, name: "Polaris", ra: 37.95456, dec: 89.26411, az: 0.4122, alt: 48.1675, gmst: 143.35719 },
  { utc: "2030-06-21T18:30:00Z", lat: -33.87, lon: 151.21, name: "Canopus", ra: 95.98792, dec: -52.69566, az: 146.6268, alt: 12.2184, gmst: 187.49622 },
  { utc: "2024-03-20T03:06:00Z", lat: -89.5, lon: -60, name: "Sigma Octantis", ra: 317.195, dec: -88.956, az: 164.138, alt: 88.3792, gmst: 224.64603 },
  { utc: "2026-02-01T23:59:00Z", lat: 10, lon: 179.9, name: "Vega", ra: 279.23473, dec: 38.78369, az: 320.2902, alt: 49.1814, gmst: 131.95117 },
  { utc: "2026-02-01T23:59:00Z", lat: -10, lon: -179.9, name: "Fomalhaut", ra: 344.41269, dec: -29.62224, az: 127.2345, alt: 53.7796, gmst: 131.95117 },
  { utc: "2026-11-14T20:00:00Z", lat: 47.61, lon: -122.33, name: "sun", az: 181.609, alt: 23.988, gmst: 353.93215 },
  { utc: "2030-06-21T18:30:00Z", lat: 0, lon: 0, name: "sun", az: 293.5919, alt: -6.4453, gmst: 187.49622 },
  { utc: "2026-11-14T06:00:00Z", lat: 47.61, lon: -122.33, name: "moon", az: 253.9438, alt: -21.1376, gmst: 143.35719 },
  { utc: "2030-06-21T18:30:00Z", lat: 10, lon: 179.9, name: "moon", az: 245.1353, alt: 68.2605, gmst: 187.49622 },
];

test("Sky.observe matches astropy: stars and Sun within 0.02 deg, Moon within 0.3 deg, sidereal time within 0.005 deg", () => {
  for (const r of ASTROPY) {
    const date = new Date(r.utc), obj = r.ra != null ? { ra: r.ra, dec: r.dec } : { body: r.name };
    const o = Sky.observe(obj, date, r.lat, r.lon);
    const err = sep(o.az, o.geometricAlt, r.az, r.alt), tol = r.name === "moon" ? 0.3 : 0.02;
    assert.ok(err < tol, `${r.name} ${r.utc} at ${r.lat},${r.lon}: ${err.toFixed(4)} deg off`);
    assert.ok(Math.abs(((Sky.gmst(Sky.jd(date)) - r.gmst + 540) % 360) - 180) < 0.005, `GMST ${r.utc}`);
  }
});

test("refraction lifts objects near the horizon by about half a degree and vanishes at the zenith", () => {
  assert.ok(Math.abs(Sky.refraction(0) - 0.48) < 0.02, `${Sky.refraction(0)}`);
  assert.ok(Math.abs(Sky.refraction(10) - 0.088) < 0.005);
  assert.ok(Math.abs(Sky.refraction(90)) < 0.001);
  assert.equal(Sky.refraction(-5), 0);
});

test("unprecess is the exact inverse of precess, also at the celestial poles and across RA 0/360", () => {
  const J = Sky.jd(new Date("2050-06-01T00:00:00Z"));
  for (const [ra, dec] of [[0, 0], [359.999, 10], [0.001, -10], [123.4, 89.99], [271, -89.95], [180, 90], [45, -90], [300, 66.5]]) {
    const p = Sky.precess(ra, dec, J), back = Sky.unprecess(p.ra, p.dec, J);
    assert.ok(sepRaDec(ra, dec, back.ra, back.dec) < 1e-9, `${ra},${dec} -> ${back.ra},${back.dec}`);
    assert.ok(back.dec >= -90 && back.dec <= 90 && back.ra >= 0 && back.ra < 360);
  }
});

test("the crosshair's RA/Dec (for the Webb chip) inverts Sky.observe, even beside the celestial pole", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "app", "compass.js"), "utf8");
  const fn = new Function("Sky", "D2R", `${src.match(/function crosshairRaDec\([\s\S]*?\n\}/)[0]}; return crosshairRaDec;`)(Sky, D2R);
  const now = new Date("2050-06-01T00:00:00Z");
  let worst = 0;
  for (const [lat, lon] of [[47.61, -122.33], [-33.9, 0], [0, 179.99], [89.9, 30], [-89.9, -60]]) {
    for (const [ra, dec] of [[132.457, -89.605], [10, 89.9], [90, 89.99], [359.99, -89.95], [200, 40], [0.01, 0], [101.3, -16.7]]) {
      const o = Sky.observe({ ra, dec }, now, lat, lon);
      const c = fn({ az: o.az, alt: o.geometricAlt }, now, { lat, lon }, o.lst);
      assert.ok(c.dec >= -90 && c.dec <= 90, `dec out of range: ${c.dec}`);
      worst = Math.max(worst, sepRaDec(ra, dec, c.ra, c.dec));
    }
  }
  assert.ok(worst < 1e-6, `worst round trip ${worst} deg`);
});

test("magnetic declination: grid edges (lon +-180, lat +-89) are finite and continuous across the date line", async () => {
  const grid = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app", "data", "declination.json"), "utf8"));
  global.fetch = async () => ({ json: async () => grid });
  await Sky.loadDeclination("x");
  delete global.fetch;
  assert.ok(Math.abs(Sky.declination(47.61, -122.33) - 15.2) < 1.5, `Seattle ${Sky.declination(47.61, -122.33)}`);
  for (const lat of [-89, -60, 0, 60, 89]) {
    const e = Sky.declination(lat, 179.999), w = Sky.declination(lat, -179.999);
    assert.ok(Number.isFinite(e) && Number.isFinite(w));
    assert.ok(Math.abs(((e - w + 540) % 360) - 180) < 0.5, `lat ${lat}: ${e} vs ${w}`);
  }
});
