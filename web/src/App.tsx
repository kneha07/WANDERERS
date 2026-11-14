import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'

type Ring = { x: number; y: number }
type Frame = { label: string; mjd_mean: number; date: string; n_images: number; png: string; ring: Ring | null }
type DetectorFrame = { group_index: number; png: string; n_images: number }
type Result = {
  query: string
  name: string | null
  center: { ra: number; dec: number }
  pm: { pmra: number; pmdec: number } | null
  fov_arcmin: number
  pixel_arcsec: number
  size_px: number
  frames: Frame[]
  detectors: Record<string, DetectorFrame[]>
  difference: { png: string; from: string; to: string } | null
  n_images_used: number
  n_failed: number
  cached: boolean
}

const TARGETS = [
  { q: "Barnard's Star", label: "Barnard's Star", note: 'fastest-moving star' },
  { q: 'eps Ind B', label: 'Epsilon Indi B', note: 'fast brown dwarf pair' },
  { q: 'WISE J085510.83-071442.5', label: 'WISE 0855', note: 'coldest brown dwarf' },
  { q: 'RW Aur', label: 'RW Aurigae', note: 'variable star' },
  { q: 'R Dra', label: 'R Draconis', note: 'variable star, many images' },
]
const PLAYER_PX = 480 // display width; an integer scale keeps the pixels square and sharp

const clampFov = (f: number) => Math.min(15, Math.max(2, Math.round(f) || 5))
const deg = (v: number, sign = false) => (sign && v >= 0 ? '+' : '') + v.toFixed(5) + '°'

function lookupLinks(ra: number, dec: number): [string, string][] {
  const r = ra.toFixed(5)
  const d = dec.toFixed(5)
  const coord = encodeURIComponent(`${r} ${d}`)
  return [
    ['SIMBAD', `https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=${coord}&Radius=10&Radius.unit=arcsec`],
    ['Gaia DR3 (VizieR)', `https://vizier.cds.unistra.fr/viz-bin/VizieR-4?-source=I/355/gaiadr3&-c=${coord}&-c.rs=10`],
    ['WiseView', `http://byw.tools/wiseview#ra=${r}&dec=${d}&size=176&band=3&speed=164&minbright=-50.0000&maxbright=500.0000&window=0.5&diff_window=1&linear=1&color=&zoom=9&border=0&gaia=1&invert=1&maxdyr=0&scandir=0&neowise=0&diff=0&outer_epochs=0&unique_window=1&smooth_scan=0&shift=0&pmra=0&pmdec=0`],
    ['Backyard Worlds', 'https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9/talk'],
  ]
}

export default function App() {
  const [input, setInput] = useState('')
  const [fov, setFov] = useState(5)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [fps, setFps] = useState(2)
  const [showRing, setShowRing] = useState(true)
  const [showCross, setShowCross] = useState(false)
  const [view, setView] = useState<'blink' | 'difference'>('blink')
  const [detector, setDetector] = useState('') // '' = all detectors stacked
  const [picked, setPicked] = useState<{ ra: number; dec: number } | null>(null)
  const [copied, setCopied] = useState(false)
  const requestId = useRef(0)

  const search = useCallback(async (q: string, f: number, push = true) => {
    q = q.trim()
    if (!q) return
    const params = new URLSearchParams({ q, fov: String(f) })
    if (push) history.pushState(null, '', `?${params}`)
    const id = ++requestId.current // a newer search wins; older answers are dropped
    setLoading(true)
    setElapsed(0)
    setError('')
    setResult(null)
    setPicked(null)
    setIndex(0)
    setDetector('')
    setView('blink')
    try {
      const res = await fetch(`/api/frames?${params}`)
      const body = await res.json().catch(() => ({ detail: `The server failed (HTTP ${res.status}).` }))
      if (id !== requestId.current) return
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      setResult(body)
      setPlaying(true)
    } catch (e) {
      if (id !== requestId.current) return
      setError(e instanceof TypeError ? 'Could not reach the server. Is the backend running?' : String((e as Error).message))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [])

  // URL state: ?q=...&fov=... runs the search on load and on back/forward.
  useEffect(() => {
    const fromUrl = () => {
      const p = new URLSearchParams(location.search)
      const q = p.get('q') ?? ''
      const f = clampFov(Number(p.get('fov') ?? 5))
      setInput(q)
      setFov(f)
      if (q) search(q, f, false)
    }
    fromUrl()
    addEventListener('popstate', fromUrl)
    return () => removeEventListener('popstate', fromUrl)
  }, [search])

  useEffect(() => {
    if (!loading) return
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [loading])

  const frames: Frame[] = !result
    ? []
    : detector
      ? result.detectors[detector].map((d) => ({ ...result.frames[d.group_index], png: d.png, n_images: d.n_images }))
      : result.frames
  const count = frames.length
  const frame = count ? frames[index % count] : null

  useEffect(() => {
    if (!playing || count < 2 || view !== 'blink') return
    const t = setInterval(() => setIndex((i) => (i + 1) % count), 1000 / fps)
    return () => clearInterval(t)
  }, [playing, count, fps, view])

  // Keyboard: space = play/pause, arrows = step. Text fields and sliders keep their own keys.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (!count || el.closest('input, textarea, select')) return
      if (e.key === ' ') {
        if (el.closest('button, a, summary')) return // the browser activates the focused control
        e.preventDefault()
        setPlaying((p) => !p)
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault()
        setPlaying(false)
        setIndex((i) => (i + (e.key === 'ArrowRight' ? 1 : count - 1)) % count)
      }
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [count])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    search(input, fov)
  }

  const onPick = (e: MouseEvent<HTMLDivElement>) => {
    if (!result) return
    // North up, east left; small-field approximation around the center.
    const box = e.currentTarget.getBoundingClientRect()
    const n = result.size_px
    const scale = result.pixel_arcsec / 3600
    const dx = ((e.clientX - box.left) / box.width) * n - n / 2 // grid pixels right of center (west)
    const dy = ((e.clientY - box.top) / box.height) * n - n / 2 // grid pixels below center (south)
    const dec = result.center.dec - dy * scale
    const ra = (result.center.ra - (dx * scale) / Math.cos((result.center.dec * Math.PI) / 180) + 360) % 360
    setPicked({ ra, dec })
  }

  const copyLink = async () => {
    await navigator.clipboard.writeText(location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const n = result?.size_px ?? 1
  const px = n * Math.max(1, Math.floor(PLAYER_PX / n))
  const showDiff = view === 'difference' && result?.difference
  const ring = showDiff ? result.frames[result.frames.length - 1].ring : frame?.ring

  return (
    <main>
      <header>
        <h1>SPHEREx Blink</h1>
        <p className="lead">
          Watch one patch of sky change over SPHEREx's surveys. A <strong>mover</strong> is an object whose position
          changes between surveys (a nearby star or brown dwarf). A <strong>blinker</strong> changes in brightness (a
          variable star).
        </p>
      </header>

      <form className="search" onSubmit={onSubmit} role="search">
        <label htmlFor="q">Target name or RA/Dec</label>
        <div className="row">
          <input
            id="q"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Barnard's Star, or 269.45 4.69, or 17h57m48.5s +04d41m36s"
            autoComplete="off"
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Show
          </button>
        </div>
      </form>

      <ul className="chips" aria-label="Test targets">
        {TARGETS.map((t) => (
          <li key={t.q}>
            <button
              type="button"
              className="chip"
              onClick={() => {
                setInput(t.q)
                search(t.q, fov)
              }}
            >
              <strong>{t.label}</strong>
              <span>{t.note}</span>
            </button>
          </li>
        ))}
      </ul>

      {loading && (
        <p className="status" role="status">
          Fetching dozens of SPHEREx images from the archive ({elapsed} s). The first load of a target can take up to a
          minute. After that it is cached.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && frame && (
        <section className="viewer" aria-label="Blink viewer">
          <p className="target">
            <strong>{result.name ?? result.query}</strong> · RA {deg(result.center.ra)} Dec {deg(result.center.dec, true)}
            {result.pm && ' · centered on its 2026.0 position'} · {result.fov_arcmin}′ field
          </p>

          <div className="views" role="group" aria-label="View">
            <button type="button" aria-pressed={view === 'blink'} onClick={() => setView('blink')}>
              Blink
            </button>
            <button type="button" aria-pressed={view === 'difference'} onClick={() => setView('difference')}>
              Difference
            </button>
          </div>

          <div className="stage" style={{ width: px }} onClick={onPick}>
            <img
              src={showDiff ? result.difference!.png : frame.png}
              alt={
                showDiff
                  ? `Difference image, ${result.difference!.to} minus ${result.difference!.from}`
                  : `SPHEREx ${frame.label}, ${frame.date}, ${frame.n_images} images stacked`
              }
              width={px}
              height={px}
            />
            <svg viewBox={`0 0 ${n} ${n}`} aria-hidden="true">
              {showRing && ring && <circle cx={ring.x} cy={ring.y} r={2.5} className="ring" />}
              {showCross && (
                <path
                  className="cross"
                  d={`M${n / 2 - 3} ${n / 2}h2m2 0h2M${n / 2} ${n / 2 - 3}v2m0 2v2`}
                />
              )}
            </svg>
          </div>
          <p className="hint">Click a pixel to look it up in other catalogs. Black means no data (off the detector, or a saturated star core).</p>

          {view === 'blink' ? (
            <div className="controls">
              <button type="button" onClick={() => setPlaying((p) => !p)} disabled={count < 2}>
                {playing ? 'Pause' : 'Play'}
              </button>
              <button type="button" onClick={() => setIndex((index - 1 + count) % count)} aria-label="Previous frame">
                ◀
              </button>
              <button type="button" onClick={() => setIndex((index + 1) % count)} aria-label="Next frame">
                ▶
              </button>
              <span className="frame-label" aria-live="polite">
                {frame.label} · {frame.date} · {frame.n_images} images · frame {(index % count) + 1} of {count}
              </span>
              <label className="speed">
                Speed {fps} frames/s
                <input type="range" min={1} max={10} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
              </label>
              <span className="keys">Space: play or pause · ←/→: step</span>
            </div>
          ) : result.difference ? (
            <p className="diff-note">
              {result.difference.to} minus {result.difference.from}. A mover shows as a dark and bright pair: dark where
              it was, bright where it is now. A blinker shows as a dark or bright spot.
            </p>
          ) : (
            <p className="diff-note">A difference needs at least two surveys. This position has only one so far.</p>
          )}

          <div className="toggles">
            <label>
              <input type="checkbox" checked={showRing} onChange={(e) => setShowRing(e.target.checked)} disabled={!result.pm} />
              Show where to look{!result.pm && ' (needs a known proper motion: search by name)'}
            </label>
            <label>
              <input type="checkbox" checked={showCross} onChange={(e) => setShowCross(e.target.checked)} />
              Crosshair at center
            </label>
          </div>

          {picked && (
            <div className="picked">
              <p>
                Pixel at RA {deg(picked.ra)} Dec {deg(picked.dec, true)}
              </p>
              <ul>
                {lookupLinks(picked.ra, picked.dec).map(([label, href]) => (
                  <li key={label}>
                    <a href={href} target="_blank" rel="noreferrer">
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p>
            <button type="button" onClick={copyLink}>
              {copied ? 'Copied' : 'Copy share link'}
            </button>
          </p>

          <details className="expert">
            <summary>Expert</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                search(result.query, fov)
              }}
            >
              <label>
                Field of view (arcmin, 2 to 15)
                <input type="number" min={2} max={15} step={1} value={fov} onChange={(e) => setFov(clampFov(Number(e.target.value)))} />
              </label>
              <button type="submit">Apply</button>
            </form>
            <label>
              Detector
              <select value={detector} onChange={(e) => (setDetector(e.target.value), setIndex(0))}>
                <option value="">All detectors, stacked</option>
                {Object.keys(result.detectors).map((d) => (
                  <option key={d} value={d}>
                    {d} only ({result.detectors[d].length} surveys)
                  </option>
                ))}
              </select>
            </label>
            <p>
              Images used: {result.n_images_used} · failed: {result.n_failed} · pixel {result.pixel_arcsec}″ ·{' '}
              {result.size_px}×{result.size_px} px · {result.cached ? 'from cache' : 'freshly built'}
              {result.pm && ` · proper motion ${result.pm.pmra.toFixed(1)}, ${result.pm.pmdec.toFixed(1)} mas/yr`}
            </p>
          </details>
        </section>
      )}

      <footer>
        Data: NASA SPHEREx (IRSA, DR1 and QR3), names via CDS Sesame. NASA Space Apps 2026, Planet X and SPHEREx.
      </footer>
    </main>
  )
}
