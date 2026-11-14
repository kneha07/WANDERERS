// Screen state machine (one owner: the reducer below; the URL owns the place):
//
//   home (no q) ──search/chip──► loading ──► result | empty (404) | error (400/502/timeout/offline)
//   result ──search/chip──► loading (the old result stays, dimmed, until the new one lands)
//   result ──click pixel──► popover (the only layer) ──Esc/close/backdrop/Back──► result
//
// URL ?q=&fov=&view=&det= : a search is a new place (pushState); toggles replace it (replaceState);
// popstate re-reads the URL, so Back returns to the previous target or home in one press.
import { useEffect, useReducer, useRef, useState } from 'react'
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
type View = 'blink' | 'diff'
type Place = { q: string; fov: number; view: View; det: string } // everything the URL holds
type Failure = { kind: 'empty' | 'input' | 'busy' | 'timeout' | 'offline' | 'server'; message: string }
type State = Place & {
  status: 'home' | 'loading' | 'result' | 'empty' | 'error'
  result: Result | null // the last result; it stays on screen, dimmed, while the next one loads
  failure: Failure | null
  attempt: number // Retry bumps it, so the same place loads again
  since: number // when loading started (ms), for the elapsed-seconds counter
  pick: { ra: number; dec: number } | null // the pixel popover
}
type Action =
  | { type: 'place'; place: Place; cached: Result | null; at: number }
  | { type: 'loaded'; key: string; result: Result }
  | { type: 'failed'; key: string; failure: Failure }
  | { type: 'retry'; at: number }
  | { type: 'pick'; ra: number; dec: number }
  | { type: 'unpick' }

const TARGETS = [
  { q: "Barnard's Star", label: "Barnard's Star", note: 'fastest-moving star' },
  { q: 'eps Ind B', label: 'Epsilon Indi B', note: 'fast brown dwarf pair' },
  { q: 'WISE J085510.83-071442.5', label: 'WISE 0855', note: 'coldest brown dwarf' },
  { q: 'RW Aur', label: 'RW Aurigae', note: 'variable star' },
  { q: 'R Dra', label: 'R Draconis', note: 'variable star, many images' },
]
const TIMEOUT_MS = 180_000
const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches

const clampFov = (f: number) => Math.min(15, Math.max(2, Math.round(f) || 5))
const deg = (v: number, sign = false) => (sign && v >= 0 ? '+' : '') + v.toFixed(5) + '°'
const keyOf = (p: { q: string; fov: number }) => `${p.q}|${p.fov}`
const placeOf = (s: State): Place => ({ q: s.q, fov: s.fov, view: s.view, det: s.det })

function readUrl(): Place {
  const p = new URLSearchParams(location.search)
  const det = p.get('det') ?? ''
  return {
    q: (p.get('q') ?? '').trim(),
    fov: clampFov(Number(p.get('fov') ?? 5)),
    view: p.get('view') === 'diff' ? 'diff' : 'blink',
    det: /^D[1-6]$/.test(det) ? det : '',
  }
}

function urlOf(p: Place): string {
  if (!p.q) return location.pathname
  const s = new URLSearchParams({ q: p.q, fov: String(p.fov) })
  if (p.view === 'diff') s.set('view', 'diff')
  if (p.det) s.set('det', p.det)
  return `${location.pathname}?${s}`
}

function failureOf(status: number, detail: unknown): Failure {
  if (status === 404) return { kind: 'empty', message: 'No SPHEREx images cover this position yet.' }
  if (status === 400)
    return { kind: 'input', message: typeof detail === 'string' ? detail : 'The server could not read this target.' }
  if (status >= 502 && status <= 504) return { kind: 'busy', message: 'IRSA, the SPHEREx archive, is busy. Try again.' }
  return { kind: 'server', message: `The server failed (HTTP ${status}). Try again.` }
}

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'place': {
      const p = a.place
      if (!p.q) return { ...s, ...p, status: 'home', failure: null, pick: null }
      if (keyOf(p) === keyOf(s) && s.status !== 'home') return { ...s, ...p } // a toggle: same data
      if (a.cached) return { ...s, ...p, status: 'result', result: a.cached, failure: null, pick: null }
      return { ...s, ...p, status: 'loading', failure: null, pick: null, since: a.at }
    }
    case 'loaded':
      return a.key === keyOf(s) ? { ...s, status: 'result', result: a.result } : s
    case 'failed':
      return a.key === keyOf(s) ? { ...s, status: a.failure.kind === 'empty' ? 'empty' : 'error', failure: a.failure } : s
    case 'retry':
      return { ...s, status: 'loading', failure: null, attempt: s.attempt + 1, since: a.at }
    case 'pick':
      return { ...s, pick: { ra: a.ra, dec: a.dec } }
    case 'unpick':
      return { ...s, pick: null }
  }
}

function initState(): State {
  const p = readUrl()
  return { ...p, status: p.q ? 'loading' : 'home', result: null, failure: null, attempt: 0, since: Date.now(), pick: null }
}

function framesOf(r: Result | null, det: string): Frame[] {
  if (!r) return []
  const d = det ? r.detectors[det] : undefined
  return d ? d.map((x) => ({ ...r.frames[x.group_index], png: x.png, n_images: x.n_images })) : r.frames
}

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
  const [state, dispatch] = useReducer(reducer, null, initState)
  const [input, setInput] = useState(state.q)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(!REDUCED_MOTION)
  const [fps, setFps] = useState(2)
  const [showRing, setShowRing] = useState(true)
  const [showCross, setShowCross] = useState(false)
  const [preloaded, setPreloaded] = useState<Result | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [toast, setToast] = useState('')
  const cache = useRef(new Map<string, Result>()) // q+fov -> result: Back to a target is instant
  const stageRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const toastTimer = useRef(0)
  const key = keyOf(state)
  const r = state.result
  const loading = state.status === 'loading'

  // The one way to change place. A new search is a new place (push); a toggle only replaces it.
  const go = (patch: Partial<Place>, mode: 'push' | 'replace') => {
    const place = { ...placeOf(state), ...patch }
    const url = urlOf(place)
    if (url !== location.pathname + location.search) {
      if (mode === 'push') history.pushState({ app: 1 }, '', url)
      else history.replaceState({ app: 1 }, '', url)
    }
    dispatch({ type: 'place', place, cached: cache.current.get(keyOf(place)) ?? null, at: Date.now() })
  }

  const search = (text: string) => {
    const q = text.trim()
    if (!q) return
    if (keyOf({ q, fov: state.fov }) === key && (state.status === 'error' || state.status === 'empty'))
      dispatch({ type: 'retry', at: Date.now() })
    else go({ q, view: 'blink', det: '' }, 'push')
  }

  // First arrival from outside (shared link): put home under it, so Back stays in the app.
  useEffect(() => {
    if (history.state?.app && !history.state?.pick) return
    const here = location.pathname + location.search
    const deep = readUrl().q !== ''
    history.replaceState({ app: 1 }, '', location.pathname)
    if (deep) history.pushState({ app: 1 }, '', here)
  }, [])

  useEffect(() => {
    const onPop = () => {
      const place = readUrl()
      setInput(place.q)
      dispatch({ type: 'place', place, cached: cache.current.get(keyOf(place)) ?? null, at: Date.now() })
      if (!history.state?.pick) dispatch({ type: 'unpick' })
    }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  // One request per load. A newer place aborts it, so an old answer never shows.
  const need = loading ? `${key}#${state.attempt}` : ''
  useEffect(() => {
    if (!need) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort('timeout'), TIMEOUT_MS)
    const t0 = performance.now()
    const params = new URLSearchParams({ q: state.q, fov: String(state.fov) })
    ;(async () => {
      let action: Action
      try {
        const res = await fetch(`/api/frames?${params}`, { signal: ctrl.signal })
        const body = await res.json().catch(() => null)
        if (res.ok && body) {
          cache.current.set(key, body)
          action = { type: 'loaded', key, result: body }
        } else action = { type: 'failed', key, failure: failureOf(res.status, body?.detail) }
      } catch {
        if (ctrl.signal.reason !== 'timeout' && ctrl.signal.aborted) return // replaced by a newer place
        action = {
          type: 'failed',
          key,
          failure:
            ctrl.signal.reason === 'timeout'
              ? { kind: 'timeout', message: 'No answer after 3 minutes. IRSA may be slow. Try again.' }
              : { kind: 'offline', message: 'Could not reach the server. Check the connection and the backend, then try again.' },
        }
      }
      // The indicator appears at 300 ms; once shown, it stays at least 500 ms.
      const t = performance.now() - t0
      if (t > 300 && t < 800) await new Promise((done) => setTimeout(done, 800 - t))
      if (ctrl.signal.reason === 'timeout' || !ctrl.signal.aborted) dispatch(action)
    })()
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [need, key, state.q, state.fov])

  useEffect(() => {
    if (!loading) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [loading])
  const elapsed = Math.max(0, Math.round((now - state.since) / 1000))

  // Decode every frame before playing, so the blink never flickers.
  useEffect(() => {
    if (!r) return
    let live = true
    const srcs = [
      ...r.frames.map((f) => f.png),
      ...Object.values(r.detectors).flatMap((d) => d.map((x) => x.png)),
      ...(r.difference ? [r.difference.png] : []),
    ]
    const decode = (src: string) => {
      const im = new Image()
      im.src = src
      return im.decode().catch(() => undefined)
    }
    Promise.all(srcs.map(decode)).then(() => {
      if (!live) return
      setPreloaded(r)
      setIndex(0)
      setPlaying(!REDUCED_MOTION)
    })
    return () => {
      live = false
    }
  }, [r])

  const det = r && r.detectors[state.det] ? state.det : ''
  const frames = framesOf(r, det)
  const count = frames.length
  const frame = count ? frames[index % count] : null
  const canPlay = state.status === 'result' && preloaded === r && state.view === 'blink' && !state.pick && count > 1

  useEffect(() => {
    if (!canPlay || !playing) return
    const t = setInterval(() => setIndex((i) => (i + 1) % count), 1000 / fps)
    return () => clearInterval(t)
  }, [canPlay, playing, count, fps])

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) setPlaying(false)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  // Keyboard: space = play or pause, arrows = step. Text fields, sliders and the popover keep their keys.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (!count || state.pick || el.closest('input, textarea, select')) return
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
  }, [count, state.pick])

  // The popover is a native modal <dialog>: focus moves in, the page behind is inert.
  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (state.pick && !d.open) {
      d.showModal()
      closeRef.current?.focus()
    } else if (!state.pick && d.open) {
      d.close()
      stageRef.current?.focus()
    }
  }, [state.pick])

  // Esc, the close button, a backdrop click and browser Back all end here.
  const closePick = () => {
    if (history.state?.pick) history.back()
    else dispatch({ type: 'unpick' })
  }

  const onPick = (e: MouseEvent<HTMLDivElement>) => {
    if (!r || state.status !== 'result') return
    // North up, east left; small-field approximation around the center.
    const box = e.currentTarget.getBoundingClientRect()
    const n = r.size_px
    const scale = r.pixel_arcsec / 3600
    const dx = ((e.clientX - box.left) / box.width) * n - n / 2 // grid pixels right of center (west)
    const dy = ((e.clientY - box.top) / box.height) * n - n / 2 // grid pixels below center (south)
    const dec = r.center.dec - dy * scale
    const ra = (r.center.ra - (dx * scale) / Math.cos((r.center.dec * Math.PI) / 180) + 360) % 360
    history.pushState({ app: 1, pick: 1 }, '', location.href)
    dispatch({ type: 'pick', ra, dec })
  }

  const say = (text: string) => {
    clearTimeout(toastTimer.current)
    setToast(text)
    toastTimer.current = window.setTimeout(() => setToast(''), 3000)
  }
  const copyLink = () =>
    navigator.clipboard.writeText(location.href).then(
      () => say('Link copied'),
      () => say('Could not copy. Use the address bar.'),
    )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    search(input)
  }

  const busy = loading && input.trim() === state.q
  const n = r?.size_px ?? 1
  const showDiff = state.view === 'diff' && r?.difference
  const ring = showDiff ? r.frames[r.frames.length - 1].ring : frame?.ring

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
            placeholder="Barnard's Star, or 269.45 4.69"
            autoComplete="off"
          />
          <button id="search-btn" type="submit" disabled={busy || !input.trim()} aria-busy={busy}>
            {busy ? 'Searching…' : 'Show'}
          </button>
        </div>
      </form>

      {state.status === 'home' && (
        <p id="home-hint" className="hint">
          Type a star name or a sky position, or pick a test target.
        </p>
      )}
      {state.status === 'empty' && (
        <div id="empty-state" className="panel">
          <p>No SPHEREx images cover this position yet. Try one of the test targets below.</p>
        </div>
      )}
      {state.status === 'error' && state.failure && (
        <div className="panel error" role="alert">
          <p>{state.failure.message}</p>
          {state.failure.kind === 'input' && (
            <p className="hint">Examples: Barnard's Star · 269.45 4.69 · 17h57m48.5s +04d41m36s</p>
          )}
          <button type="button" onClick={() => dispatch({ type: 'retry', at: Date.now() })}>
            Retry
          </button>
        </div>
      )}

      <ul className="chips" aria-label="Test targets">
        {TARGETS.map((t) => (
          <li key={t.q}>
            <button
              type="button"
              className="chip"
              data-target={t.q}
              onClick={() => {
                setInput(t.q)
                search(t.q)
              }}
            >
              <strong>{t.label}</strong>
              <span>{t.note}</span>
            </button>
          </li>
        ))}
      </ul>

      {(loading || state.status === 'result') && (
        <section className="viewer" data-status={state.status} aria-busy={loading} aria-label="Blink viewer">
          <p className="target">
            {loading || !r ? (
              <>Loading {state.q}…</>
            ) : (
              <>
                <strong>{r.name ?? r.query}</strong> · RA {deg(r.center.ra)} Dec {deg(r.center.dec, true)}
                {r.pm && ' · 2026.0 position'} · {r.fov_arcmin}′ field
              </>
            )}
          </p>

          <div className="views" role="group" aria-label="View">
            <button type="button" aria-pressed={state.view === 'blink'} disabled={!r} onClick={() => go({ view: 'blink' }, 'replace')}>
              Blink
            </button>
            <button type="button" aria-pressed={state.view === 'diff'} disabled={!r} onClick={() => go({ view: 'diff' }, 'replace')}>
              Difference
            </button>
          </div>

          <div className="stage" ref={stageRef} tabIndex={-1} onClick={onPick}>
            {r && frame && (
              <img
                src={showDiff ? r.difference!.png : frame.png}
                alt={
                  showDiff
                    ? `Difference image, ${r.difference!.to} minus ${r.difference!.from}`
                    : `SPHEREx ${frame.label}, ${frame.date}, ${frame.n_images} images stacked`
                }
              />
            )}
            {r && (
              <svg viewBox={`0 0 ${n} ${n}`} aria-hidden="true">
                {showRing && ring && <circle cx={ring.x} cy={ring.y} r={2.5} className="ring" />}
                {showCross && <path className="cross" d={`M${n / 2 - 3} ${n / 2}h2m2 0h2M${n / 2} ${n / 2 - 3}v2m0 2v2`} />}
              </svg>
            )}
            {loading && (
              <p className="indicator" role="status">
                <span>
                  Fetching SPHEREx images from IRSA. The first load of a target takes up to a minute; later loads are
                  instant. <span aria-hidden="true">{elapsed} s</span>
                </span>
              </p>
            )}
          </div>

          <p className="frame-label" aria-live={playing ? 'off' : 'polite'}>
            {!loading && frame && !showDiff
              ? `${frame.label} · ${frame.date} · ${frame.n_images} images · frame ${(index % count) + 1} of ${count}`
              : !loading && showDiff
                ? `${r.difference!.to} minus ${r.difference!.from}`
                : ' '}
          </p>

          {state.view === 'diff' && r && !loading ? (
            <p className="diff-note">
              {r.difference
                ? 'A mover shows as a dark and bright pair: dark where it was, bright where it is now. A blinker shows as a dark or bright spot.'
                : 'A difference needs at least two surveys. This position has only one so far.'}
            </p>
          ) : (
            <div className="controls">
              <button type="button" onClick={() => setPlaying((p) => !p)} disabled={!canPlay}>
                {playing && canPlay ? 'Pause' : 'Play'}
              </button>
              <button type="button" onClick={() => setIndex((index + count - 1) % count)} disabled={!canPlay} aria-label="Previous frame">
                ◀
              </button>
              <button type="button" onClick={() => setIndex((index + 1) % count)} disabled={!canPlay} aria-label="Next frame">
                ▶
              </button>
              <label className="speed">
                Speed {fps}/s
                <input type="range" min={1} max={10} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
              </label>
            </div>
          )}

          <div className="toggles">
            <label>
              <input type="checkbox" checked={showRing} onChange={(e) => setShowRing(e.target.checked)} disabled={!r?.pm} />
              Show where to look{r && !r.pm && ' (needs a known proper motion: search by name)'}
            </label>
            <label>
              <input type="checkbox" checked={showCross} onChange={(e) => setShowCross(e.target.checked)} />
              Crosshair at center
            </label>
          </div>
          <p className="hint">
            Click a pixel to look it up in other catalogs. Black means no data (off the detector, or a saturated star
            core). Keys: Space plays or pauses, ← and → step.
          </p>

          <div className="share">
            <button type="button" onClick={copyLink} disabled={!r}>
              Copy share link
            </button>
            <span className="toast" role="status">
              {toast}
            </span>
          </div>

          {r && (
            <details className="expert">
              <summary>Expert</summary>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  go({ fov: clampFov(Number(new FormData(e.currentTarget).get('fov'))) }, 'replace')
                }}
              >
                <label>
                  Field of view (arcmin, 2 to 15)
                  <input key={state.fov} name="fov" type="number" min={2} max={15} step={1} defaultValue={state.fov} />
                </label>
                <button type="submit">Apply</button>
              </form>
              <label>
                Detector
                <select
                  value={det}
                  onChange={(e) => {
                    setIndex(0)
                    go({ det: e.target.value }, 'replace')
                  }}
                >
                  <option value="">All detectors, stacked</option>
                  {Object.keys(r.detectors).map((d) => (
                    <option key={d} value={d}>
                      {d} only ({r.detectors[d].length} surveys)
                    </option>
                  ))}
                </select>
              </label>
              <p>
                Images used: {r.n_images_used} · failed: {r.n_failed} · pixel {r.pixel_arcsec}″ · {r.size_px}×
                {r.size_px} px · {r.cached ? 'from the server cache' : 'freshly built'}
                {r.pm && ` · proper motion ${r.pm.pmra.toFixed(1)}, ${r.pm.pmdec.toFixed(1)} mas/yr`}
              </p>
            </details>
          )}
        </section>
      )}

      <dialog
        ref={dialogRef}
        className="popover"
        aria-labelledby="pick-title"
        onCancel={(e) => {
          e.preventDefault()
          closePick()
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) closePick() // a click on the backdrop
        }}
      >
        {state.pick && (
          <div className="popover-body">
            <h2 id="pick-title">
              RA {deg(state.pick.ra)} Dec {deg(state.pick.dec, true)}
            </h2>
            <p className="hint">Look up this pixel (opens a new tab):</p>
            <ul>
              {lookupLinks(state.pick.ra, state.pick.dec).map(([label, href]) => (
                <li key={label}>
                  <a href={href} target="_blank" rel="noreferrer">
                    {label}
                  </a>
                </li>
              ))}
            </ul>
            <button type="button" ref={closeRef} onClick={closePick}>
              Close
            </button>
          </div>
        )}
      </dialog>

      <footer>
        Data: NASA SPHEREx (IRSA, DR1 and QR3), names via CDS Sesame. NASA Space Apps 2026, Planet X and SPHEREx.
      </footer>
    </main>
  )
}
