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
  centroid?: Centroid | null
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
  difference: { png: string; from: string; to: string } | null
  n_images_used: number
  n_failed: number
  cached: boolean
  photometry_unit?: string
  gaia?: Gaia | null
  notes?: string[]
  quality?: { n_images_used: number; n_failed: number; cache_age_s: number | null }
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
  if (f.centroid === null) notes.push('No source above 5σ at the target')
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
