// Types of GET /api/frames (docs/blink/api.md) and pure helpers on them.
// Fields added for the redesign are optional, so an older backend still renders (the panels say what is missing).
import type { RaDec } from './sky'

export type XY = { x: number; y: number }
export type Range = [number, number]
export type Phot = { flux: number; err: number }
export type Centroid = XY & { ex: number; ey: number; saturated?: boolean }
export type Frame = {
  label: string
  mjd_mean: number
  date: string
  n_images: number
  png: string
  rgb_png?: string | null
  ring: XY | null
  saturated: boolean
  wavelength_um?: Range
  detectors?: string[]
  stack_detectors?: string[] // the detectors in png and photometry (the ones every frame has)
  centroid?: Centroid | null
  notes?: string[]
  photometry?: Phot | null
}
export type DetectorFrame = { group_index: number; png: string; n_images: number; photometry?: Phot | null; wavelength_um?: Range }
export type GaiaStar = {
  source_id: string
  ra: number
  dec: number
  pmra: number | null
  pmdec: number | null
  gmag: number | null
  xy: [number, number][]
  parallax?: number | null // mas
  parallax_over_error?: number | null
}
export type Gaia = { release: string; epoch_mjd: number; stars: GaiaStar[] }
export type Rgb = { method?: string; wavelength_um?: Partial<Record<'blue' | 'green' | 'red', Range>> } & Record<string, unknown>
export type Result = {
  query: string
  name: string | null
  center: RaDec
  pm: { pmra: number; pmdec: number } | null
  det: string | null
  fov_arcmin: number
  pixel_arcsec: number
  size_px: number
  frames: Frame[]
  detectors: Record<string, DetectorFrame[]>
  difference: { png: string; from: string; to: string; detectors?: string[] | null } | null
  n_images_used: number
  n_failed: number
  cached: boolean
  photometry_unit?: string
  gaia?: Gaia | null
  notes?: string[]
  quality?: { n_images_used: number; n_failed: number; epochs_dropped?: number; cache_age_s: number | null }
  rgb?: Rgb | null
}

const DAY_MS = 86_400_000
const MJD_UNIX = 40_587 // MJD of 1970-01-01
export const mjdOf = (iso: string) => Date.parse(iso + 'T00:00:00Z') / DAY_MS + MJD_UNIX
export const dateOf = (mjd: number) => new Date((mjd - MJD_UNIX) * DAY_MS).toISOString().slice(0, 10)
export const yearOf = (mjd: number) => 2000 + (mjd - 51_544.5) / 365.25

/** Epoch label ("2025-08-15 to 09-05", "2025-12-20 to 2026-01-10" or "2026-09-22") -> [first MJD, last MJD + 1). */
export function labelRange(label: string): Range | null {
  const m = /^(\d{4})-(\d{2}-\d{2})(?: to (\d{4}-)?(\d{2}-\d{2}))?$/.exec(label)
  if (!m) return null
  const start = mjdOf(`${m[1]}-${m[2]}`)
  const end = m[4] ? mjdOf(`${m[3] ? m[3].slice(0, 4) : m[1]}-${m[4]}`) : start
  return Number.isFinite(start) && Number.isFinite(end) ? [start, end + 1] : null
}

/** Candidates in the URL: "ra_dec_ra_dec" (decimal degrees; "_" and "-" stay readable in a query string). */
export const marksToParam = (marks: RaDec[]) => marks.map((m) => `${+m.ra.toFixed(5)}_${+m.dec.toFixed(5)}`).join('_')

export function marksFromParam(text: string | null): RaDec[] {
  const v = (text ?? '').split('_').map(Number)
  const out: RaDec[] = []
  for (let i = 0; i + 1 < v.length; i += 2) {
    const [ra, dec] = [v[i], v[i + 1]]
    if (Number.isFinite(ra) && Number.isFinite(dec) && ra >= 0 && ra < 360 && Math.abs(dec) <= 90) out.push({ ra, dec })
  }
  return out
}

/** The Gaia star closest to a PNG position, over all frames (a moving star is compared at each frame epoch). */
export function nearestGaia(view: { pixel_arcsec: number }, gaia: Gaia | null | undefined, p: XY) {
  let best: { star: GaiaStar; sep: number; frame: number } | null = null
  for (const star of gaia?.stars ?? [])
    star.xy.forEach(([x, y], frame) => {
      const sep = Math.hypot(x - p.x, y - p.y) * view.pixel_arcsec
      if (!best || sep < best.sep) best = { star, sep, frame }
    })
  return best as { star: GaiaStar; sep: number; frame: number } | null
}

export const KNOWN_ARCSEC = 3 // a candidate within 3" of a Gaia star is "known in catalog"

/** Brightness summary of measured points: the spread and how many sigma it is. */
export function brightnessChange(points: Phot[]) {
  if (points.length < 2) return null
  const lo = points.reduce((a, b) => (b.flux < a.flux ? b : a))
  const hi = points.reduce((a, b) => (b.flux > a.flux ? b : a))
  const mean = points.reduce((s, p) => s + p.flux, 0) / points.length
  const sigma = Math.hypot(lo.err, hi.err)
  return { lo, hi, mean, pct: mean ? ((hi.flux - lo.flux) / Math.abs(mean)) * 100 : 0, sigmas: sigma ? (hi.flux - lo.flux) / sigma : 0 }
}

/** Plain-language notes for one frame, from its flags. */
export function frameNotes(f: Frame) {
  const notes: string[] = []
  if (f.saturated) notes.push(f.centroid?.saturated ? 'Saturated core; position from the wings' : 'Saturated core')
  if (f.saturated && f.photometry === null) notes.push('no brightness')
  if (f.centroid === null && !f.notes?.length) notes.push('No source above 5σ at the target')
  for (const n of f.notes ?? []) notes.push(n[0].toUpperCase() + n.slice(1)) // e.g. no proper motion known for a typed RA/Dec
  if (f.n_images < 4) notes.push(`Only ${f.n_images} image${f.n_images === 1 ? '' : 's'}: noisy`)
  return notes
}

/** Proper motion in the units the panels show. */
export function motionOf(r: Result) {
  if (!r.pm) return null
  const total = Math.hypot(r.pm.pmra, r.pm.pmdec) // mas/yr
  const pa = ((Math.atan2(r.pm.pmra, r.pm.pmdec) * 180) / Math.PI + 360) % 360 // east of north
  const years = r.frames.length > 1 ? (r.frames[r.frames.length - 1].mjd_mean - r.frames[0].mjd_mean) / 365.25 : 0
  const pxPerYear = total / 1000 / r.pixel_arcsec
  return { total, pa, pxPerYear, years, shiftPx: pxPerYear * years }
}

export const DETECTOR_IDS = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6'] as const

/** First-of-month MJDs between a and b, thinned to at most max labels. */
export function monthTicks(a: number, b: number, max: number) {
  const out: number[] = []
  const d = new Date(dateOf(a) + 'T00:00:00Z')
  d.setUTCDate(1)
  for (d.setUTCMonth(d.getUTCMonth() + 1); d.getTime() / DAY_MS + MJD_UNIX <= b; d.setUTCMonth(d.getUTCMonth() + 1))
    out.push(d.getTime() / DAY_MS + MJD_UNIX)
  const step = Math.ceil(out.length / max)
  return out.filter((_, i) => i % step === 0)
}

const COMPASS = ['north', 'north-northeast', 'northeast', 'east-northeast', 'east', 'east-southeast', 'southeast', 'south-southeast',
  'south', 'south-southwest', 'southwest', 'west-southwest', 'west', 'west-northwest', 'northwest', 'north-northwest']
/** Position angle (degrees east of north) -> a 16-point compass word. */
export const compass = (pa: number) => COMPASS[Math.round((((pa % 360) + 360) % 360) / 22.5) % 16]

type Track = Pick<Result, 'pixel_arcsec' | 'pm'> & { frames: Pick<Frame, 'mjd_mean' | 'ring' | 'centroid'>[] }

/** Shift between two PNG positions: arcsec, pixels and position angle (x grows to the west, y to the south). */
function shiftOf(a: XY, b: XY, s: number) {
  const px = Math.hypot(b.x - a.x, b.y - a.y)
  return { px, arcsec: px * s, pa: ((Math.atan2(-(b.x - a.x), -(b.y - a.y)) * 180) / Math.PI + 360) % 360 }
}

/** Measured motion between the first and the last frame with a centroid, and the catalogue prediction for the same frames. */
export function measuredMotion(r: Track) {
  const meas = r.frames.filter((f) => f.centroid)
  if (meas.length < 2) return null
  const a = meas[0]
  const b = meas[meas.length - 1]
  const ca = a.centroid!
  const cb = b.centroid!
  const shift = shiftOf(ca, cb, r.pixel_arcsec)
  const sigmaPx = Math.hypot(ca.ex, cb.ex, ca.ey, cb.ey) / Math.SQRT2 // 1 sigma of the shift, both axes averaged
  const pred = r.pm && a.ring && b.ring ? shiftOf(a.ring, b.ring, r.pixel_arcsec) : null
  // agree: the measured and the predicted shift differ by less than 3 sigma (and never ask for better than 0.5 px)
  const agree = pred ? Math.hypot(cb.x - ca.x - (b.ring!.x - a.ring!.x), cb.y - ca.y - (b.ring!.y - a.ring!.y)) < Math.max(3 * sigmaPx, 0.5) : null
  return { ...shift, days: b.mjd_mean - a.mjd_mean, sigmaPx, significant: shift.px >= 3 * sigmaPx, pred, agree }
}

const span = (days: number) =>
  days < 45 ? `${Math.round(days)} days` : days < 730 ? `${Math.round(days / 30.44)} months` : `${(days / 365.25).toFixed(1)} years`

const perYear = (arcsec: number, days: number) => (arcsec / (days / 365.25)).toFixed(1)

/** The measured motion in the words that the Motion panel and About share: one number, per year, from our frames. */
export const motionClause = (m: NonNullable<ReturnType<typeof measuredMotion>>) =>
  `In our SPHEREx frames it moves about ${perYear(m.arcsec, m.days)}″ per year toward the ${compass(m.pa)}`

/** One plain sentence for the Motion panel: how fast, which way, over how long, and whether the catalogue agrees. */
export function motionSentence(r: Track) {
  const m = measuredMotion(r)
  if (!m)
    return r.pm
      ? 'SPHEREx did not measure its position in two frames, so there is no measured motion here.'
      : 'No proper motion is known for a typed position, so there is no predicted position to measure.'
  const t = span(m.days)
  const moved = m.significant
    ? `${motionClause(m)} (${m.px.toFixed(1)} pixels in ${t})`
    : `In our SPHEREx frames it does not move measurably in ${t} (less than ${perYear(3 * m.sigmaPx * r.pixel_arcsec, m.days)}″ per year)`
  if (!m.pred) return `${moved}. No catalogue motion is known for a typed position.`
  const cat = `${perYear(m.pred.arcsec, m.days)}″ per year`
  if (m.significant && m.agree) return `${moved}, as its catalogue motion predicts (${cat}).`
  return `${moved}; its catalogue motion is ${cat}${m.significant ? ` toward the ${compass(m.pred.pa)}` : ''}.`
}

/** A source stands out where the brightness is measured: a centroid in that frame, or a flux of 5 sigma or more.
 * Without one, a "change" is only sky noise (typed coordinates of a star that has moved away). */
export const sourceSeen = (f: Pick<Frame, 'centroid'>, p: Phot | null | undefined) => !!f.centroid || (!!p && p.flux >= 5 * p.err)

/** SIMBAD prefixes and spacing do not make a different name: "V* R Dra" is "R Dra". */
const bare = (s: string) =>
  s
    .replace(/^(NAME|V\*|\*\*|\*|EM\*)\s+/i, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()

/** Heading: the name the user typed, plus the catalog id when it is a different name ("Kapteyn's Star · HD 33793"). */
export function titleOf(r: Pick<Result, 'query' | 'name'>) {
  return { title: r.query.trim(), catalog: r.name && bare(r.name) !== bare(r.query) ? r.name : null }
}

/** Gaia stars drawn by default: brighter than G 17, at most the 40 brightest (Barnard's field has 151). */
export const brightGhosts = (stars: GaiaStar[]) =>
  stars
    .filter((s) => s.gmag != null && s.gmag < 17)
    .sort((a, b) => a.gmag! - b.gmag!)
    .slice(0, 40)

/** True when the detector with the largest brightness change is D1 or D2: probably scattered light (issue #5). */
export function scatteredLight(r: Pick<Result, 'detectors'>) {
  let best: [string, number] | null = null
  for (const [d, items] of Object.entries(r.detectors)) {
    const c = brightnessChange(items.flatMap((x) => (x.photometry ? [x.photometry] : [])))
    if (c && (!best || c.pct > best[1])) best = [d, c.pct]
  }
  return !!best && (best[0] === 'D1' || best[0] === 'D2')
}
