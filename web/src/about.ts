// "About this star": the answer of GET /api/about (docs/blink/api.md) and the three sentences of the card.
// Sentence 1 and 3 come from catalogs and Wikipedia (backend/about.py); sentence 2 comes from our own SPHEREx
// measurements in the frames answer. Pure functions, so the card can be tested without a browser.
import { brightestSeen, brightnessChange, KNOWN_ARCSEC, measuredMotion, motionClause, scatteredLight, yearOf } from './data'
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
  fast_movers?: { name: string; pm_arcsec_yr: number; sep_arcsec: number }[] | null // a position only; null: the search failed
}

type Measured = Pick<Result, 'pixel_arcsec' | 'pm' | 'detectors'> & {
  frames: Pick<Frame, 'mjd_mean' | 'ring' | 'centroid' | 'saturated' | 'photometry'>[]
}

/** Sentence 2: motion per year and direction, or the brightness change, or "too bright", from our frames only. */
export function measuredSentence(r: Measured) {
  const m = measuredMotion(r)
  if (m?.significant) return `${motionClause(m)}.`
  const change = brightnessChange(r.frames.flatMap((f) => (f.photometry ? [f.photometry] : [])))
  const points = r.frames.flatMap((f, frame) => (f.photometry ? [{ frame, phot: f.photometry }] : []))
  if (change && !brightestSeen(points, r.frames))
    return 'In our SPHEREx frames no source shows at this position, so its brightness numbers are sky noise.'
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
  const g = gmag != null ? ` has G = ${gmag.toFixed(1)} (Gaia brightness; larger is fainter)` : ' is there'
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

const hint = (name: string, pm: number, sep: number) =>
  `A fast-moving star (${name}, ${pm.toFixed(1)}″/yr) is ${Math.round(sep)}″ from here. Typed coordinates from an old catalogue may miss it — search it by name.`

/** How near a straight path (position at epoch, proper motion in mas/yr) passes a point between 1990 and 2030, and
 * how far it is from the point in 2026.0: [closest, now] in arcsec (flat sky, like backend/about.py path_near). */
export function pathNear(s: { ra: number; dec: number; pmra: number; pmdec: number }, epoch: number, p: { ra: number; dec: number }) {
  const dx = ((((p.ra - s.ra + 180) % 360) + 360) % 360 - 180) * Math.cos((s.dec * Math.PI) / 180) * 3600
  const dy = (p.dec - s.dec) * 3600
  const [vx, vy] = [s.pmra / 1000, s.pmdec / 1000]
  const t = Math.max(1990 - epoch, Math.min(2030 - epoch, (dx * vx + dy * vy) / (vx * vx + vy * vy)))
  return [Math.hypot(dx - vx * t, dy - vy * t), Math.hypot(dx - vx * (2026 - epoch), dy - vy * (2026 - epoch))]
}

/** NM2: typed coordinates (no proper motion) of a fast mover may be old. A star faster than 1″/yr whose path passes
 * within 60″ of the typed position: from SIMBAD (in the About answer), else from the Gaia stars of the frames answer. */
export function fastHint(r: Pick<Result, 'pm' | 'center' | 'gaia'>, about: Pick<About, 'fast_movers'> | null) {
  if (r.pm) return null
  const f = about?.fast_movers?.[0]
  if (f) return hint(f.name, f.pm_arcsec_yr, f.sep_arcsec)
  const epoch = r.gaia ? yearOf(r.gaia.epoch_mjd) : 2016
  const near = (r.gaia?.stars ?? [])
    .filter((s) => s.pmra != null && s.pmdec != null && Math.hypot(s.pmra, s.pmdec) > 1000)
    .map((s) => ({ s, path: pathNear(s as { ra: number; dec: number; pmra: number; pmdec: number }, epoch, r.center) }))
    .filter((x) => x.path[0] <= 60 && x.path[1] > 5) // not when the typed position is where the star is now
    .sort((a, b) => a.path[0] - b.path[0])[0]
  return near ? hint(`Gaia DR3 ${near.s.source_id}`, Math.hypot(near.s.pmra!, near.s.pmdec!) / 1000, near.path[1]) : null
}

/** True when a candidate mark is on the target (within 1.5 px of its predicted or measured position, or the view
 * center for typed coordinates): then the card tells about the target itself. */
export function onTarget(r: Pick<Result, 'frames' | 'pm' | 'size_px' | 'pixel_arcsec' | 'center'>, p: { x: number; y: number }) {
  const spots = r.frames.flatMap((f) => [f.ring, f.centroid].filter((s): s is NonNullable<typeof s> => !!s))
  if (!r.pm) spots.push({ x: r.size_px / 2, y: r.size_px / 2 })
  return spots.some((s) => Math.hypot(s.x - p.x, s.y - p.y) < 1.5)
}
