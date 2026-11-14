// Expected values: computed once with astropy 8.0.2 (web/scripts/sky-expected.py), no refraction (pressure 0).
// The numbers are hard-coded on purpose: an independent source of truth, not a copy of the code under test.
import { describe, expect, it } from 'vitest'
import { altAz, decText, gmstDeg, julianDate, pixelToSky, raText, separationArcsec, skyDay, skyToPixel } from './sky'

const close = (got: number, want: number, tol: number) => expect(Math.abs(got - want)).toBeLessThan(tol)

describe('sidereal time', () => {
  it('gives JD 2451545.0 at 2000-01-01 12:00 UTC', () => {
    expect(julianDate(new Date('2000-01-01T12:00:00Z'))).toBe(2451545)
  })
  it('matches astropy mean GMST within 0.01 deg', () => {
    close(gmstDeg(julianDate(new Date('2026-11-15T05:00:00Z'))), 129.30176751980196, 0.01)
    close(gmstDeg(julianDate(new Date('2026-03-20T00:00:00Z'))), 177.54157772408223, 0.01)
  })
})

const SEATTLE = { lat: 47.6062, lon: -122.3321 }
const TOKYO = { lat: 35.6762, lon: 139.6503 }
const BARNARD = { ra: 269.446268, dec: 4.768204 }
const RW_AUR = { ra: 76.956083, dec: 30.401187 }
const R_DRA = { ra: 248.167343, dec: 66.755011 }

describe('altitude and azimuth', () => {
  const cases: [string, typeof BARNARD, typeof SEATTLE, string, number, number][] = [
    ['Barnard from Seattle', BARNARD, SEATTLE, '2026-11-15T01:00:00Z', 36.7083, 228.4728],
    ['RW Aur from Seattle', RW_AUR, SEATTLE, '2026-11-15T09:00:00Z', 71.1102, 151.6877],
    ['RW Aur from Tokyo', RW_AUR, TOKYO, '2026-11-14T12:00:00Z', 36.9377, 76.0877],
    ['R Dra from Seattle', R_DRA, SEATTLE, '2026-11-15T05:00:00Z', 33.3555, 335.4798],
  ]
  it.each(cases)('matches astropy for %s within 0.1 deg', (_, star, here, iso, alt, az) => {
    const got = altAz(star, here, new Date(iso))
    close(got.alt, alt, 0.1)
    close(got.az, az, 0.1)
  })
})

describe('rise, set and transit', () => {
  const when = new Date('2026-11-14T22:00:00Z')
  const near = (got: Date | null, iso: string) => close(got!.getTime() / 1000, new Date(iso).getTime() / 1000, 120)

  it('gives the next rise, set and transit of RW Aur from Seattle within 2 minutes', () => {
    const day = skyDay(RW_AUR, SEATTLE, when)
    near(day.rise, '2026-11-15T01:02:05.940Z')
    near(day.set, '2026-11-15T18:19:44.701Z')
    near(day.transit, '2026-11-15T09:40:55.332Z')
    close(day.transitAlt, 72.8305, 0.1)
    expect(day.always).toBe(null)
  })
  it('gives the next set before the next rise when the star is up (Barnard)', () => {
    const day = skyDay(BARNARD, SEATTLE, when)
    near(day.set, '2026-11-15T04:52:11.982Z')
    near(day.rise, '2026-11-15T16:08:25.307Z')
    near(day.transit, '2026-11-14T22:32:16.614Z')
    close(day.transitAlt, 47.1605, 0.1)
  })
  it('says R Dra never sets from Seattle', () => {
    const day = skyDay(R_DRA, SEATTLE, when)
    expect(day.always).toBe('up')
    expect(day.rise).toBe(null)
    near(day.transit, '2026-11-15T21:02:11.185Z')
    close(day.transitAlt, 70.9075, 0.1)
  })
  it('says eps Ind B never rises from Seattle', () => {
    const day = skyDay({ ra: 331.0813, dec: -56.79546 }, SEATTLE, when)
    expect(day.always).toBe('down')
    expect(day.set).toBe(null)
  })
})

describe('flipbook pixels and the sky (north up, east left TAN grid like backend output_wcs)', () => {
  const barnard = { center: BARNARD, size_px: 49, pixel_arcsec: 6.15 }
  const rdra = { center: R_DRA, size_px: 147, pixel_arcsec: 6.15 }
  it('maps a PNG pixel to RA/Dec like astropy WCS', () => {
    const a = pixelToSky(barnard, 10, 40)
    close(a.ra, 269.4711239, 1e-5)
    close(a.dec, 4.7417244, 1e-5)
    const b = pixelToSky(rdra, 3, 140)
    close(b.ra, 248.471103, 1e-5)
    close(b.dec, 66.6411139, 1e-5)
  })
  it('maps RA/Dec back to the same pixel', () => {
    const p = skyToPixel(rdra, { ra: 248.471103, dec: 66.6411139 })
    close(p.x, 3, 1e-3)
    close(p.y, 140, 1e-3)
  })
  it('puts the view center at the middle of the PNG', () => {
    const c = pixelToSky(barnard, 24.5, 24.5)
    close(c.ra, BARNARD.ra, 1e-9)
    close(c.dec, BARNARD.dec, 1e-9)
  })
  it('measures separations like astropy', () => {
    close(separationArcsec(BARNARD, { ra: 269.447, dec: 4.7695 }), 5.353887021701024, 1e-6)
  })
})

describe('sexagesimal text', () => {
  it('writes RA and Dec like astropy to_string', () => {
    expect(raText(269.446268)).toBe('17h 57m 47.10s')
    expect(decText(4.768204)).toBe('+04° 46′ 05.5″')
    expect(raText(331.0813)).toBe('22h 04m 19.51s')
    expect(decText(-56.79546)).toBe('-56° 47′ 43.7″')
  })
  it('carries 60 seconds into the next minute', () => {
    expect(raText(15 + (59.99999 / 3600) * 15)).toBe('01h 01m 00.00s')
    expect(decText(4.999989)).toBe('+05° 00′ 00.0″')
  })
})
