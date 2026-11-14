// "Sky context": Aladin Lite (CDS) flies from a wide view down to the target, like a globe zooming in.
// aladin-lite is loaded on demand (its own chunk). Any failure here stays inside this panel.
import { useEffect, useRef, useState } from 'react'
import type { Result } from './data'
import { pixelToSky } from './sky'
import { AlertIcon } from './panels'

const SURVEYS: { id: string; label: string; url: string; credit: string; slice?: number }[] = [
  // The SPHEREx HiPS is a cube of 102 wavelength slices; slice 46 is 2.19 um (like 2MASS K). Slices 50 and 51 are blank.
  { id: 'spherex', label: 'SPHEREx 2.2 µm', url: 'https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube', credit: 'SPHEREx DR1 all-sky cube HiPS, slice 46 = 2.19 µm (IRSA)', slice: 46 },
  // CDS HiPS from the IRSA mirrors (CORS open). The CDS primary host answered 404 on 2026-11-14.
  { id: '2mass', label: '2MASS', url: 'https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color', credit: '2MASS colour HiPS (CDS, IRSA mirror)' },
  { id: 'dss', label: 'DSS2', url: 'https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color', credit: 'DSS2 colour HiPS (CDS, IRSA mirror)' },
]
const WIDE_DEG = 60

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

type Any = any
type Survey = (typeof SURVEYS)[number]

// ponytail: Aladin 3.8.2 turns a slice number into a frequency linearly in wavelength, and its renderer turns the
// frequency back into a frame linearly in frequency, so setSliceNumber(k) shows another frame. This inverts that
// mapping (checked against the tile names it requests). Drop it when Aladin selects cube frames by index.
const sliceArg = (h: Any, k: number) => {
  const lo = 1 / h.emMax
  const f = lo + ((k + 0.5) / h.cubeDepth) * (1 / h.emMin - lo)
  return ((1 / f - h.emMin) / (h.emMax - h.emMin)) * h.cubeDepth
}

// A HiPS layer; a cube (SPHEREx) starts on its chosen wavelength frame.
const hipsOf = (A: Any, s: Survey) =>
  A.imageHiPS(s.url, {
    name: s.label,
    successCallback: (h: Any) => s.slice !== undefined && h.cubeDepth && h.setSliceNumber(sliceArg(h, s.slice)),
  })

export default function SkyContext({ r, reduced }: { r: Result; reduced: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const lib = useRef<Any>(null)
  const view = useRef<Any>(null)
  const seq = useRef(0)
  const shown = useRef<Survey>(SURVEYS[0])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [survey, setSurvey] = useState(SURVEYS[0])
  const [flying, setFlying] = useState(false)
  const { ra, dec } = r.center

  // Create the viewer once, wide, at the first target.
  useEffect(() => {
    let live = true
    import('aladin-lite')
      .then(async ({ default: A }) => {
        await A.init
        if (!live || !box.current) return
        lib.current = A
        view.current = A.aladin(box.current, {
          survey: hipsOf(A, SURVEYS[0]),
          fov: WIDE_DEG * 2,
          target: `${ra} ${dec}`,
          projection: 'SIN',
          showReticle: false,
          showLayersControl: false,
          showFullscreenControl: false,
          showProjectionControl: false,
          showFrame: false,
          showCooGridControl: false,
          showSettingsControl: false,
          showShareControl: false,
          showSimbadPointerControl: false,
          showContextMenu: false,
          log: false, // no startup ping to CDS
          showCooLocation: false, // the flipbook panels show the coordinates
        })
        setStatus('ready')
      })
      .catch((e) => {
        if (!live) return
        setStatus('error')
        setError(String(e?.message ?? e))
      })
    return () => {
      live = false
    }
  }, [])

  // For each target: draw the flipbook field, then zoom out, fly over and zoom in (reduced motion: jump).
  useEffect(() => {
    const a = view.current
    const A = lib.current
    if (status !== 'ready' || !a) return
    const n = r.size_px
    const corners = [
      [0, 0],
      [n, 0],
      [n, n],
      [0, n],
    ].map(([x, y]) => pixelToSky(r, x, y))
    a.removeOverlays()
    const overlay = A.graphicOverlay({ color: token('--data'), lineWidth: 2 })
    a.addOverlay(overlay)
    overlay.add(A.polygon(corners.map((c) => [c.ra, c.dec])))
    const close = Math.max((r.fov_arcmin * 4) / 60, 0.25)
    const me = ++seq.current
    const ok = () => me === seq.current
    if (reduced) {
      a.gotoRaDec(ra, dec)
      a.setFoV(close)
      return
    }
    setFlying(true)
    const wide = Math.max(a.getFov()[0], WIDE_DEG)
    a.zoomToFoV(wide, 1, () =>
      ok() &&
      a.animateToRaDec(ra, dec, 2, () =>
        ok() &&
        a.zoomToFoV(close, 2.5, () => {
          if (ok()) setFlying(false)
        }),
      ),
    )
  }, [status, ra, dec, r.fov_arcmin, r.size_px, r.pixel_arcsec, reduced])

  useEffect(() => {
    const a = view.current
    if (status !== 'ready' || !a || shown.current === survey) return
    shown.current = survey
    a.setImageSurvey(hipsOf(lib.current, survey))
  }, [status, survey])

  return (
    <>
      <div className="place-row">
        <span className="group-label" id="survey-label">
          Background
        </span>
        <div className="segmented" role="group" aria-labelledby="survey-label">
          {SURVEYS.map((s) => (
            <button key={s.id} type="button" aria-pressed={survey.id === s.id} onClick={() => setSurvey(s)} disabled={status !== 'ready'}>
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="skymap">
        <div className="skymap-host" ref={box} aria-label={`Sky map around ${r.name ?? r.query}`} />
        {status === 'loading' && (
          <div className="state" role="status">
            <p className="muted">Loading the sky map…</p>
          </div>
        )}
        {status === 'error' && (
          <div className="state error" role="alert">
            <AlertIcon />
            <p>The sky map could not start ({error}). The flipbook works without it.</p>
          </div>
        )}
      </div>
      <p className="hint" aria-live="polite">
        {status === 'ready'
          ? flying
            ? 'Flying to the target…'
            : `The blue square is the ${r.fov_arcmin}′ flipbook field. Drag to pan, scroll to zoom.`
          : ' '}
      </p>
      <p className="credit">Aladin Lite (CDS, Strasbourg) · {survey.credit}</p>
    </>
  )
}
