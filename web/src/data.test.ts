import { describe, expect, it } from 'vitest'
import { frameNotes, labelRange, marksFromParam, marksToParam, nearestGaia } from './data'

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
