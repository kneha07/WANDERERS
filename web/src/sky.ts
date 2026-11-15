// Sky math for the "Your sky now" and candidate panels. Pure functions, degrees in and out.
// Accuracy target: 0.1 deg (no nutation, aberration or refraction; UT1 = UTC).

const RAD = Math.PI / 180
const mod360 = (d: number) => ((d % 360) + 360) % 360

/** Julian date (UTC) of a JS Date. */
export const julianDate = (d: Date) => d.getTime() / 86_400_000 + 2_440_587.5

/** Greenwich mean sidereal time, degrees (IAU 1982). */
export function gmstDeg(jd: number) {
  const t = (jd - 2_451_545) / 36_525
  return mod360(280.46061837 + 360.98564736629 * (jd - 2_451_545) + 0.000387933 * t * t - (t * t * t) / 38_710_000)
}

export type RaDec = { ra: number; dec: number }
export type Place = { lat: number; lon: number } // degrees, east longitude positive

/** J2000 (ICRS) position -> mean equator of date (IAU 1976 precession). 26 years move a star about 0.37 deg. */
export function precess({ ra, dec }: RaDec, jd: number): RaDec {
  const t = (jd - 2_451_545) / 36_525
  const as = RAD / 3600
  const zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * as
  const z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * as
  const theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * as
  const a = ra * RAD + zeta
  const d = dec * RAD
  const x = Math.cos(theta) * Math.cos(d) * Math.cos(a) - Math.sin(theta) * Math.sin(d)
  const y = Math.cos(d) * Math.sin(a)
  const s = Math.sin(theta) * Math.cos(d) * Math.cos(a) + Math.cos(theta) * Math.sin(d)
  return { ra: mod360((Math.atan2(y, x) + z) / RAD), dec: Math.asin(s) / RAD }
}

/** Altitude above the horizon and azimuth (from north, through east) of a J2000 position, degrees. */
export function altAz(star: RaDec, here: Place, when: Date) {
  const jd = julianDate(when)
  const p = precess(star, jd)
  const h = (gmstDeg(jd) + here.lon - p.ra) * RAD // hour angle
  const d = p.dec * RAD
  const phi = here.lat * RAD
  const alt = Math.asin(Math.sin(phi) * Math.sin(d) + Math.cos(phi) * Math.cos(d) * Math.cos(h))
  const az = Math.atan2(-Math.sin(h) * Math.cos(d), Math.sin(d) * Math.cos(phi) - Math.cos(d) * Math.sin(phi) * Math.cos(h))
  return { alt: alt / RAD, az: mod360(az / RAD) }
}

const SIDEREAL_DEG_PER_DAY = 360.98564736629
const after = (when: Date, deg: number) => new Date(when.getTime() + (mod360(deg) / SIDEREAL_DEG_PER_DAY) * 86_400_000)

/** Next rise, set and upper transit after `when` (geometric horizon, altitude 0). */
export function skyDay(star: RaDec, here: Place, when: Date) {
  const jd = julianDate(when)
  const p = precess(star, jd)
  const h0 = gmstDeg(jd) + here.lon - p.ra // hour angle now
  const phi = here.lat * RAD
  const d = p.dec * RAD
  const cosH = -Math.tan(phi) * Math.tan(d) // hour angle at altitude 0
  const always: 'up' | 'down' | null = cosH < -1 ? 'up' : cosH > 1 ? 'down' : null
  const hr = always ? 0 : Math.acos(cosH) / RAD
  return {
    transit: after(when, -h0),
    transitAlt: 90 - Math.abs(here.lat - p.dec),
    rise: always ? null : after(when, -hr - h0),
    set: always ? null : after(when, hr - h0),
    always,
  }
}

/** The flipbook geometry from the API: a north-up, east-left TAN grid of size_px pixels around center. */
export type Grid = { center: RaDec; size_px: number; pixel_arcsec: number }

/** PNG pixel (origin top-left, continuous: pixel k spans k..k+1) -> RA/Dec, like backend output_wcs + display_xy. */
export function pixelToSky(g: Grid, x: number, y: number): RaDec {
  const s = (g.pixel_arcsec / 3600) * RAD
  const xi = -(x - g.size_px / 2) * s // east positive
  const eta = (g.size_px / 2 - y) * s // north positive
  const rho = Math.hypot(xi, eta)
  if (rho === 0) return { ...g.center }
  const c = Math.atan(rho)
  const d0 = g.center.dec * RAD
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (eta * Math.sin(c) * Math.cos(d0)) / rho)
  const dra = Math.atan2(xi * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - eta * Math.sin(d0) * Math.sin(c))
  return { ra: mod360(g.center.ra + dra / RAD), dec: dec / RAD }
}

/** RA/Dec -> PNG pixel (inverse of pixelToSky). */
export function skyToPixel(g: Grid, p: RaDec) {
  const s = (g.pixel_arcsec / 3600) * RAD
  const a = (p.ra - g.center.ra) * RAD
  const d = p.dec * RAD
  const d0 = g.center.dec * RAD
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a)
  const xi = (Math.cos(d) * Math.sin(a)) / cosc
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a)) / cosc
  return { x: g.size_px / 2 - xi / s, y: g.size_px / 2 - eta / s }
}

/** Angle between two sky positions, arcsec (Vincenty: exact for small and large angles). */
export function separationArcsec(a: RaDec, b: RaDec) {
  const d1 = a.dec * RAD
  const d2 = b.dec * RAD
  const dl = (b.ra - a.ra) * RAD
  const num = Math.hypot(Math.cos(d2) * Math.sin(dl), Math.cos(d1) * Math.sin(d2) - Math.sin(d1) * Math.cos(d2) * Math.cos(dl))
  const den = Math.sin(d1) * Math.sin(d2) + Math.cos(d1) * Math.cos(d2) * Math.cos(dl)
  return (Math.atan2(num, den) / RAD) * 3600
}

const pad = (v: number, n: number, digits = 0) => v.toFixed(digits).padStart(n + (digits ? digits + 1 : 0), '0')

/** RA in degrees -> "17h 57m 47.10s". Rounds once, so 59.999 s carries into the next minute. */
export function raText(ra: number) {
  const cs = Math.round((mod360(ra) / 15) * 360_000) // centiseconds of time
  return `${pad(Math.floor(cs / 360_000) % 24, 2)}h ${pad(Math.floor(cs / 6000) % 60, 2)}m ${pad((cs % 6000) / 100, 2, 2)}s`
}

/** Dec in degrees -> "+04° 46′ 05.5″". */
export function decText(dec: number) {
  const ds = Math.round(Math.abs(dec) * 36_000) // tenths of an arcsec
  return `${dec < 0 ? '-' : '+'}${pad(Math.floor(ds / 36_000), 2)}° ${pad(Math.floor(ds / 600) % 60, 2)}′ ${pad((ds % 600) / 10, 2, 1)}″`
}
