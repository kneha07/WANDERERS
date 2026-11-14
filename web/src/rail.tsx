// Right rail content: the task (mark, check, report), the field guide, and the first-run tutorial cards.
import { useState } from 'react'
import { KNOWN_ARCSEC, nearestGaia } from './data'
import type { Result } from './data'
import { decText, raText, skyToPixel } from './sky'
import type { RaDec } from './sky'
import { Empty } from './panels'

const EX = `${import.meta.env.BASE_URL}examples/`
export const CREDIT = 'Example images: NASA/JPL-Caltech/IPAC SPHEREx (IRSA), DR1 and QR3, through this tool.'
export const TALK_URL = 'https://www.zooniverse.org/projects/marckuchner/backyard-worlds-planet-9/talk'
export const COLOUR_LINE =
  'Colours are infrared wavelengths shown as visible colours: cold brown dwarfs look red, hot stars look blue.'

type Img = { src: string; caption: string }
type Example = { id: string; title: string; images: Img[]; text: string; tell: string; blink?: boolean }

// Real crops from /api/frames answers (web/scripts/make-examples.py). Captions name the frame each one comes from.
export const EXAMPLES: Example[] = [
  {
    id: 'mover',
    title: 'Mover',
    images: [
      { src: 'mover-1.png', caption: '2025-08' },
      { src: 'mover-2.png', caption: '2026-08' },
    ],
    blink: true,
    text: "A mover changes position from frame to frame. Here Barnard's Star, the fastest star in our sky, moves north in one year.",
    tell: 'The dot shifts between frames and the amber ring follows it. Nearby stars and brown dwarfs move like this.',
  },
  {
    id: 'dipole',
    title: 'Dipole',
    images: [{ src: 'dipole.png', caption: 'difference' }],
    text: "In the Difference view (last frame minus first), a mover makes a dipole: dark where it was, bright where it is now. This is Kapteyn's Star.",
    tell: 'A dark and a bright spot side by side. The line from dark to bright is the direction of motion.',
  },
  {
    id: 'blinker',
    title: 'Blinker',
    images: [
      { src: 'blinker-1.png', caption: '2025-09' },
      { src: 'blinker-2.png', caption: '2026-09' },
      { src: 'blinker-diff.png', caption: 'difference' },
    ],
    text: 'A blinker stays in place but changes brightness. RW Aurigae, a young star, is fainter in the later frame.',
    tell: 'The difference shows a dark or bright spot with no partner beside it. Check the Brightness panel.',
  },
]

export const ARTIFACTS: Example[] = [
  {
    id: 'hot-pixel',
    title: 'Hot pixel or cosmic ray',
    images: [{ src: 'hot-pixel.png', caption: 'D5, 2026-02' }],
    text: 'One or two sharp bright pixels in one frame only (RW Aur field, detector D5, at the right).',
    tell: 'No star there in the other frames, and sharper than a star. Not real: do not mark it.',
  },
  {
    id: 'saturated',
    title: 'Saturated core',
    images: [{ src: 'saturated-core.png', caption: 'Barnard' }],
    text: 'A flat white core: the detector filled up, so the core has no data.',
    tell: 'Brightness is not measurable. The position still comes from the wings (hollow points in Motion).',
  },
  {
    id: 'no-data',
    title: 'Edge or no data',
    images: [{ src: 'no-data.png', caption: 'D2, 2026-09' }],
    text: 'Black pixels have no data: the detector edge, or pixels flagged bad (here around Barnard’s Star in one D2 image).',
    tell: 'A star can seem to blink when it falls on such pixels. Compare with other frames before you mark it.',
  },
]

export const COLOUR: Example = {
  id: 'colour',
  title: 'Infrared colour',
  images: [{ src: 'colour.png', caption: 'RW Aur, 2025-09' }],
  text: COLOUR_LINE,
  tell: 'RW Aur, a young star in dust, looks orange-red; the ordinary stars around it look blue. The Look menu shows this view; measurements always use the raw pixels.',
}

export function Thumbs({ ex, reduced, large }: { ex: Example; reduced: boolean; large?: boolean }) {
  const figs = ex.images.map((im) => (
    <figure key={im.src}>
      <img src={EX + im.src} alt={`${ex.title} example, ${im.caption}`} width={large ? 132 : 84} height={large ? 132 : 84} />
      <figcaption>{im.caption}</figcaption>
    </figure>
  ))
  // A two-frame blink, unless the reader asked for reduced motion (then side by side).
  if (ex.blink && !reduced)
    return (
      <div className="thumbs blinking">
        <div className="blink">{figs}</div>
        <p className="hint">Blinks between {ex.images.map((i) => i.caption).join(' and ')}.</p>
      </div>
    )
  return <div className="thumbs">{figs}</div>
}

export function FieldGuide({ reduced }: { reduced: boolean }) {
  return (
    <div className="guide">
      <p className="hint">What you see in the flipbook, from real SPHEREx frames.</p>
      {[...EXAMPLES, COLOUR, ...ARTIFACTS].map((ex) => (
        <article className="example" key={ex.id}>
          <Thumbs ex={ex} reduced={reduced} />
          <div>
            <h3>{ex.title}</h3>
            <p>{ex.text}</p>
            <p className="hint">{ex.tell}</p>
          </div>
        </article>
      ))}
      <p className="credit">{CREDIT}</p>
    </div>
  )
}

export function Tutorial({ reduced, onClose }: { reduced: boolean; onClose: () => void }) {
  const [step, setStep] = useState(0)
  const ex = EXAMPLES[step]
  const last = step === EXAMPLES.length - 1
  return (
    <div className="dialog-body">
      <p className="panel-title">
        How to look · {step + 1} of {EXAMPLES.length}
      </p>
      <h2 id="layer-title">{ex.title}</h2>
      <Thumbs ex={ex} reduced={reduced} large />
      <p>{ex.text}</p>
      <p className="hint">{ex.tell}</p>
      {last && (
        <>
          <p>Your task: mark what moves or blinks, check it in Gaia and SIMBAD, then report it on Backyard Worlds Talk.</p>
          <p className="hint">{COLOUR_LINE}</p>
        </>
      )}
      <p className="credit">{CREDIT}</p>
      <div className="dialog-foot">
        <button type="button" id="layer-close" onClick={onClose}>
          {last ? 'Close' : 'Skip tutorial'}
        </button>
        <div className="actions" style={{ marginTop: 0 }}>
          {step > 0 && (
            <button type="button" onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          <button type="button" className="primary" data-autofocus onClick={() => (last ? onClose() : setStep(step + 1))}>
            {last ? 'Start exploring' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}

export const lookups = (m: RaDec) => {
  const c = encodeURIComponent(`${m.ra.toFixed(5)} ${m.dec >= 0 ? '+' : ''}${m.dec.toFixed(5)}`)
  return {
    simbad: `https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=${c}&Radius=10&Radius.unit=arcsec`,
    gaia: `https://vizier.cds.unistra.fr/viz-bin/VizieR-4?-source=I/355/gaiadr3&-c=${c}&-c.rs=10`,
    wiseview: `http://byw.tools/wiseview#ra=${m.ra.toFixed(5)}&dec=${m.dec.toFixed(5)}&size=176&band=3&speed=164&minbright=-50.0000&maxbright=500.0000&window=0.5&diff_window=1&linear=1&color=&zoom=9&border=0&gaia=1&invert=1&maxdyr=0&scandir=0&neowise=0&diff=0&outer_epochs=0&unique_window=1&smooth_scan=0&shift=0&pmra=0&pmdec=0`,
  }
}

/** Nearest Gaia star of a candidate, in words the task rail and the report share. */
export function matchOf(r: Result, m: RaDec) {
  const hit = nearestGaia(r, r.gaia, skyToPixel(r, m))
  return { hit, known: !!hit && hit.sep < KNOWN_ARCSEC }
}

export function reportText(r: Result, marks: RaDec[], url: string) {
  const lines = marks.map((m, k) => {
    const { hit, known } = matchOf(r, m)
    const g = hit ? `nearest ${r.gaia!.release} ${hit.star.source_id} at ${hit.sep.toFixed(1)}″${known ? ' (known)' : ' (unexplained)'}` : 'no Gaia data'
    return `${k + 1}. RA ${raText(m.ra)}, Dec ${decText(m.dec)} (${m.ra.toFixed(5)}, ${m.dec.toFixed(5)}): ${g}`
  })
  return [
    `Candidate${marks.length === 1 ? '' : 's'} from WANDERERS Explore (NASA SPHEREx images from IRSA)`,
    `Field: ${r.name ?? r.query}, ${r.fov_arcmin}′, frames ${r.frames[0]?.label} to ${r.frames[r.frames.length - 1]?.label}`,
    ...lines,
    `Link: ${url}`,
  ].join('\n')
}

type TaskProps = {
  r: Result | null
  marks: RaDec[]
  onRemove: (k: number) => void
  onCopyLink: () => void
  onTalk: () => void
}

export function TaskTab({ r, marks, onRemove, onCopyLink, onTalk }: TaskProps) {
  return (
    <>
      <ol className="steps">
        <li>Play the flipbook. Look for a dot that moves (a mover) or gets brighter and fainter (a blinker).</li>
        <li>Click the image to mark a candidate. Each mark gets a number.</li>
        <li>Check each mark. A mover without a green Gaia circle is unexplained.</li>
        <li>Done? Copy the link and report it on Backyard Worlds Talk.</li>
      </ol>
      <h3 className="panel-title">Candidates ({marks.length})</h3>
      {!r ? (
        <Empty>Load a target to mark candidates.</Empty>
      ) : marks.length === 0 ? (
        <Empty>No candidates yet. Click the image where something moves or blinks.</Empty>
      ) : (
        <ul className="cands">
          {marks.map((m, k) => {
            const { hit, known } = matchOf(r, m)
            const links = lookups(m)
            return (
              <li className="cand" key={`${m.ra},${m.dec},${k}`}>
                <div className="cand-head">
                  <span className="cand-no" aria-label={`Candidate ${k + 1}`}>
                    {k + 1}
                  </span>
                  <div>
                    <div className="mono">
                      {raText(m.ra)} {decText(m.dec)}
                    </div>
                    <div className="mono hint">
                      {m.ra.toFixed(5)}°, {m.dec >= 0 ? '+' : ''}
                      {m.dec.toFixed(5)}°
                    </div>
                  </div>
                </div>
                <p className={`badge ${hit ? (known ? 'known' : 'unknown') : ''}`}>
                  {r.gaia === undefined ? (
                    'Gaia data not in this answer.'
                  ) : r.gaia === null ? (
                    'Gaia query failed: check it by hand.'
                  ) : !hit ? (
                    'No Gaia star in view.'
                  ) : known ? (
                    <>
                      <span aria-hidden="true">✓</span> Known in {r.gaia.release}: {hit.star.source_id}
                      {hit.star.gmag != null && `, G ${hit.star.gmag.toFixed(1)}`}, {hit.sep.toFixed(1)}″ away
                    </>
                  ) : (
                    <>
                      <span aria-hidden="true">?</span> Unexplained: nearest {r.gaia.release} star is {hit.sep.toFixed(1)}″ away
                      {hit.star.gmag != null && ` (G ${hit.star.gmag.toFixed(1)})`}
                    </>
                  )}
                </p>
                <div className="actions">
                  <a href={links.simbad} target="_blank" rel="noreferrer">
                    Check SIMBAD ↗
                  </a>
                  <a href={links.gaia} target="_blank" rel="noreferrer">
                    Check Gaia ↗
                  </a>
                  <a href={links.wiseview} target="_blank" rel="noreferrer">
                    WiseView ↗
                  </a>
                  <button type="button" onClick={() => onRemove(k)} aria-label={`Remove candidate ${k + 1}`}>
                    Remove
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <h3 className="panel-title">Done &amp; Talk</h3>
      <p className="hint">The link holds the target, the view and your marks. The Talk button also copies a report you can paste.</p>
      <div className="actions">
        <button type="button" onClick={onCopyLink} disabled={!r}>
          Copy share link
        </button>
        <a href={TALK_URL} target="_blank" rel="noreferrer" onClick={onTalk}>
          Report on Backyard Worlds Talk ↗
        </a>
      </div>
    </>
  )
}
