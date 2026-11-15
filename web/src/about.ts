// "About this star": the answer of GET /api/about (docs/blink/api.md) and the three sentences of the card.
// Sentence 1 and 3 come from catalogs and Wikipedia (backend/about.py); sentence 2 comes from our own SPHEREx
// measurements in the frames answer. Pure functions, so the card can be tested without a browser.
import { brightnessChange, compass, KNOWN_ARCSEC, measuredMotion, scatteredLight, yearOf } from './data'
import type { Frame, Gaia, GaiaStar, Result } from './data'

export type About = {
  name: string | null
  object_type: string | null
  spectral_type: string | null
  distance_ly: number | null
  aliases: string[]
  facts_sentence: string | null
  history_sentence: string | null
  history_source: { title: string; url: string; license: string } | null
  papers: number | null
  sources: { label: string; url: string }[]
  notes: string[]
}

type Measured = Pick<Result, 'pixel_arcsec' | 'pm' | 'detectors'> & {
  frames: Pick<Frame, 'mjd_mean' | 'ring' | 'centroid' | 'saturated' | 'photometry'>[]
}

/** Sentence 2: motion per year and direction, or the brightness change, or "too bright", from our frames only. */
export function measuredSentence(r: Measured) {
  const m = measuredMotion(r)
  if (m?.significant)
    return `In our SPHEREx frames it moves about ${(m.arcsec / (m.days / 365.25)).toFixed(1)}″ per year toward the ${compass(m.pa)}.`
  const change = brightnessChange(r.frames.flatMap((f) => (f.photometry ? [f.photometry] : [])))
  if (change) {
    if (change.sigmas < 3) return `In our SPHEREx frames it does not move measurably, and its brightness stays within the noise.`
    if (scatteredLight(r)) return 'In our SPHEREx frames its brightness changes, but that may be scattered light (known issue #5).'
    const size = change.lo.flux > 0 ? `${(change.hi.flux / change.lo.flux).toFixed(1)}×` : `by ${+(change.hi.flux - change.lo.flux).toPrecision(3)} mJy`
    return `In our SPHEREx frames its brightness changes ${size} between surveys (${change.sigmas.toFixed(1)}σ).`
  }
  if (r.frames.some((f) => f.saturated)) return 'It is too bright for SPHEREx to measure here.'
  if (m) return 'In our SPHEREx frames it does not move measurably.'
  return r.pm
    ? 'SPHEREx measures nothing here: no source stands out at the target.'
    : 'No proper motion is known for a typed position, so SPHEREx measures no motion for it here.'
}

/** Sentence 2 for a candidate away from the target: the tool measures only at the target. */
export const MARK_SENTENCE = 'This tool measures motion and brightness only at the target, so compare this mark between frames by eye.'

const lightYears = (d: number) => (d < 20 ? d.toFixed(1) : d < 100 ? d.toFixed(0) : Number(d.toPrecision(2)).toLocaleString('en-US'))

/** Sentence 1 for a position that SIMBAD does not name: what Gaia DR3 says about the nearest star. */
export function gaiaSentence(hit: { star: GaiaStar; sep: number; frame: number } | null, release: string) {
  if (!hit) return `No ${release} star is in this view.`
  if (hit.sep >= 3) return `No ${release} star is within 3″; the nearest is ${hit.sep.toFixed(1)}″ away.`
  const { gmag, parallax, parallax_over_error: snr } = hit.star
  const g = gmag != null ? ` has G = ${gmag.toFixed(1)}` : ' is there'
  const far = parallax && parallax > 0 && (snr ?? 0) >= 5 ? ` and lies about ${lightYears(3261.56 / parallax)} light-years away (parallax ${parallax.toFixed(2)} mas)` : ''
  return `The nearest ${release} star, ${hit.sep.toFixed(1)}″ away,${g}${far}.`
}

/** Sentence 3: the quoted Wikipedia sentence, else the SIMBAD paper count, else "unknown". */
export const LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/'

export function historyLine(a: Pick<About, 'history_sentence' | 'history_source' | 'papers'> | null) {
  if (a?.history_sentence && a.history_source)
    return { text: `“${a.history_sentence}”`, url: a.history_source.url, license: a.history_source.license }
  if (a?.papers) return { text: `SIMBAD lists ${a.papers.toLocaleString('en-US')} papers about it.`, url: '', license: '' }
  return { text: 'Its history is unknown here.', url: '', license: '' }
}

/** The request for a target (by its typed name, or by position for typed coordinates) or for a marked candidate. */
type Where = { q?: string; ra?: number; dec?: number; pmra?: number; pmdec?: number; epoch?: number }
export const aboutUrl = (p: Where) =>
  `/api/about?${new URLSearchParams(Object.entries(p).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))}`

/** Where to ask about a position. On a Gaia star faster than 1″/yr, send its Gaia position, epoch and proper motion:
 * SIMBAD lists positions at J2000, and such a star has moved out of the 5″ cone since then (Barnard's Star: 270″). */
export function aboutWhere(p: { ra: number; dec: number }, hit: { star: GaiaStar; sep: number } | null, gaia: Gaia | null | undefined): Where {
  const s = hit?.star
  if (gaia && s && hit.sep < KNOWN_ARCSEC && s.pmra != null && s.pmdec != null && Math.hypot(s.pmra, s.pmdec) > 1000)
    return { ra: s.ra, dec: s.dec, pmra: s.pmra, pmdec: s.pmdec, epoch: +yearOf(gaia.epoch_mjd).toFixed(2) }
  return { ra: p.ra, dec: p.dec }
}

/** True when a candidate mark is on the target (within 1.5 px of its predicted or measured position, or the view
 * center for typed coordinates): then the card tells about the target itself. */
export function onTarget(r: Pick<Result, 'frames' | 'pm' | 'size_px' | 'pixel_arcsec' | 'center'>, p: { x: number; y: number }) {
  const spots = r.frames.flatMap((f) => [f.ring, f.centroid].filter((s): s is NonNullable<typeof s> => !!s))
  if (!r.pm) spots.push({ x: r.size_px / 2, y: r.size_px / 2 })
  return spots.some((s) => Math.hypot(s.x - p.x, s.y - p.y) < 1.5)
}
