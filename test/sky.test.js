// Sky maths for the real-sky view: the inverse direction (phone -> stars) and the planets.
// Run: node --test test/sky.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const Sky = require("../app/sky.js");

const STARS = [
  ["Polaris", 37.95, 89.26], ["Vega", 279.23, 38.78], ["Arcturus", 213.92, 19.18], ["Capella", 79.17, 46.00],
  ["Sirius", 101.29, -16.72], ["Betelgeuse", 88.79, 7.41], ["Rigel", 78.63, -8.20], ["Aldebaran", 68.98, 16.51],
  ["Altair", 297.70, 8.87], ["Deneb", 310.36, 45.28], ["Spica", 201.30, -11.16], ["Antares", 247.35, -26.43],
  ["Procyon", 114.83, 5.22], ["Pollux", 116.33, 28.03], ["Regulus", 152.09, 11.97], ["Fomalhaut", 344.41, -29.62],
];
const DATES = ["2026-11-15T06:00:00Z", "2027-04-02T11:30:00Z", "2030-07-20T20:15:00Z"].map((d) => new Date(d));
const sepDeg = (a, b) => {
  const r = Math.PI / 180;
  const c = Math.sin(a.dec * r) * Math.sin(b.dec * r) + Math.cos(a.dec * r) * Math.cos(b.dec * r) * Math.cos((a.ra - b.ra) * r);
  return Math.acos(Math.max(-1, Math.min(1, c))) / r;
};

test("unobserve undoes observe for every named star that is up", () => {
  let checked = 0;
  for (const date of DATES) for (const [lat, lon] of [[47.6, -122.3], [0, 10], [-35, 149]]) for (const [name, ra, dec] of STARS) {
    const o = Sky.observe({ ra, dec }, date, lat, lon);
    if (o.alt < 5) continue;
    const back = Sky.unobserve(o.az, o.alt, date, lat, lon);
    assert.ok(sepDeg(back, { ra, dec }) < 0.02, `${name} at lat ${lat}: ${sepDeg(back, { ra, dec }).toFixed(4)} deg off`);
    checked++;
  }
  assert.ok(checked > 60, `only ${checked} cases were above 5 degrees`);
});

test("frame puts every star where observe puts it", () => {
  for (const date of DATES) for (const [lat, lon] of [[47.6, -122.3], [-35, 149]]) {
    const f = Sky.frame(date, lat, lon);
    for (const [name, ra, dec] of STARS) {
      const o = Sky.observe({ ra, dec }, date, lat, lon), v = f.toHorizon(...Sky.unit(ra, dec));
      const az = (Math.atan2(v[0], v[1]) * 180 / Math.PI + 360) % 360, alt = Math.asin(v[2]) * 180 / Math.PI;
      assert.ok(Math.abs(alt - o.alt) < 1e-6 && Math.abs(((az - o.az + 540) % 360) - 180) * Math.cos(alt * Math.PI / 180) < 1e-6, `${name}: ${az},${alt} vs ${o.az},${o.alt}`);
    }
  }
});

test("frame.toJ2000 is the exact inverse of the rotation", () => {
  const f = Sky.frame(DATES[1], 47.6, -122.3), r = Math.PI / 180;
  for (const [name, ra, dec] of STARS) {
    const [x, y, z] = Sky.unit(ra, dec), m = f.m;
    const v = [0, 1, 2].map((i) => m[i][0] * x + m[i][1] * y + m[i][2] * z), b = f.toJ2000(v);
    assert.ok(sepDeg(b, { ra, dec }) < 1e-5, `${name}: ${sepDeg(b, { ra, dec })}`);
  }
});

test("zenithAngle: up is north for a point due south, and south for a point between the pole and the zenith", () => {
  const d = DATES[0], near = (x, want) => Math.abs(((x - want + 540) % 360) - 180) < 0.5;
  assert.ok(near(Sky.zenithAngle(180, 30, d, 47.6, -122.3), 0), String(Sky.zenithAngle(180, 30, d, 47.6, -122.3)));
  assert.ok(near(Sky.zenithAngle(0, 70, d, 47.6, -122.3), 180), String(Sky.zenithAngle(0, 70, d, 47.6, -122.3)));
});

test("zenithAngle is continuous through the horizon and defined at the zenith", () => {
  const d = DATES[0];
  const a = Sky.zenithAngle(120, 0.01, d, 47.6, -122.3), b = Sky.zenithAngle(120, -0.01, d, 47.6, -122.3);
  assert.ok(Math.abs(((a - b + 540) % 360) - 180) < 0.1, `${a} vs ${b}`);
  assert.ok(Number.isFinite(Sky.zenithAngle(40, 90, d, 47.6, -122.3)));
});

// JPL Horizons, geocentric (500@399), astrometric RA/Dec (ICRF), degrees. Queried 2026-11-14 from
// https://ssd.jpl.nasa.gov/api/horizons.api?COMMAND='499'&EPHEM_TYPE='OBSERVER'&CENTER='500@399'&QUANTITIES='1'&ANG_FORMAT='DEG'&TLIST=...
const HORIZONS = {
  "2026-11-15T06:00:00Z": { Mercury: [213.37323, -11.04397], Venus: [200.30897, -10.04059], Mars: [148.00026, 14.97266], Jupiter: [147.95053, 13.74169], Saturn: [8.51410, 0.79534] },
  "2028-03-01T00:00:00Z": { Mercury: [316.37932, -17.18970], Venus: [23.09213, 10.93895], Mars: [346.42680, -6.83756], Jupiter: [174.78844, 3.88742], Saturn: [23.54877, 7.34941] },
  "2030-07-20T12:00:00Z": { Mercury: [143.98552, 15.09183], Venus: [93.42835, 22.87882], Mars: [103.35378, 23.65726], Jupiter: [225.19148, -16.09232], Saturn: [63.70224, 19.33365] },
};
test("planets agree with JPL Horizons within 0.1 degree", () => {
  for (const [when, truth] of Object.entries(HORIZONS)) for (const p of Sky.planets(new Date(when))) {
    const [ra, dec] = truth[p.name], off = sepDeg(p, { ra, dec });
    assert.ok(off < 0.1, `${p.name} on ${when}: ${off.toFixed(3)} deg off`);
  }
});
