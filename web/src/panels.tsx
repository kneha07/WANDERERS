// Instrument panels. Every value comes from the API answer (docs/blink/api.md); nothing is hard-coded.
import { Component, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { brightnessChange, dateOf, frameNotes, monthTicks, motionOf, motionSentence, nearestGaia, scatteredLight, sourceSeen, yearOf } from './data'
import type { Frame, Phot, Result } from './data'
import { decText, raText, skyToPixel } from './sky'
import type { RaDec } from './sky'
import { aboutUrl, aboutWhere, gaiaSentence, historyLine, LICENSE_URL, MARK_SENTENCE, measuredSentence, onTarget } from './about'
import type { About } from './about'

// ---------- shared pieces ----------

export const AlertIcon = () => (
  <svg className="icon" viewBox="0 0 20 20" aria-hidden="true">
    <path d="M10 2 19 18H1Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    <path d="M10 8v4.5M10 14.6v.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
)

/** Catches a render error in one panel, so the rest of the viewer keeps working. */
export class Boundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="state error" role="alert">
        <AlertIcon />
        <p>
          {this.props.name} failed ({this.state.error.message}). The flipbook and the other panels still work.
        </p>
        <button type="button" onClick={() => this.setState({ error: null })}>
          Retry panel
        </button>
      </div>
    )
  }
}

/** busy: while another target loads, a panel that still shows the previous one says so and is dimmed. */
export function Panel({ id, title, actions, busy, children }: { id: string; title: string; actions?: ReactNode; busy?: string; children: ReactNode }) {
  return (
    <section className="panel" id={id} aria-labelledby={`${id}-title`} aria-busy={!!busy} data-stale={!!busy}>
      <header className="panel-head">
        <h2 className="panel-title" id={`${id}-title`}>
          {title}
        </h2>
        {actions}
      </header>
      <div className="panel-body">
        {busy && <p className="stale-note">{busy}</p>}
        <Boundary name={title}>{children}</Boundary>
      </div>
    </section>
  )
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="muted">{children}</p>

export const Skeleton = ({ lines = 3 }: { lines?: number }) => (
  <div aria-hidden="true">
    {Array.from({ length: lines }, (_, i) => (
      <div key={i} className="skeleton" style={{ height: 14, width: `${90 - i * 15}%`, marginTop: i ? 8 : 0, borderRadius: 4 }} />
    ))}
  </div>
)

const fix = (v: number, d: number) => (Number.isFinite(v) ? v.toFixed(d) : '–')
const signed = (v: number, d: number) => (v >= 0 ? '+' : '') + v.toFixed(d)
const um = (w?: [number, number]) => (w ? `${w[0].toFixed(2)}–${w[1].toFixed(2)}` : '–')

function ago(seconds: number) {
  if (seconds < 90) return `${Math.round(seconds)} s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 172_800) return `${(seconds / 3600).toFixed(1)} h ago`
  return `${Math.round(seconds / 86_400)} days ago`
}

/** Nice axis steps for a span. */
function ticks(lo: number, hi: number, count = 4) {
  const raw = (hi - lo) / count
  const p = 10 ** Math.floor(Math.log10(raw || 1))
  const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10))
  return out
}

// ---------- about this star ----------

const aboutAnswers = new Map<string, Promise<About>>() // url -> answer: a tab switch or a second open is instant

export function fetchAbout(url: string) {
  let p = aboutAnswers.get(url)
  if (!p) {
    p = fetch(url, { signal: AbortSignal.timeout(20_000) }).then(async (res) => {
      const body = await res.json().catch(() => null)
      if (!res.ok || !body) throw new Error(body?.detail ?? `HTTP ${res.status}`)
      return body as About
    })
    p.catch(() => aboutAnswers.delete(url)) // a failure is asked again next time
    aboutAnswers.set(url, p)
  }
  return p
}

/** The About request for the current target: by its typed name, or by position for typed coordinates. */
export function targetAboutUrl(r: Result) {
  if (r.name) return aboutUrl({ q: r.query })
  const at = r.frames.find((f) => f.ring)?.ring ?? { x: r.size_px / 2, y: r.size_px / 2 }
  return aboutUrl(aboutWhere(r.center, nearestGaia(r, r.gaia, at), r.gaia))
}

/** Three short sentences about the target, or about a marked candidate: (1) catalog facts, (2) our SPHEREx
 * measurement, (3) one history sentence from Wikipedia or the SIMBAD paper count. Sources are linked below. */
export function AboutCard({ r, mark }: { r: Result; mark?: RaDec }) {
  const at = mark ? skyToPixel(r, mark) : (r.frames.find((f) => f.ring)?.ring ?? { x: r.size_px / 2, y: r.size_px / 2 })
  const self = !mark || onTarget(r, at)
  const hit = nearestGaia(r, r.gaia, at)
  const url = self ? targetAboutUrl(r) : aboutUrl(aboutWhere(mark!, hit, r.gaia))
  const [got, setGot] = useState<{ url: string; data?: About; error?: string }>({ url: '' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    fetchAbout(url).then(
      (data) => live && setGot({ url, data }),
      (e) => live && setGot({ url, error: String(e?.message ?? e) }),
    )
    return () => {
      live = false
    }
  }, [url, attempt])
  const a = got.url === url ? got.data : undefined
  const error = got.url === url ? got.error : undefined
  const loading = !a && !error
  const byName = self && !!r.name
  const failed = a?.notes.some((n) => n.includes('did not answer'))
  const first = a?.facts_sentence
    ? a.facts_sentence
    : error
      ? 'The catalog facts did not load.'
      : !byName && r.gaia
        ? gaiaSentence(hit, r.gaia.release)
        : failed
          ? 'The catalogs did not answer, so its facts are missing for now.'
          : byName
            ? 'The catalogs list no facts about it.'
            : 'No catalog object is known at this position.'
  const history = historyLine(a ?? null)
  const bar = (w: number) => <span className="skeleton" style={{ display: 'block', height: 14, width: `${w}%`, borderRadius: 4, margin: '4px 0' }} />
  return (
    <div className="about" aria-busy={loading}>
      <ol className="about-lines">
        <li>{loading ? <>{bar(95)}{bar(70)}</> : first}</li>
        <li>{self ? measuredSentence(r) : MARK_SENTENCE}</li>
        <li>
          {loading ? (
            <>
              {bar(90)}
              {bar(55)}
            </>
          ) : error ? (
            'History unavailable right now.'
          ) : (
            <>
              {history.text}
              {history.license && (
                <>
                  {' — '}
                  <a href={history.url} target="_blank" rel="noreferrer">
                    Wikipedia
                  </a>
                  ,{' '}
                  <a href={LICENSE_URL} target="_blank" rel="noreferrer">
                    {history.license}
                  </a>
                </>
              )}
            </>
          )}
        </li>
      </ol>
      <p className="hint about-sources">
        Sources:{' '}
        {(a?.sources ?? []).map((s) => (
          <span key={s.url}>
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.label}
            </a>
            {' · '}
          </span>
        ))}
        {!byName && !a?.facts_sentence && r.gaia ? `${r.gaia.release} (this answer) · ` : ''}
        SPHEREx measurements (this tool)
        {error && (
          <button type="button" className="about-retry" onClick={() => setAttempt((n) => n + 1)}>
            Retry
          </button>
        )}
      </p>
    </div>
  )
}

// ---------- target ----------

export function TargetCard({ r }: { r: Result }) {
  const m = motionOf(r)
  const ring = r.frames.find((f) => f.ring)?.ring ?? { x: r.size_px / 2, y: r.size_px / 2 }
  const gaia = nearestGaia(r, r.gaia, ring)
  const match = gaia && gaia.sep < r.pixel_arcsec * 1.5 ? gaia : null
  return (
    <dl className="kv">
      <dt>Name</dt>
      <dd>
        {r.name ?? 'Sky position (no name)'}
        <span className="sub">Query: {r.query}</span>
      </dd>
      <dt>Catalog id</dt>
      <dd>
        {match ? `${r.gaia!.release} ${match.star.source_id}` : r.gaia ? 'No Gaia star at the target' : 'Gaia data not in this answer'}
        {match && <span className="sub">nearest Gaia star to the target, {match.sep.toFixed(1)}″</span>}
      </dd>
      <dt>RA</dt>
      <dd>
        {raText(r.center.ra)}
        <span className="sub">{r.center.ra.toFixed(5)}°</span>
      </dd>
      <dt>Dec</dt>
      <dd>
        {decText(r.center.dec)}
        <span className="sub">{signed(r.center.dec, 5)}°</span>
      </dd>
      <dt>Position epoch</dt>
      <dd>
        {r.pm ? 'J2026.0' : 'as entered'}
        <span className="sub">{r.pm ? 'moved by the catalog proper motion' : 'no proper motion known'}</span>
      </dd>
      <dt>Proper motion</dt>
      <dd>
        {m ? (
          <>
            {fix(m.total, 1)} mas/yr · {fix(m.pxPerYear, 2)} px/yr
            <span className="sub">
              μα* {fix(r.pm!.pmra, 1)}, μδ {fix(r.pm!.pmdec, 1)} mas/yr · PA {fix(m.pa, 0)}° · {fix(m.shiftPx, 2)} px over{' '}
              {fix(m.years, 2)} yr of frames (at {r.pixel_arcsec}″/px)
            </span>
          </>
        ) : (
          'unknown (search by name to get it)'
        )}
      </dd>
      <dt>Field</dt>
      <dd>
        {r.fov_arcmin}′ · {r.size_px} × {r.size_px} px
        <span className="sub">{r.pixel_arcsec}″ per pixel · north up, east left</span>
      </dd>
    </dl>
  )
}

// ---------- data quality ----------

export function QualityPanel({ r }: { r: Result }) {
  const q = r.quality
  const dets = [...new Set(r.frames.flatMap((f) => f.detectors ?? []))].sort()
  const sat = r.frames.filter((f) => f.saturated).length
  const notes = r.notes ?? []
  return (
    <>
      <dl className="kv">
        <dt>Images used</dt>
        <dd>{q?.n_images_used ?? r.n_images_used}</dd>
        <dt>Images failed</dt>
        <dd>{q?.n_failed ?? r.n_failed}</dd>
        <dt>Frames</dt>
        <dd>
          {r.frames.length} survey epochs
          <span className="sub">
            {r.frames[0]?.label} … {r.frames[r.frames.length - 1]?.label}
          </span>
        </dd>
        <dt>Detectors</dt>
        <dd>{dets.length ? dets.join(' ') : Object.keys(r.detectors).sort().join(' ') || '–'}</dd>
        <dt>Saturated frames</dt>
        <dd>
          {sat} of {r.frames.length}
        </dd>
        <dt>Gaia overlay</dt>
        <dd>
          {r.gaia ? `${r.gaia.stars.length} stars, ${r.gaia.release}` : r.gaia === null ? 'off (no Gaia answer)' : 'not in this answer'}
          {r.gaia && <span className="sub">moved from epoch {yearOf(r.gaia.epoch_mjd).toFixed(1)} to each frame</span>}
        </dd>
        <dt>Cache</dt>
        <dd>
          {r.cached ? 'from the server cache' : 'freshly built'}
          {q?.cache_age_s != null && <span className="sub">built {ago(q.cache_age_s)}</span>}
        </dd>
      </dl>
      {notes.length > 0 ? (
        <ul className="hint">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : (
        <p className="hint">{r.notes ? 'No warnings from the server.' : 'This answer has no notes field.'}</p>
      )}
    </>
  )
}

// ---------- frames table ----------

type Col = { key: string; label: string; value: (f: Frame, i: number) => string | number }
const COLS: Col[] = [
  { key: 'i', label: '#', value: (_, i) => i },
  { key: 'label', label: 'Epoch', value: (f) => f.mjd_mean },
  { key: 'date', label: 'Mean date', value: (f) => f.mjd_mean },
  { key: 'mjd', label: 'MJD', value: (f) => f.mjd_mean },
  { key: 'n', label: 'Images', value: (f) => f.n_images },
  { key: 'det', label: 'Detectors', value: (f) => f.detectors?.length ?? 0 },
  { key: 'wl', label: 'λ (µm)', value: (f) => f.wavelength_um?.[0] ?? 0 },
  { key: 'sat', label: 'Saturated', value: (f) => Number(f.saturated) },
  { key: 'notes', label: 'Notes', value: (f) => frameNotes(f).join(' ') },
]

export function FramesTable({ r, index, onPick }: { r: Result; index: number; onPick: (i: number) => void }) {
  const [sort, setSort] = useState({ key: 'i', dir: 1 })
  const col = COLS.find((c) => c.key === sort.key)!
  const rows = r.frames
    .map((f, i) => ({ f, i }))
    .sort((a, b) => {
      const x = col.value(a.f, a.i)
      const y = col.value(b.f, b.i)
      return (x < y ? -1 : x > y ? 1 : a.i - b.i) * sort.dir
    })
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">SPHEREx frames, one per survey epoch. Sort with the column buttons.</caption>
        <thead>
          <tr>
            {COLS.map((c) => (
              <th key={c.key} aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}>
                <button type="button" onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? -s.dir : 1 }))}>
                  {c.label}
                  <span aria-hidden="true">{sort.key === c.key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ f, i }) => (
            <tr key={f.label} aria-current={i === index ? 'true' : undefined}>
              <td>
                <button type="button" onClick={() => onPick(i)} aria-label={`Show frame ${i + 1}, ${f.label}`}>
                  {i + 1}
                </button>
              </td>
              <td>{f.label}</td>
              <td>{f.date}</td>
              <td>{f.mjd_mean.toFixed(4)}</td>
              <td>{f.n_images}</td>
              <td>
                {f.detectors?.join(' ') ?? '–'}
                {f.stack_detectors && f.detectors && f.stack_detectors.length < f.detectors.length && (
                  <span className="sub">image: {f.stack_detectors.join(' ')}</span>
                )}
              </td>
              <td>{um(f.wavelength_um)}</td>
              <td className={f.saturated ? 'yes' : undefined}>{f.saturated ? 'yes' : 'no'}</td>
              <td className="wrap">{frameNotes(f).join('; ') || '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------- motion ----------

export function MotionPanel({ r, index, onPick }: { r: Result; index: number; onPick: (i: number) => void }) {
  if (!r.frames.some((f) => f.centroid !== undefined))
    return <Empty>This API answer has no measured positions (the centroid field). Update the backend to see them.</Empty>
  const s = r.pixel_arcsec
  const n = r.size_px
  const pts = r.frames.map((f, i) => ({ i, ring: f.ring, c: f.centroid ?? null }))
  const xs = pts.flatMap((p) => [...(p.ring ? [p.ring.x] : []), ...(p.c ? [p.c.x - p.c.ex, p.c.x + p.c.ex] : [])])
  const ys = pts.flatMap((p) => [...(p.ring ? [p.ring.y] : []), ...(p.c ? [p.c.y - p.c.ey, p.c.y + p.c.ey] : [])])
  if (!xs.length)
    return (
      <Empty>
        {r.pm
          ? 'No source stands out at the target in any frame (all peaks below 5σ).'
          : 'No proper motion is known for a typed position, so there is no predicted position to measure. Search by name to get the motion.'}
      </Empty>
    )
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2
  const h = Math.max(1, (Math.max(...xs) - Math.min(...xs)) / 2, (Math.max(...ys) - Math.min(...ys)) / 2) * 1.25
  const L = 56
  const T = 12
  const W = 300
  const X = (x: number) => L + ((x - (cx - h)) / (2 * h)) * W
  const Y = (y: number) => T + ((y - (cy - h)) / (2 * h)) * W
  // Axis values: arcsec from the view center, east positive (to the left), north positive (up).
  const ex = (x: number) => -(x - n / 2) * s
  const ny = (y: number) => (n / 2 - y) * s
  const xt = ticks(ex(cx + h), ex(cx - h))
  const yt = ticks(ny(cy + h), ny(cy - h))
  const toX = (v: number) => X(n / 2 - v / s)
  const toY = (v: number) => Y(n / 2 - v / s)
  const rings = pts.filter((p) => p.ring)
  const meas = pts.filter((p) => p.c)
  const shift = (a?: { x: number; y: number } | null, b?: { x: number; y: number } | null) =>
    a && b ? { sep: Math.hypot(b.x - a.x, b.y - a.y) * s, pa: ((Math.atan2(-(b.x - a.x), -(b.y - a.y)) * 180) / Math.PI + 360) % 360 } : null
  const words = (m: ReturnType<typeof shift>) => (!m ? '–' : m.sep < 0.05 ? 'no motion' : `${m.sep.toFixed(1)}″ toward PA ${m.pa.toFixed(0)}°`)
  const measured = shift(meas[0]?.c, meas[meas.length - 1]?.c)
  const predicted = shift(rings[0]?.ring, rings[rings.length - 1]?.ring)
  return (
    <>
      <p className="plain">{motionSentence(r)}</p>
      <svg className="chart" viewBox={`0 0 ${L + W + 12} ${T + W + 44}`} style={{ maxWidth: 460 }} role="img" aria-labelledby="motion-desc">
        <desc id="motion-desc">
          Predicted target positions (dashed line) and measured positions with error bars, one per frame, north up, east left.
        </desc>
        {xt.map((v) => (
          <g key={`x${v}`}>
            <line className="grid-line" x1={toX(v)} x2={toX(v)} y1={T} y2={T + W} />
            <text x={toX(v)} y={T + W + 14} textAnchor="middle">
              {v}
            </text>
          </g>
        ))}
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line className="grid-line" x1={L} x2={L + W} y1={toY(v)} y2={toY(v)} />
            <text x={L - 6} y={toY(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        <rect x={L} y={T} width={W} height={W} fill="none" className="grid-line" />
        <text className="axis-title" x={L + W / 2} y={T + W + 34} textAnchor="middle">
          ΔRA cos δ (″) · east ←
        </text>
        <text className="axis-title" transform={`translate(14 ${T + W / 2}) rotate(-90)`} textAnchor="middle">
          ΔDec (″) · north ↑
        </text>
        {rings.length > 1 && <polyline className="predicted" points={rings.map((p) => `${X(p.ring!.x)},${Y(p.ring!.y)}`).join(' ')} />}
        {rings.map((p) => (
          <circle key={`r${p.i}`} className="pred-dot" cx={X(p.ring!.x)} cy={Y(p.ring!.y)} r={2.5} />
        ))}
        {meas.map(({ i, c }) => (
          <g key={`m${i}`} onClick={() => onPick(i)} style={{ cursor: 'pointer' }}>
            <line className="err" x1={X(c!.x - c!.ex)} x2={X(c!.x + c!.ex)} y1={Y(c!.y)} y2={Y(c!.y)} />
            <line className="err" x1={X(c!.x)} x2={X(c!.x)} y1={Y(c!.y - c!.ey)} y2={Y(c!.y + c!.ey)} />
            <circle className={c!.saturated ? 'meas hollow' : 'meas'} cx={X(c!.x)} cy={Y(c!.y)} r={4} />
            {i === index && <circle className="current-ring" cx={X(c!.x)} cy={Y(c!.y)} r={8} />}
            <text className="label-data" x={X(c!.x) + 8} y={Y(c!.y) - 6}>
              {i + 1}
            </text>
          </g>
        ))}
      </svg>
      <ul className="legend">
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <path d="M0 6h18" className="predicted" style={{ stroke: 'var(--amber)', strokeDasharray: '5 3' }} />
          </svg>{' '}
          predicted (ring, catalog proper motion)
        </li>
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <circle cx="9" cy="6" r="4" style={{ fill: 'var(--data)' }} />
          </svg>{' '}
          measured centroid ±1σ
        </li>
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <circle cx="9" cy="6" r="4" style={{ fill: 'none', stroke: 'var(--data)', strokeWidth: 2 }} />
          </svg>{' '}
          measured from the wings (saturated core)
        </li>
      </ul>
      <p className="summary">
        Measured: {words(measured)} · Predicted: {predicted ? words(predicted) : 'no proper motion'}
        {meas.length > 1 && ` (frame ${meas[0].i + 1} → ${meas[meas.length - 1].i + 1})`}
      </p>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Predicted and measured target position per frame</caption>
          <thead>
            <tr>
              <th>#</th>
              <th>Predicted x, y (px)</th>
              <th>Measured x, y ± (px)</th>
              <th>Offset (″)</th>
            </tr>
          </thead>
          <tbody>
            {pts.map(({ i, ring, c }) => (
              <tr key={i} aria-current={i === index ? 'true' : undefined}>
                <td>{i + 1}</td>
                <td>{ring ? `${ring.x.toFixed(2)}, ${ring.y.toFixed(2)}` : '–'}</td>
                <td>
                  {c
                    ? `${c.x.toFixed(2)} ± ${c.ex.toFixed(2)}, ${c.y.toFixed(2)} ± ${c.ey.toFixed(2)}`
                    : r.pm
                      ? 'no source above 5σ'
                      : 'no predicted position (no proper motion known)'}
                  {c?.saturated ? ' (wings)' : ''}
                </td>
                <td>{c && ring ? (Math.hypot(c.x - ring.x, c.y - ring.y) * s).toFixed(2) : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

// ---------- brightness ----------

type Point = { x: number; frame: number; phot: Phot | null; tag: string }

/** Frame numbers as short text: [2, 3] -> '2–3', [1, 3, 4] -> '1, 3–4'. */
export function spans(nums: number[]) {
  const out: string[] = []
  for (let i = 0; i < nums.length; i++) {
    let j = i
    while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++
    out.push(j > i ? `${nums[i]}–${nums[j]}` : `${nums[i]}`)
    i = j
  }
  return out.join(', ')
}

const fmt = (p: Phot) => `${+p.flux.toPrecision(4)} ± ${+p.err.toPrecision(2)}`

export function BrightnessPanel({ r, index, deepLink }: { r: Result; index: number; deepLink?: string }) {
  const [series, setSeries] = useState<string | null>(null)
  if (!r.frames.some((f) => f.photometry !== undefined))
    return <Empty>This API answer has no photometry. Update the backend to see the brightness per frame.</Empty>
  const dets = Object.keys(r.detectors).sort()
  const ofStack = (): Point[] => r.frames.map((f, i) => ({ x: f.mjd_mean, frame: i, phot: f.photometry ?? null, tag: 'stack' }))
  const ofDet = (d: string): Point[] =>
    r.detectors[d].map((x) => ({ x: r.frames[x.group_index].mjd_mean, frame: x.group_index, phot: x.photometry ?? null, tag: d }))
  // How many surveys each series measured. The panel opens on the series with the most (the stack wins a tie);
  // when no series has two points, it shows every detector at once, so no measurement is hidden.
  const counts = [['stack', r.frames.filter((f) => f.photometry).length] as const, ...dets.map((d) => [d, ofDet(d).filter((p) => p.phot).length] as const)]
  const most = counts.reduce((a, b) => (b[1] > a[1] ? b : a))
  const pick = series && (series === 'stack' || series === 'each' || r.detectors[series]) ? series : most[1] >= 2 ? most[0] : 'each'
  const groups = pick === 'stack' ? [ofStack()] : pick === 'each' ? dets.map(ofDet) : [ofDet(pick)]
  const all = groups.flat()
  const good = all.filter((p) => p.phot)
  const seen = new Set(good.map((p) => p.frame))
  const missing = [...new Set(all.filter((p) => !p.phot && !seen.has(p.frame)).map((p) => p.frame))].sort((a, b) => a - b)
  const sat = missing.filter((f) => r.frames[f].saturated).map((f) => f + 1)
  const gap = missing.filter((f) => !r.frames[f].saturated).map((f) => f + 1)
  const unit = (r.photometry_unit ?? 'flux').split(' (')[0]
  const wl = pick === 'stack' || pick === 'each' ? null : r.detectors[pick].find((d) => d.wavelength_um)?.wavelength_um
  const change = pick === 'each' ? null : brightnessChange(good.map((p) => p.phot!))
  // A change that is largest in D1 or D2 is probably scattered light (issue #5): never call it real.
  // NM1: no claim about a change where no source shows (typed coordinates of a star that has moved away)
  const source = good.some((p) => sourceSeen(r.frames[p.frame], p.phot))
  const suspect = !!change && source && change.sigmas >= 3 && scatteredLight(r) && !/^D[3-6]$/.test(pick)
  const common = r.frames[0]?.stack_detectors
  const sameStack = !!common && r.frames.every((f) => f.stack_detectors?.join() === common.join())
  const L = 64
  const T = 12
  const W = 440
  const H = 180
  const x0 = Math.min(...r.frames.map((f) => f.mjd_mean)) - 15
  const x1 = Math.max(...r.frames.map((f) => f.mjd_mean)) + 15
  const lo = good.length ? Math.min(...good.map((p) => p.phot!.flux - p.phot!.err)) : 0
  const hi = good.length ? Math.max(...good.map((p) => p.phot!.flux + p.phot!.err)) : 1
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.15
  const y0 = lo - pad
  const y1 = hi + pad
  const X = (v: number) => L + ((v - x0) / (x1 - x0)) * W
  const Y = (v: number) => T + H - ((v - y0) / (y1 - y0)) * H
  const band = (d: string) => r.detectors[d].find((x) => x.wavelength_um)?.wavelength_um
  return (
    <>
      <label className="place-row">
        Series
        <select value={pick} onChange={(e) => setSeries(e.target.value)}>
          <option value="stack">{r.det ? `Stack (${r.det} only)` : sameStack ? `Stack (${common!.join(' ')})` : 'All detectors (stack)'}</option>
          {dets.length > 1 && <option value="each">Each detector (all points)</option>}
          {dets.map((d) => (
            <option key={d} value={d}>
              {d} only{band(d) ? ` (${um(band(d))} µm)` : ''}
            </option>
          ))}
        </select>
      </label>
      <svg className="chart" viewBox={`0 0 ${L + W + 12} ${T + H + 44}`} style={{ maxWidth: 640 }} role="img" aria-labelledby="phot-desc">
        <desc id="phot-desc">
          Brightness of the target per frame in {unit}, with 1σ error bars, against the date. Frames marked SAT are saturated and
          have no measurement.
        </desc>
        {ticks(y0, y1).map((v) => (
          <g key={`y${v}`}>
            <line className="grid-line" x1={L} x2={L + W} y1={Y(v)} y2={Y(v)} />
            <text x={L - 6} y={Y(v) + 4} textAnchor="end">
              {+v.toPrecision(4)}
            </text>
          </g>
        ))}
        {monthTicks(x0, x1, 5).map((m) => (
          <text key={m} x={X(m)} y={T + H + 14} textAnchor="middle">
            {dateOf(m).slice(0, 7)}
          </text>
        ))}
        <rect x={L} y={T} width={W} height={H} fill="none" className="grid-line" />
        <text className="axis-title" x={L + W / 2} y={T + H + 34} textAnchor="middle">
          Mean date of the frame
        </text>
        <text className="axis-title" transform={`translate(14 ${T + H / 2}) rotate(-90)`} textAnchor="middle">
          Flux ({unit})
        </text>
        {groups.map((g) => {
          const pts = g.filter((p) => p.phot)
          return pts.length > 1 && <polyline key={g[0]?.tag} className="series" points={pts.map((p) => `${X(p.x)},${Y(p.phot!.flux)}`).join(' ')} />
        })}
        {good.map((p) => (
          <g key={`${p.tag}${p.frame}`}>
            <line className="err" x1={X(p.x)} x2={X(p.x)} y1={Y(p.phot!.flux - p.phot!.err)} y2={Y(p.phot!.flux + p.phot!.err)} />
            <circle className="meas" cx={X(p.x)} cy={Y(p.phot!.flux)} r={4} />
            {p.frame === index && <circle className="current-ring" cx={X(p.x)} cy={Y(p.phot!.flux)} r={8} />}
            <text className="label-data" x={X(p.x) + 8} y={Y(p.phot!.flux) - 6}>
              {pick === 'each' ? p.tag : p.frame + 1}
            </text>
          </g>
        ))}
        {missing.map((f) => (
          <g key={`m${f}`}>
            <path className={r.frames[f].saturated ? 'sat' : 'sat hollow'} d={`M${X(r.frames[f].mjd_mean)} ${T + H - 4}l-5 -9h10z`} />
            <text className="label-data" x={X(r.frames[f].mjd_mean)} y={T + H - 18} textAnchor="middle">
              {f + 1}
            </text>
          </g>
        ))}
      </svg>
      <ul className="legend">
        <li>● measured flux ±1σ, labelled by {pick === 'each' ? 'detector' : 'survey'}</li>
        <li>▲ survey saturated — not measurable</li>
        <li>△ no data at the target</li>
      </ul>
      <p className="summary">
        {good.length && !source
          ? 'No source at this position — the brightness numbers are sky noise.'
          : pick === 'each'
          ? good.length
            ? `Measured: ${good.map((p) => `${p.tag} ${fmt(p.phot!)} ${unit} (survey ${p.frame + 1})`).join(' · ')}`
            : 'No detector is measurable here.'
          : change
            ? `Change: ${change.lo.flux > 0 ? `the brightest survey is ${(change.hi.flux / change.lo.flux).toFixed(1)}× the faintest` : `${+(change.hi.flux - change.lo.flux).toPrecision(3)} ${unit}`} (${+change.lo.flux.toPrecision(4)} to ${+change.hi.flux.toPrecision(4)} ${unit}, ${change.sigmas.toFixed(1)}σ)${suspect ? '' : change.sigmas >= 3 ? ' — larger than the noise' : ' — within the noise'}`
            : good.length === 1
              ? `Only survey ${good[0].frame + 1} is measurable (${fmt(good[0].phot!)} ${unit}).`
              : 'No survey is measurable in this series.'}
        {wl && ` · ${pick} ${um(wl)} µm`}
      </p>
      {suspect && (
        <p className="note-line">
          <AlertIcon /> May be scattered light (known issue #5): the change is largest in D1 or D2, where stray light from bright
          stars is strongest. It is not evidence of a real change.
        </p>
      )}
      {sat.length > 0 && (
        <p className="note-line">
          <AlertIcon /> Saturated in survey{sat.length > 1 ? 's' : ''} {spans(sat)}: too bright for SPHEREx to measure here.
        </p>
      )}
      {gap.length > 0 && (
        <p className="hint">
          No measurement in survey{gap.length > 1 ? 's' : ''} {spans(gap)}:{' '}
          {pick === 'stack' ? 'at least one detector has no data in the core.' : 'no data at the target.'}
        </p>
      )}
      <p className="hint mono">Measured surveys per series: {counts.map(([k, n]) => `${k} ${n}`).join(' · ')}</p>
      {deepLink && (sat.length > 0 || gap.length > 0) && (
        <p>
          <a href={deepLink}>See the matched-wavelength brightness check in WANDERERS →</a>
        </p>
      )}
      <p className="hint">
        Unit: {r.photometry_unit ?? '–'}.{' '}
        {sameStack && !r.det
          ? `The stack uses only ${common!.join(' ')}, the detectors that every survey has.`
          : 'A stack mixes detectors (wavelengths), so a fixed star can change a little between stacks; one detector is a fairer test.'}{' '}
        Each survey also sees the target at another wavelength inside a detector band, so an object with strong spectral bands
        can change here without being variable.
      </p>
    </>
  )
}
