import { describe, expect, it } from 'vitest'
import type { Result } from './data'
import { localOnly, markedText, reportText } from './rail'

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

describe('the report names the field once', () => {
  it('leaves out a catalog name that only differs in case', () => {
    const text = reportText({ ...r, query: "Barnard's Star", name: "Barnard's star" } as Result, [], 'u', true)
    expect(text).toContain("Field: Barnard's Star at RA")
  })
})

describe('the toast after a mark', () => {
  it('points to the Task tab on a wide screen and to the list below on a phone', () => {
    expect(markedText(1, 269.44642, 4.7676, false)).toBe('Candidate 1 marked at 17h 57m 47.14s +04° 46′ 03.4″. See the Task tab.')
    expect(markedText(2, 269.44642, 4.7676, true)).toBe('Candidate 2 marked at 17h 57m 47.14s +04° 46′ 03.4″. See Candidates below.')
  })
})
