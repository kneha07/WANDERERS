import { describe, expect, it } from 'vitest'
import { brightGhosts, frameNotes, labelRange, marksFromParam, marksToParam, motionSentence, nearestGaia, scatteredLight, titleOf } from './data'

describe('epoch labels', () => {
  it('reads a one-day label', () => {
    expect(labelRange('2026-09-22')).toEqual([61305, 61306])
  })
  it('reads a same-year range (end day included)', () => {
    expect(labelRange('2025-08-15 to 09-05')).toEqual([60902, 60924])
  })
  it('reads a range across a new year', () => {
    expect(labelRange('2025-12-20 to 2026-01-10')).toEqual([61029, 61051])
  })
  it('gives null for text it does not know', () => {
    expect(labelRange('summer 2025')).toBe(null)
  })
})

describe('candidates in the URL', () => {
  it('round-trips positions, negative Dec included', () => {
    const marks = [
      { ra: 269.44612, dec: 4.6933 },
      { ra: 331.0813, dec: -56.79546 },
    ]
    expect(marksFromParam(marksToParam(marks))).toEqual(marks)
  })
  it('drops broken pairs', () => {
    expect(marksFromParam('12.5_x_400_1_10_20_30')).toEqual([{ ra: 10, dec: 20 }])
  })
})

describe('nearest Gaia star', () => {
  const view = { pixel_arcsec: 6.15 }
  const gaia = {
    release: 'Gaia DR3',
    epoch_mjd: 57388.5,
    stars: [
      { source_id: '1', ra: 0, dec: 0, pmra: 0, pmdec: 0, gmag: 12, xy: [[10, 10], [10, 10]] as [number, number][] },
      { source_id: '2', ra: 0, dec: 0, pmra: 0, pmdec: 0, gmag: 15, xy: [[30, 30], [20.5, 20]] as [number, number][] },
    ],
  }
  it('uses the closest frame of a moving star', () => {
    const hit = nearestGaia(view, gaia, { x: 20, y: 20 })
    expect(hit?.star.source_id).toBe('2')
    expect(hit?.sep).toBeCloseTo(0.5 * 6.15, 6)
  })
  it('gives null without Gaia data', () => {
    expect(nearestGaia(view, null, { x: 1, y: 1 })).toBe(null)
  })
})

describe('frame notes', () => {
  const frame = { label: '2025-05-05', mjd_mean: 60800, date: '2025-05-05', n_images: 12, png: '', ring: null, saturated: false }
  it('says plainly that a typed position has no predicted position, not that nothing is there', () => {
    const notes = frameNotes({ ...frame, centroid: null, notes: ['no proper motion known: no predicted position'] })
    expect(notes).toEqual(['No proper motion known: no predicted position'])
  })
  it('keeps "no source" for a known motion with an empty fit', () => {
    expect(frameNotes({ ...frame, centroid: null, notes: [] })).toEqual(['No source above 5σ at the target'])
  })
})

// Barnard's Star, cached answer of 2026-11-14: centroids and rings of frames 1 and 6 (391.9 days apart).
const barnard = {
  pixel_arcsec: 6.15,
  pm: { pmra: -801.6, pmdec: 10362.4 },
  frames: [
    { mjd_mean: 60913.55, ring: { x: 24.45, y: 25.09 }, centroid: { x: 24.24, y: 24.993, ex: 0.123, ey: 0.124 } },
    { mjd_mean: 61305.5, ring: { x: 24.59, y: 23.28 }, centroid: { x: 24.575, y: 23.471, ex: 0.234, ey: 0.213 } },
  ],
}

describe('plain motion sentence', () => {
  it('says how far, which way and how long, and that the catalogue agrees', () => {
    expect(motionSentence(barnard)).toBe(
      'In our SPHEREx frames it moves about 8.9″ per year toward the north-northwest (1.6 pixels in 13 months), as its catalogue motion predicts (10.4″ per year).',
    )
  })
  it('says what the catalogue predicts when it disagrees', () => {
    const r = { ...barnard, frames: [barnard.frames[0], { ...barnard.frames[1], ring: { x: 22.0, y: 25.09 } }] }
    expect(motionSentence(r)).toBe(
      'In our SPHEREx frames it moves about 8.9″ per year toward the north-northwest (1.6 pixels in 13 months); its catalogue motion is 14.0″ per year toward the east.',
    )
  })
  it('says when the shift is inside the errors', () => {
    const c = { ex: 0.3, ey: 0.3 }
    const r = { ...barnard, frames: [{ ...barnard.frames[0], centroid: { x: 24.5, y: 24.5, ...c } }, { ...barnard.frames[1], centroid: { x: 24.6, y: 24.5, ...c } }] }
    expect(motionSentence(r)).toBe(
      'In our SPHEREx frames it does not move measurably in 13 months (less than 7.3″ per year); its catalogue motion is 10.4″ per year.',
    )
  })
  it('says that a typed position has no prediction', () => {
    expect(motionSentence({ ...barnard, pm: null, frames: barnard.frames.map((f) => ({ ...f, ring: null, centroid: null })) })).toBe(
      'No proper motion is known for a typed position, so there is no predicted position to measure.',
    )
  })
})

describe('heading name', () => {
  it('keeps the typed name and adds the catalog id when it differs', () => {
    expect(titleOf({ query: "Kapteyn's Star", name: 'HD 33793' })).toEqual({ title: "Kapteyn's Star", catalog: 'HD 33793' })
  })
  it('adds nothing when the catalog id is the same name', () => {
    expect(titleOf({ query: 'R Dra', name: 'V* R Dra' }).catalog).toBe(null)
    expect(titleOf({ query: "barnard's star", name: "Barnard's star" }).catalog).toBe(null)
    expect(titleOf({ query: '269.45 4.69', name: null }).catalog).toBe(null)
  })
})

describe('Gaia ghosts shown by default', () => {
  const star = (g: number) => ({ source_id: String(g), ra: 0, dec: 0, pmra: 0, pmdec: 0, gmag: g, xy: [] })
  it('shows only stars brighter than G 17', () => {
    expect(brightGhosts([8, 12, 16.9, 17, 18].map(star)).map((s) => s.gmag)).toEqual([8, 12, 16.9])
  })
  it('shows at most the 40 brightest', () => {
    expect(brightGhosts(Array.from({ length: 50 }, (_, i) => star(10 + i * 0.1))).length).toBe(40)
  })
})

describe('scattered light', () => {
  const det = (fluxes: number[]) => fluxes.map((flux, i) => ({ group_index: i, png: '', n_images: 4, photometry: { flux, err: 0.03 } }))
  it('is suspected when the largest change is in D1 or D2 (Epsilon Indi B, issue #5)', () => {
    expect(scatteredLight({ detectors: { D2: det([13.1, 35.97]), D3: det([11.7, 25.14]), D6: det([19.7, 23.85]) } })).toBe(true)
  })
  it('is not suspected when a long-wavelength detector changes most', () => {
    expect(scatteredLight({ detectors: { D2: det([20, 22]), D5: det([29.94, 58.88]) } })).toBe(false)
  })
})
