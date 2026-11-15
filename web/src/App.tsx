// Screen state machine (one owner: the reducer below; the URL owns the place):
//
//   home (no q) ──search/chip──► loading ──► result | empty (404) | error (400/502/timeout/offline)
//   result ──search/chip──► loading (the old result stays, dimmed, until the new one lands)
//   any ──"?" or first visit──► tutorial (the only layer) ──Esc/close/backdrop/Back──► where it was
//
// URL ?q=&fov=&view=&det=&look=&c= : a search is a new place (pushState); toggles and new candidates replace it
// (replaceState); popstate re-reads the URL, so Back returns to the previous target or home in one press.
import { useEffect, useReducer, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from 'react'
import { marksFromParam, marksToParam } from './data'
import type { Result } from './data'
import { AlertIcon, Boundary, BrightnessPanel, FramesTable, MotionPanel, Panel, QualityPanel, Skeleton, TargetCard } from './panels'
import { COLOUR_LINE, EXAMPLES, FieldGuide, TaskTab, Thumbs, Tutorial, reportText } from './rail'
import SkyContext from './SkyContext'
import SkyNow, { CITIES } from './SkyNow'
import type { Here } from './SkyNow'
import { decText, pixelToSky, raText } from './sky'
import type { RaDec } from './sky'
import { LOOKS, needsRgb, Stage, Timeline } from './viewer'
import type { Look } from './viewer'

type View = 'blink' | 'diff'
type Place = { q: string; fov: number; view: View; det: string; look: Look; marks: RaDec[] } // everything the URL holds
type Failure = { kind: 'empty' | 'input' | 'busy' | 'timeout' | 'offline' | 'server'; message: string }
type Layer = 'tutorial' | null
type State = Place & {
  status: 'home' | 'loading' | 'result' | 'empty' | 'error'
  result: Result | null // the last result; it stays on screen, dimmed, while the next one loads
  failure: Failure | null
  attempt: number // Retry bumps it, so the same place loads again
  since: number // when loading started (ms), for the elapsed-seconds counter
  layer: Layer
}
type Action =
  | { type: 'place'; place: Place; cached: Result | null; at: number }
  | { type: 'loaded'; key: string; result: Result }
  | { type: 'failed'; key: string; failure: Failure }
  | { type: 'retry'; at: number }
  | { type: 'layer'; layer: Layer }

// det: the WISE 0855 brown dwarf is bright only near 4.5 um, so its chip opens the D6 stack.
// id: the WANDERERS mission id (app/data/index.json), for the deep-dive link.
const TARGETS = [
  { id: 'barnard', q: "Barnard's Star", det: '', label: "Barnard's Star", note: 'fastest-moving star' },
  { id: 'eps_indi_b', q: 'eps Ind B', det: '', label: 'Epsilon Indi B', note: 'fast brown dwarf pair' },
  { id: 'wise0855', q: 'WISE J085510.83-071442.5', det: 'D6', label: 'WISE 0855', note: 'uses its 2026 position; the challenge coordinates are from 2010' },
  { id: 'rw_aur', q: 'RW Aur', det: '', label: 'RW Aurigae', note: 'young variable star' },
  { id: 'r_dra', q: 'R Dra', det: '', label: 'R Draconis', note: 'pulsating giant, many images' },
]
const DETECTORS = [
  ['', 'All detectors, stacked'],
  ['D1', 'D1 only (0.75–1.09 µm)'],
  ['D2', 'D2 only (1.10–1.62 µm)'],
  ['D3', 'D3 only (1.63–2.41 µm)'],
  ['D4', 'D4 only (2.42–3.82 µm)'],
  ['D5', 'D5 only (3.83–4.41 µm)'],
  ['D6', 'Long-wavelength stack (D6 only, 4.42–5.00 µm): best for cold brown dwarfs like WISE 0855'],
]
const TABS = [
  ['task', 'Task'],
  ['data', 'Data'],
  ['guide', 'Field guide'],
] as const
type Tab = (typeof TABS)[number][0]
const TIMEOUT_MS = 180_000
const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches
const TUTORIAL_KEY = 'wanderers-explore-tutorial-seen'
const MAX_MARKS = 20

const clampFov = (f: number) => Math.min(15, Math.max(2, Math.round(f) || 5))
const keyOf = (p: { q: string; fov: number; det: string }) => `${p.q}|${p.fov}|${p.det}`
const placeOf = (s: State): Place => ({ q: s.q, fov: s.fov, view: s.view, det: s.det, look: s.look, marks: s.marks })
const short = (v: number) => (v < 1 ? v.toFixed(2) : v.toPrecision(2))

function readUrl(): Place {
  const p = new URLSearchParams(location.search)
  const det = p.get('det') ?? ''
  const look = LOOKS.find(([k]) => k === p.get('look'))?.[0] ?? 'raw'
  return {
    q: (p.get('q') ?? '').trim(),
    fov: clampFov(Number(p.get('fov') ?? 5)),
    view: p.get('view') === 'diff' ? 'diff' : 'blink',
    det: /^D[1-6]$/.test(det) ? det : '',
    look,
    marks: marksFromParam(p.get('c')),
  }
}

function urlOf(p: Place): string {
  const s = new URLSearchParams()
  if (p.q) {
    s.set('q', p.q)
    s.set('fov', String(p.fov))
    if (p.view === 'diff') s.set('view', 'diff')
    if (p.det) s.set('det', p.det)
  }
  if (p.look !== 'raw') s.set('look', p.look) // the look persists across targets
  if (p.q && p.marks.length) s.set('c', marksToParam(p.marks))
  const qs = s.toString()
  return location.pathname + (qs ? `?${qs}` : '')
}

function failureOf(status: number, detail: unknown): Failure {
  if (status === 404) return { kind: 'empty', message: 'No SPHEREx images cover this position yet.' }
  if (status === 400)
    return { kind: 'input', message: typeof detail === 'string' ? detail : 'The server could not read this target.' }
  if (status >= 502 && status <= 504) {
    if (typeof detail === 'string' && detail.startsWith('The live SPHEREx server')) return { kind: 'offline', message: detail }
    return { kind: 'busy', message: 'IRSA, the SPHEREx archive, is busy. Try again.' }
  }
  return { kind: 'server', message: `The server failed (HTTP ${status}). Try again.` }
}

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'place': {
      const p = a.place
      if (!p.q) return { ...s, ...p, status: 'home', failure: null }
      if (keyOf(p) === keyOf(s) && s.status !== 'home') return { ...s, ...p } // a toggle: same data
      if (a.cached) return { ...s, ...p, status: 'result', result: a.cached, failure: null }
      return { ...s, ...p, status: 'loading', failure: null, since: a.at }
    }
    case 'loaded':
      return a.key === keyOf(s) ? { ...s, status: 'result', result: a.result } : s
    case 'failed':
      return a.key === keyOf(s) ? { ...s, status: a.failure.kind === 'empty' ? 'empty' : 'error', failure: a.failure } : s
    case 'retry':
      return { ...s, status: 'loading', failure: null, attempt: s.attempt + 1, since: a.at }
    case 'layer':
      return { ...s, layer: a.layer }
  }
}

function initState(): State {
  const p = readUrl()
  return { ...p, status: p.q ? 'loading' : 'home', result: null, failure: null, attempt: 0, since: Date.now(), layer: null }
}

/** True once: the first visit in this browser. Storage can be blocked; then the tutorial waits for the "?" button. */
function firstVisit() {
  try {
    if (localStorage.getItem(TUTORIAL_KEY)) return false
    localStorage.setItem(TUTORIAL_KEY, '1')
    return true
  } catch {
    return false
  }
}

const PlayIcon = ({ playing }: { playing: boolean }) => (
  <svg className="icon" viewBox="0 0 20 20" aria-hidden="true">
    {playing ? <path d="M6 4h3v12H6zM11 4h3v12h-3z" fill="currentColor" /> : <path d="M6 4l10 6-10 6z" fill="currentColor" />}
  </svg>
)
const StepIcon = ({ dir }: { dir: 1 | -1 }) => (
  <svg className="icon" viewBox="0 0 20 20" aria-hidden="true" style={dir < 0 ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M5 4l8 6-8 6zM14 4h2v12h-2z" fill="currentColor" />
  </svg>
)

export default function App() {
  const [state, dispatch] = useReducer(reducer, null, initState)
  const [input, setInput] = useState(state.q)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(!REDUCED_MOTION)
  const [fps, setFps] = useState(2)
  const [showRing, setShowRing] = useState(true)
  const [showGaia, setShowGaia] = useState(true)
  const [showCross, setShowCross] = useState(false)
  const [bri, setBri] = useState(1)
  const [con, setCon] = useState(1)
  const [tab, setTab] = useState<Tab>('task')
  const [here, setHere] = useState<Here>(CITIES[0]) // memory only, never stored or sent
  const [preloaded, setPreloaded] = useState<Result | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [toast, setToast] = useState('')
  const cache = useRef(new Map<string, Result>()) // q+fov+det -> result: Back to a target is instant
  const dialogRef = useRef<HTMLDialogElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)
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

  const search = (text: string, det = '') => {
    const q = text.trim()
    if (!q) return
    if (keyOf({ q, fov: state.fov, det }) === key && (state.status === 'error' || state.status === 'empty'))
      dispatch({ type: 'retry', at: Date.now() })
    else go({ q, view: 'blink', det, marks: [] }, 'push')
  }

  const openTutorial = () => {
    returnFocus.current = document.activeElement as HTMLElement | null
    history.pushState({ app: 1, layer: 'tutorial' }, '', location.href)
    dispatch({ type: 'layer', layer: 'tutorial' })
  }
  // Esc, the close buttons, a backdrop click and browser Back all end here.
  const closeLayer = () => {
    if (history.state?.layer) history.back()
    else dispatch({ type: 'layer', layer: null })
  }

  // First arrival from outside (shared link): put home under it, so Back stays in the app. Then the first-run tutorial.
  useEffect(() => {
    if (!history.state?.app || history.state?.layer) {
      const deepUrl = location.pathname + location.search
      const place = readUrl()
      history.replaceState({ app: 1 }, '', urlOf({ ...place, q: '' }))
      if (place.q) history.pushState({ app: 1 }, '', deepUrl)
    }
    if (firstVisit()) openTutorial()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onPop = () => {
      const place = readUrl()
      setInput(place.q)
      dispatch({ type: 'place', place, cached: cache.current.get(keyOf(place)) ?? null, at: Date.now() })
      if (!history.state?.layer) dispatch({ type: 'layer', layer: null })
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
    if (state.det) params.set('det', state.det)
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
  }, [need, key, state.q, state.fov, state.det])

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
      ...r.frames.flatMap((f) => (f.rgb_png ? [f.png, f.rgb_png] : [f.png])),
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

  const frames = r?.frames ?? []
  const count = frames.length
  const at = count ? index % count : 0
  const frame = count ? frames[at] : null
  const canPlay = state.status === 'result' && preloaded === r && state.view === 'blink' && !state.layer && count > 1

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

  // Keyboard: space = play or pause, arrows = step. Text fields, menus, tabs and the layer keep their keys.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (!count || state.layer || el.closest('input, textarea, select, [role=tablist], dialog')) return
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
  }, [count, state.layer])

  // The layer is a native modal <dialog>: focus moves in, the page behind is inert; focus returns on close.
  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (state.layer && !d.open) {
      d.showModal()
      d.querySelector<HTMLElement>('[data-autofocus]')?.focus()
    } else if (!state.layer && d.open) {
      d.close()
      const back = returnFocus.current
      ;(back?.isConnected && back !== document.body ? back : searchRef.current)?.focus()
    }
  }, [state.layer])

  const say = (text: string) => {
    clearTimeout(toastTimer.current)
    setToast(text)
    toastTimer.current = window.setTimeout(() => setToast(''), 4000)
  }
  const copy = (text: string, done: string) =>
    navigator.clipboard.writeText(text).then(
      () => say(done),
      () => say('Could not copy. Use the address bar.'),
    )

  const pickFrame = (i: number) => {
    setPlaying(false)
    setIndex(i)
  }

  const mark = (x: number, y: number) => {
    if (!r || state.status !== 'result') return
    if (state.marks.length >= MAX_MARKS) return say(`At most ${MAX_MARKS} candidates. Remove one first.`)
    const p = pixelToSky(r, x, y)
    go({ marks: [...state.marks, { ra: +p.ra.toFixed(5), dec: +p.dec.toFixed(5) }] }, 'replace')
    setTab('task')
    say(`Candidate ${state.marks.length + 1} marked at ${raText(p.ra)} ${decText(p.dec)}. See the Task tab.`)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    search(input)
  }

  const tabKeys = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const i = TABS.findIndex(([id]) => id === tab)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key]
    if (next === undefined) return
    e.preventDefault()
    const t = TABS[(next + TABS.length) % TABS.length][0]
    setTab(t)
    document.getElementById(`tab-${t}`)?.focus()
  }

  const busy = loading && input.trim() === state.q
  const showDiff = state.view === 'diff' && !!r?.difference
  const rgbOk = !!r?.frames.some((f) => f.rgb_png)
  const wl = r?.rgb?.wavelength_um
  const satN = r?.frames.filter((f) => f.saturated).length ?? 0
  const current = TARGETS.find((t) => t.q.toLowerCase() === state.q.toLowerCase())

  return (
    <>
      <header className="topbar">
        <p className="brand">
          WANDERERS <span>· Explore</span>
        </p>
        <form className="search" onSubmit={onSubmit} role="search">
          <label htmlFor="q" className="sr-only">
            Target name or RA/Dec
          </label>
          <input
            id="q"
            ref={searchRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Barnard's Star, or 269.45 4.69"
            autoComplete="off"
          />
          <button id="search-btn" className="primary" type="submit" disabled={busy || !input.trim()} aria-busy={busy}>
            {busy ? 'Searching…' : 'Show'}
          </button>
        </form>
        <nav className="topbar-links" aria-label="Site">
          <button type="button" id="help-btn" onClick={openTutorial} aria-label="How to look: open the tutorial">
            ?
          </button>
          <a href="/">← Missions</a>
        </nav>
      </header>

      <main className="page">
        <div className="status-row">
          {state.status === 'empty' && (
            <div id="empty-state" className="state">
              <p>No SPHEREx images cover this position yet. Try one of the test targets below.</p>
            </div>
          )}
          {state.status === 'error' && state.failure && (
            <div className="state error" role="alert">
              <AlertIcon />
              <p>
                {state.failure.message}
                {state.failure.kind === 'input' && (
                  <span className="hint" style={{ display: 'block' }}>
                    Examples: Barnard's Star · 269.45 4.69 · 17h57m48.5s +04d41m36s
                  </span>
                )}
              </p>
              <button type="button" onClick={() => dispatch({ type: 'retry', at: Date.now() })}>
                Retry
              </button>
            </div>
          )}
        </div>

        <ul className="chips" aria-label="Test targets">
          {TARGETS.map((t) => (
            <li key={t.q}>
              <button
                type="button"
                className="chip"
                data-target={t.q}
                aria-current={current === t ? 'true' : undefined}
                onClick={() => {
                  setInput(t.q)
                  search(t.q, t.det)
                }}
              >
                <strong>{t.label}</strong>
                <span>{t.note}</span>
              </button>
              <a className="deep-link" href={`/?target=${t.id}`}>
                Deep dive in WANDERERS →
              </a>
            </li>
          ))}
        </ul>

        {state.status === 'home' && (
          <div className="home">
            <section className="panel">
              <header className="panel-head">
                <h2 className="panel-title">Explore any patch of sky</h2>
              </header>
              <div className="panel-body">
                <h1>Blink NASA SPHEREx images to find what moves or changes</h1>
                <p id="home-hint" className="muted">
                  Type a star name or a sky position, or pick a test target.
                </p>
                <p>
                  The tool gets the SPHEREx survey images of that patch from IRSA, stacks one frame per survey and plays them as a
                  flipbook. A <strong>mover</strong> changes position between surveys (a nearby star or brown dwarf). A{' '}
                  <strong>blinker</strong> changes brightness (a variable star).
                </p>
                <p className="hint">
                  Then mark candidates, check them against Gaia DR3 and SIMBAD, and report them on Backyard Worlds Talk.
                </p>
              </div>
            </section>
            {EXAMPLES.map((ex) => (
              <section className="panel" key={ex.id}>
                <header className="panel-head">
                  <h2 className="panel-title">Field guide · {ex.title}</h2>
                </header>
                <div className="panel-body example">
                  <Thumbs ex={ex} reduced={REDUCED_MOTION} />
                  <p>{ex.text}</p>
                </div>
              </section>
            ))}
          </div>
        )}

        {(loading || state.status === 'result') && (
          <div className="results" data-status={state.status} aria-busy={loading}>
            <div className="workspace">
              <section className="viewer" data-status={state.status} aria-label="Flipbook">
                <div className="target-line" id="target-line">
                  <h1 id="target-name">{loading || !r ? `Loading ${state.q}…` : (r.name ?? r.query)}</h1>
                  {r && !loading && (
                    <span className="mono muted">
                      {raText(r.center.ra)} {decText(r.center.dec)} · {r.pm ? 'J2026.0' : 'as entered'} · {r.fov_arcmin}′ ·{' '}
                      {count} frames
                    </span>
                  )}
                </div>
                <Boundary name="Flipbook">
                  <div className="flip">
                    <Stage
                      r={r}
                      index={at}
                      diff={state.view === 'diff'}
                      look={state.look}
                      bri={bri}
                      con={con}
                      ring={showRing && !!r?.pm}
                      gaia={showGaia}
                      cross={showCross}
                      marks={state.marks}
                      loading={loading}
                      elapsed={elapsed}
                      query={state.q}
                      onMark={mark}
                    />
                    <p className="frame-label" aria-live={playing ? 'off' : 'polite'}>
                      {!loading && frame && !showDiff
                        ? `Frame ${at + 1} of ${count} · ${frame.label} · ${frame.n_images} images`
                        : !loading && showDiff
                          ? `Difference: ${r!.difference!.to} minus ${r!.difference!.from}`
                          : ' '}
                    </p>
                    <p className="note">
                      {!loading && state.view === 'diff' && r
                        ? r.difference
                          ? 'A mover shows as a dark and bright pair: dark where it was, bright where it is now. A blinker shows as a dark or bright spot.'
                          : 'A difference needs at least two surveys. This position has only one so far.'
                        : !loading && satN
                          ? `Saturated in ${satN} of ${count} frames: SPHEREx cannot measure this star’s brightness change here. The white core has no data.${r!.frames.some((f) => f.centroid?.saturated) ? ' Positions come from the wings.' : ''}`
                          : ' '}
                    </p>
                    <div className="toolbar" role="group" aria-label="Flipbook controls">
                      <div className="group">
                        <button
                          type="button"
                          onClick={() => setPlaying((p) => !p)}
                          disabled={!canPlay}
                          aria-label={playing && canPlay ? 'Pause' : 'Play'}
                        >
                          <PlayIcon playing={playing && canPlay} />
                        </button>
                        <button type="button" onClick={() => pickFrame((at + count - 1) % count)} disabled={!canPlay} aria-label="Previous frame">
                          <StepIcon dir={-1} />
                        </button>
                        <button type="button" onClick={() => pickFrame((at + 1) % count)} disabled={!canPlay} aria-label="Next frame">
                          <StepIcon dir={1} />
                        </button>
                        <label className="speed">
                          {fps}/s
                          <input type="range" min={1} max={10} value={fps} onChange={(e) => setFps(Number(e.target.value))} aria-label="Speed, frames per second" />
                        </label>
                      </div>
                      <div className="group" role="group" aria-label="View">
                        <button type="button" aria-pressed={state.view === 'blink'} disabled={!r} onClick={() => go({ view: 'blink' }, 'replace')}>
                          Blink
                        </button>
                        <button type="button" aria-pressed={state.view === 'diff'} disabled={!r} onClick={() => go({ view: 'diff' }, 'replace')}>
                          Difference
                        </button>
                      </div>
                      <div className="group" role="group" aria-label="Overlays">
                        <button
                          type="button"
                          className="toggle"
                          aria-pressed={showRing && !!r?.pm}
                          disabled={!r?.pm}
                          onClick={() => setShowRing((v) => !v)}
                          title={r && !r.pm ? 'Needs a known proper motion: search by name' : 'Where the target should be'}
                        >
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <circle cx="8" cy="8" r="5.5" fill="none" strokeWidth="2" strokeDasharray="4 2" className="legend-ring" />
                          </svg>
                          Ring
                        </button>
                        <button
                          type="button"
                          className="toggle"
                          aria-pressed={showGaia && !!r?.gaia}
                          disabled={!r?.gaia}
                          onClick={() => setShowGaia((v) => !v)}
                          title={r?.gaia ? `${r.gaia.stars.length} ${r.gaia.release} stars` : 'No Gaia data in this answer'}
                        >
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <circle cx="8" cy="8" r="5" fill="none" strokeWidth="1.2" className="legend-ghost" />
                          </svg>
                          Gaia
                        </button>
                        <button type="button" className="toggle" aria-pressed={showCross} onClick={() => setShowCross((v) => !v)}>
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M2 8h4m4 0h4M8 2v4m0 4v4" strokeWidth="1.5" className="legend-cross" />
                          </svg>
                          Crosshair
                        </button>
                      </div>
                      <div className="group">
                        <label className="speed" style={{ fontFamily: 'var(--sans)' }}>
                          <span className="group-label">Look</span>
                          <select id="look" value={state.look} onChange={(e) => go({ look: e.target.value as Look }, 'replace')}>
                            {LOOKS.map(([k, label]) => (
                              <option key={k} value={k} disabled={!!r && needsRgb(k) && !rgbOk}>
                                {label}
                                {!!r && needsRgb(k) && !rgbOk ? ' (no colour image for this view)' : ''}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    </div>
                    {needsRgb(state.look) && (
                      <p className="colour-legend">
                        {rgbOk && wl ? (
                          <>
                            {(['blue', 'green', 'red'] as const)
                              .filter((c) => wl[c])
                              .map((c) => `${c} ${short(wl[c]![0])}–${short(wl[c]![1])} µm`)
                              .join(' · ')}
                            . {COLOUR_LINE}
                          </>
                        ) : rgbOk ? (
                          COLOUR_LINE
                        ) : (
                          'Infrared colour needs the colour image (rgb_png), which this view does not have (for example a one-detector stack). Showing gray, smoothed.'
                        )}
                        {rgbOk &&
                          r?.notes
                            ?.filter((n) => n.startsWith('Colour'))
                            .map((n) => (
                              <span key={n} style={{ display: 'block' }}>
                                {n}
                              </span>
                            ))}
                      </p>
                    )}
                    <Timeline r={r} index={at} diff={showDiff} onPick={pickFrame} />
                    <p className="hint" style={{ width: '100%' }}>
                      Click the image to mark a candidate. Black means no data; a white star core is saturated. Keys: Space plays or
                      pauses, ← and → step.
                    </p>
                    <details className="expert">
                      <summary>Expert settings</summary>
                      <div className="expert-grid">
                        <form
                          onSubmit={(e) => {
                            e.preventDefault()
                            go({ fov: clampFov(Number(new FormData(e.currentTarget).get('fov'))) }, 'replace')
                          }}
                        >
                          <label>
                            Field (arcmin, 2 to 15)
                            <input key={state.fov} name="fov" type="number" min={2} max={15} step={1} defaultValue={state.fov} />
                          </label>
                          <button type="submit">Apply</button>
                        </form>
                        <label>
                          Detector
                          <select value={state.det} onChange={(e) => go({ det: e.target.value }, 'replace')}>
                            {DETECTORS.map(([value, text]) => (
                              <option key={value} value={value}>
                                {text}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Brightness <span className="mono">{bri.toFixed(2)}</span>
                          <input type="range" min={0.5} max={2} step={0.05} value={bri} onChange={(e) => setBri(Number(e.target.value))} />
                        </label>
                        <label>
                          Contrast <span className="mono">{con.toFixed(2)}</span>
                          <input type="range" min={0.5} max={2} step={0.05} value={con} onChange={(e) => setCon(Number(e.target.value))} />
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            setBri(1)
                            setCon(1)
                          }}
                          disabled={bri === 1 && con === 1}
                        >
                          Reset display
                        </button>
                      </div>
                      <p className="hint" style={{ paddingBottom: 8 }}>
                        Brightness and contrast change the display only. Measurements use the raw pixels.
                      </p>
                    </details>
                  </div>
                </Boundary>
              </section>

              <aside className="rail panel" aria-label="Task, data and field guide">
                <div className="tabs" role="tablist" aria-label="Rail" onKeyDown={tabKeys}>
                  {TABS.map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      role="tab"
                      id={`tab-${id}`}
                      aria-selected={tab === id}
                      aria-controls="rail-panel"
                      tabIndex={tab === id ? 0 : -1}
                      onClick={() => setTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="panel-body rail-body" role="tabpanel" id="rail-panel" aria-labelledby={`tab-${tab}`} tabIndex={0}>
                  <Boundary name={TABS.find(([id]) => id === tab)![1]} key={tab}>
                    {tab === 'task' && (
                      <TaskTab
                        r={loading ? null : r}
                        marks={state.marks}
                        onRemove={(k) => {
                          go({ marks: state.marks.filter((_, i) => i !== k) }, 'replace')
                          say(`Candidate ${k + 1} removed.`)
                        }}
                        onCopyLink={() => copy(location.href, 'Link copied. It holds the target, the view and your marks.')}
                        onTalk={() => r && state.marks.length && copy(reportText(r, state.marks, location.href), 'Report copied. Paste it into your Talk post.')}
                      />
                    )}
                    {tab === 'data' &&
                      (r && !loading ? (
                        <>
                          <h3 className="panel-title">Target</h3>
                          <TargetCard r={r} />
                          <h3 className="panel-title">Data quality</h3>
                          <QualityPanel r={r} />
                        </>
                      ) : (
                        <Skeleton lines={6} />
                      ))}
                    {tab === 'guide' && <FieldGuide reduced={REDUCED_MOTION} />}
                  </Boundary>
                </div>
              </aside>
            </div>

            <div className="grid">
              <Panel id="motion" title="Motion · predicted vs measured">
                {r ? <MotionPanel r={r} index={at} onPick={pickFrame} /> : <Skeleton lines={8} />}
              </Panel>
              <Panel id="brightness" title="Brightness · per frame">
                {r ? (
                  <BrightnessPanel key={key} r={r} index={at} deepLink={current && `/?target=${current.id}`} />
                ) : (
                  <Skeleton lines={8} />
                )}
              </Panel>
              <Panel id="sky-context" title="Sky context">
                {r ? <SkyContext r={r} reduced={REDUCED_MOTION} /> : <Skeleton lines={8} />}
              </Panel>
              <Panel id="sky-now" title="Your sky now">
                {r ? <SkyNow star={r.center} here={here} setHere={setHere} reduced={REDUCED_MOTION} say={say} /> : <Skeleton lines={8} />}
              </Panel>
            </div>
            <div className="grid">
              <Panel id="frames" title="Frames">
                {r ? <FramesTable r={r} index={at} onPick={pickFrame} /> : <Skeleton lines={5} />}
              </Panel>
            </div>
          </div>
        )}

        <footer>
          Data: NASA/JPL-Caltech/IPAC SPHEREx (IRSA), ESA Gaia DR3, CDS. Not an official NASA product.
          <br />
          WANDERERS · NASA Space Apps 2026, Planet X and SPHEREx challenge. Sky map: Aladin Lite (CDS).
        </footer>
      </main>

      <dialog
        ref={dialogRef}
        className="dialog"
        aria-labelledby="layer-title"
        onCancel={(e) => {
          e.preventDefault()
          closeLayer()
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) closeLayer() // a click on the backdrop
        }}
      >
        {state.layer === 'tutorial' && <Tutorial reduced={REDUCED_MOTION} onClose={closeLayer} />}
      </dialog>

      <p className="toast" role="status" aria-live="polite">
        {toast}
      </p>
    </>
  )
}
