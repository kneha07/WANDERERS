import { describe, expect, it } from 'vitest'
import type { Result } from './data'
import { localOnly, reportText } from './rail'

const r = {
  query: "Kapteyn's Star",
  name: 'HD 33793',
  center: { ra: 77.95717, dec: -45.06003 },
  fov_arcmin: 5,
  pixel_arcsec: 6.15,
  size_px: 49,
  frames: [{ label: '2025-08-10 to 09-20' }, { label: '2026-08-07 to 09-07' }],
  gaia: null,
} as unknown as Result

describe('Talk report', () => {
  it('names the target and its RA/Dec, and leaves out a link that opens only on this computer', () => {
    const text = reportText(r, [], 'http://localhost:8000/explore/?q=x', true)
    expect(text).toContain("Field: Kapteyn's Star (HD 33793) at RA 05h 11m 49.72s, Dec -45° 03′ 36.1″ (77.95717, -45.06003), 5′")
    expect(text).toContain('Frames: first 2025-08-10 to 09-20, last 2026-08-07 to 09-07')
    expect(text).not.toContain('localhost')
  })
  it('keeps the link once the tool is hosted', () => {
    expect(reportText(r, [], 'https://example.org/explore/?q=x', false)).toContain('Link: https://example.org/explore/?q=x')
  })
  it('knows which hosts are this computer only', () => {
    expect([localOnly('localhost'), localOnly('127.0.0.1'), localOnly('example.org')]).toEqual([true, true, false])
  })
})
