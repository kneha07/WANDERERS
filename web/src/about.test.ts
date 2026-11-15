import { describe, expect, it } from 'vitest'
import { aboutUrl, aboutWhere, fastHint, gaiaSentence, historyLine, measuredSentence, onTarget } from './about'
import type { About } from './about'

// Barnard's Star, cached answer of 2026-11-14: frames 1 and 6 are 391.9 days apart.
const barnard = {
  pixel_arcsec: 6.15,
  pm: { pmra: -801.6, pmdec: 10362.4 },
  detectors: {},
  frames: [
    { mjd_mean: 60913.55, ring: { x: 24.45, y: 25.09 }, centroid: { x: 24.24, y: 24.993, ex: 0.123, ey: 0.124 }, saturated: true, photometry: null },
    { mjd_mean: 61305.5, ring: { x: 24.59, y: 23.28 }, centroid: { x: 24.575, y: 23.471, ex: 0.234, ey: 0.213 }, saturated: true, photometry: null },
  ],
}
const still = (f: (typeof barnard.frames)[number]) => ({ ...f, centroid: { x: 24.5, y: 24.5, ex: 0.3, ey: 0.3 } })

describe('sentence 2: what our SPHEREx frames measure', () => {
  it('gives the motion per year and its direction', () => {
    // 1.558 px = 9.58″ in 1.073 years = 8.9″ per year, position angle 348°
    expect(measuredSentence(barnard)).toBe('In our SPHEREx frames it moves about 8.9″ per year toward the north-northwest.')
  })
  it('gives the brightness change when it does not move measurably', () => {
    const phot = [{ flux: 10, err: 0.1 }, { flux: 13, err: 0.1 }]
    const r = { ...barnard, detectors: { D5: [] }, frames: barnard.frames.map((f, i) => ({ ...still(f), saturated: false, photometry: phot[i] })) }
    expect(measuredSentence(r)).toBe('In our SPHEREx frames its brightness changes 1.3× between surveys (21.2σ).')
  })
  it('says when the brightness change is inside the noise', () => {
    const phot = [{ flux: 10, err: 0.5 }, { flux: 10.5, err: 0.5 }]
    const r = { ...barnard, frames: barnard.frames.map((f, i) => ({ ...still(f), saturated: false, photometry: phot[i] })) }
    expect(measuredSentence(r)).toBe('In our SPHEREx frames it does not move measurably, and its brightness stays within the noise.')
  })
  it('calls a change sky noise when no source shows at the position (typed coordinates of a star that moved away)', () => {
    const phot = [{ flux: 0.0288, err: 0.06 }, { flux: 0.3114, err: 0.07 }] // 10.8×, 3.1σ, but never 5σ, and no centroid
    const r = { ...barnard, pm: null, frames: barnard.frames.map((f, i) => ({ ...f, ring: null, centroid: null, saturated: false, photometry: phot[i] })) }
    expect(measuredSentence(r)).toBe('In our SPHEREx frames no source shows at this position, so its brightness numbers are sky noise.')
  })
  it('says when the star is too bright to measure', () => {
    const r = { ...barnard, frames: barnard.frames.map(still) }
    expect(measuredSentence(r)).toBe('It is too bright for SPHEREx to measure here.')
  })
})

describe('sentence 1 for a position without a SIMBAD answer: the nearest Gaia star', () => {
  const star = { source_id: '1', ra: 0, dec: 0, pmra: 0, pmdec: 0, gmag: 12.34, xy: [], parallax: 2.5, parallax_over_error: 40 }
  it('gives magnitude and distance from a good parallax', () => {
    expect(gaiaSentence({ star, sep: 0.42, frame: 0 }, 'Gaia DR3')).toBe(
      'The nearest Gaia DR3 star, 0.4″ away, has G = 12.3 (Gaia brightness; larger is fainter) and lies about 1,300 light-years away (parallax 2.50 mas).',
    )
  })
  it('leaves out a distance from a poor parallax', () => {
    expect(gaiaSentence({ star: { ...star, parallax_over_error: 3 }, sep: 1.1, frame: 0 }, 'Gaia DR3')).toBe(
      'The nearest Gaia DR3 star, 1.1″ away, has G = 12.3 (Gaia brightness; larger is fainter).',
    )
  })
  it('says when no Gaia star is close', () => {
    expect(gaiaSentence({ star, sep: 7.24, frame: 0 }, 'Gaia DR3')).toBe('No Gaia DR3 star is within 3″; the nearest is 7.2″ away.')
    expect(gaiaSentence(null, 'Gaia DR3')).toBe('No Gaia DR3 star is in this view.')
  })
})

describe('sentence 3: history', () => {
  const a = { history_sentence: null, history_source: null, papers: null } as unknown as About
  it('quotes the Wikipedia sentence with its licence', () => {
    const line = historyLine({ ...a, history_sentence: 'RW Aurigae B was discovered in 1944.', history_source: { title: 'RW Aurigae', url: 'u', license: 'CC BY-SA 4.0' } })
    expect(line).toEqual({ text: '“RW Aurigae B was discovered in 1944.”', url: 'u', license: 'CC BY-SA 4.0' })
  })
  it('else counts the SIMBAD papers', () => {
    expect(historyLine({ ...a, papers: 924 }).text).toBe('SIMBAD lists 924 papers about it.')
  })
  it('else says the history is unknown', () => {
    expect(historyLine({ ...a }).text).toBe('Its history is unknown here.')
    expect(historyLine(null).text).toBe('Its history is unknown here.')
  })
})

describe('where to ask about a position', () => {
  const gaia = { release: 'Gaia DR3', epoch_mjd: 57388.5, stars: [] }
  const barnard = { source_id: '4472832130942575872', ra: 269.4485025, dec: 4.739420, pmra: -801.551, pmdec: 10362.394, gmag: 8.2, xy: [] }
  it('sends the Gaia position, epoch and proper motion of a star faster than 1″ per year', () => {
    expect(aboutUrl(aboutWhere({ ra: 269.44642, dec: 4.7676 }, { star: barnard, sep: 0.5 }, gaia))).toBe(
      '/api/about?ra=269.4485025&dec=4.73942&pmra=-801.551&pmdec=10362.394&epoch=2016',
    )
  })
  it('sends the mark itself for a slow star or none', () => {
    const slow = { ...barnard, pmra: 5, pmdec: -3 }
    expect(aboutUrl(aboutWhere({ ra: 10.5, dec: -2 }, { star: slow, sep: 0.5 }, gaia))).toBe('/api/about?ra=10.5&dec=-2')
    expect(aboutUrl(aboutWhere({ ra: 10.5, dec: -2 }, null, gaia))).toBe('/api/about?ra=10.5&dec=-2')
  })
})

describe('a fast mover near typed coordinates', () => {
  const typed = { pm: null, center: { ra: 133.795129, dec: -7.245147 }, gaia: null }
  it('names the SIMBAD star whose path crosses the typed position', () => {
    const about = { fast_movers: [{ name: 'WISEA J085510.74-071442.5', pm_arcsec_yr: 8.15, sep_arcsec: 127 }] }
    expect(fastHint(typed, about)).toBe(
      'A fast-moving star (WISEA J085510.74-071442.5, 8.2″/yr) is 127″ from here. Typed coordinates from an old catalogue may miss it — search it by name.',
    )
  })
  it('else uses a Gaia star of the answer: Barnard\'s Star seen from its J2000 coordinates', () => {
    const star = { source_id: '4472832130942575872', ra: 269.44850253, dec: 4.73942005, pmra: -801.551, pmdec: 10362.394, gmag: 8.2, xy: [] }
    const r = { pm: null, center: { ra: 269.452077, dec: 4.693365 }, gaia: { release: 'Gaia DR3', epoch_mjd: 57388.5, stars: [star] } }
    // its path crosses the J2000 position in 2000; in 2026.0 it is 26 × 10.39″ = 270″ away
    expect(fastHint(r, null)).toBe(
      'A fast-moving star (Gaia DR3 4472832130942575872, 10.4″/yr) is 270″ from here. Typed coordinates from an old catalogue may miss it — search it by name.',
    )
  })
  it('says nothing when the typed position is where the star is now (2026)', () => {
    const star = { source_id: '1', ra: 269.44850253, dec: 4.73942005, pmra: -801.551, pmdec: 10362.394, gmag: 8.2, xy: [] }
    const now = { ra: 269.44850253 - (0.801551 * 10) / 3600 / Math.cos((4.73942 * Math.PI) / 180), dec: 4.73942005 + (10.362394 * 10) / 3600 }
    expect(fastHint({ pm: null, center: now, gaia: { release: 'Gaia DR3', epoch_mjd: 57388.5, stars: [star] } }, null)).toBe(null)
  })
  it('says nothing for a named target or without a fast mover', () => {
    expect(fastHint({ ...typed, pm: { pmra: 1, pmdec: 1 } }, { fast_movers: [{ name: 'x', pm_arcsec_yr: 2, sep_arcsec: 3 }] })).toBe(null)
    expect(fastHint(typed, { fast_movers: [] })).toBe(null)
  })
})

describe('a mark on the target', () => {
  const r = { ...barnard, size_px: 49, center: { ra: 0, dec: 0 } } as unknown as Parameters<typeof onTarget>[0]
  it('is on the target near a predicted or measured position', () => {
    expect(onTarget(r, { x: 24.6, y: 23.4 })).toBe(true)
  })
  it('is not on the target 10 pixels away', () => {
    expect(onTarget(r, { x: 14.5, y: 24.5 })).toBe(false)
  })
})
