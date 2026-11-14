// The flipbook: the stage (image + overlays) and the timeline (frames on a real date axis).
import { useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, MouseEvent, PointerEvent } from 'react'
import { labelRange, monthTicks } from './data'
import type { Result } from './data'
import { skyToPixel } from './sky'
import type { RaDec } from './sky'

export type Look = 'raw' | 'smooth' | 'colour' | 'realistic'
export const LOOKS: [Look, string][] = [
  ['raw', 'Raw pixels'],
  ['smooth', 'Smooth'],
  ['colour', 'Infrared colour'],
  ['realistic', 'Realistic'],
]
export const needsRgb = (look: Look) => look === 'colour' || look === 'realistic'

type StageProps = {
  r: Result | null
  index: number
  diff: boolean
  look: Look
  bri: number
  con: number
  ring: boolean
  gaia: boolean
  cross: boolean
  marks: RaDec[]
  loading: boolean
  elapsed: number
  query: string
  onMark: (x: number, y: number) => void
}

export function Stage(p: StageProps) {
  const { r } = p
  const n = r?.size_px ?? 1
  const f = r?.frames[p.index] ?? null
  const showDiff = p.diff && !!r?.difference
  const colour = needsRgb(p.look) && !showDiff && !!f?.rgb_png
  const src = !r || !f ? null : showDiff ? r.difference!.png : colour ? f.rgb_png! : f.png
  const smooth = p.look !== 'raw'
  const glow = p.look === 'realistic' && !showDiff
  // The ring of the difference view is where the target is in the last frame.
  const ring = showDiff ? r!.frames[r!.frames.length - 1].ring : f?.ring
  const at = showDiff ? r!.frames.length - 1 : p.index
  const label = !smooth
    ? ''
    : [
        showDiff ? 'Difference (gray)' : colour ? 'False-colour infrared' : needsRgb(p.look) ? 'Gray (no colour image here)' : '',
        glow ? 'smoothed, with glow, for display' : 'smoothed for display',
        'measurements use raw pixels',
      ]
        .filter(Boolean)
        .join(' · ')

  const click = (e: MouseEvent<HTMLDivElement>) => {
    if (!r || p.loading) return
    const box = e.currentTarget.getBoundingClientRect()
    p.onMark(((e.clientX - box.left) / box.width) * n, ((e.clientY - box.top) / box.height) * n)
  }

  return (
    <div
      className={r ? 'stage' : 'stage skeleton'}
      data-smooth={smooth}
      style={{ '--bri': p.bri, '--con': p.con } as CSSProperties}
      onClick={click}
      tabIndex={-1}
      id="stage"
    >
      {src && (
        <img
          className="sky"
          src={src}
          alt={
            showDiff
              ? `Difference image, ${r!.difference!.to} minus ${r!.difference!.from}`
              : `SPHEREx ${f!.label}, mean date ${f!.date}, ${f!.n_images} images stacked`
          }
        />
      )}
      {src && glow && <img className="sky glow" src={src} alt="" aria-hidden="true" />}
      {r && (
        <svg viewBox={`0 0 ${n} ${n}`} aria-hidden="true">
          {p.gaia &&
            r.gaia?.stars.map((s) => {
              const xy = s.xy[at]
              // Faint Gaia stars fade, so the bright ones that SPHEREx sees stand out (display only).
              const o = s.gmag == null ? 1 : Math.min(1, Math.max(0.3, (20 - s.gmag) / 5))
              return xy && <circle key={s.source_id} className="ghost" cx={xy[0]} cy={xy[1]} r={1.4} opacity={o} />
            })}
          {p.ring && ring && <circle className="ring" cx={ring.x} cy={ring.y} r={2.6} />}
          {p.cross && <path className="cross" d={`M${n / 2 - 3} ${n / 2}h2m2 0h2M${n / 2} ${n / 2 - 3}v2m0 2v2`} />}
          {p.marks.map((m, k) => {
            const q = skyToPixel(r, m)
            return (
              <g className="mark" key={k}>
                <rect x={q.x - 1.1} y={q.y - 1.1} width={2.2} height={2.2} />
                <text x={q.x + 1.6} y={q.y - 1.4}>
                  {k + 1}
                </text>
              </g>
            )
          })}
        </svg>
      )}
      {label && <p className="look-label">{label}</p>}
      {p.loading && (
        <p className="indicator" role="status">
          <span>
            Fetching SPHEREx images of {p.query} from IRSA. The first load of a target takes up to a minute; later loads are
            instant. <span className="mono">{p.elapsed} s</span>
          </span>
        </p>
      )}
    </div>
  )
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** Frames on a real date axis. Click or tap anywhere to jump to the nearest frame; arrows step (global keys). */
export function Timeline({ r, index, diff, onPick }: { r: Result | null; index: number; diff: boolean; onPick: (i: number) => void }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  const frames = r?.frames ?? []
  const spans = frames.map((f) => labelRange(f.label) ?? [f.mjd_mean - 0.5, f.mjd_mean + 0.5])
  const a = Math.min(...spans.map((s) => s[0]))
  const b = Math.max(...spans.map((s) => s[1]))
  const pad = Math.max(10, (b - a) * 0.04)
  const x0 = a - pad
  const x1 = b + pad
  const X = (m: number) => 12 + ((m - x0) / (x1 - x0 || 1)) * Math.max(w - 24, 1)
  const pick = (e: PointerEvent<HTMLDivElement>) => {
    if (!frames.length) return
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left - 8
    let best = 0
    frames.forEach((f, i) => {
      if (Math.abs(X(f.mjd_mean) - x) < Math.abs(X(frames[best].mjd_mean) - x)) best = i
    })
    onPick(best)
  }
  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      onPick(e.key === 'Home' ? 0 : frames.length - 1)
    }
  }
  const cur = frames[index]
  return (
    <div
      ref={ref}
      className={r ? 'timeline' : 'timeline skeleton'}
      role="slider"
      tabIndex={frames.length ? 0 : -1}
      aria-label="Frame timeline"
      aria-valuemin={1}
      aria-valuemax={Math.max(frames.length, 1)}
      aria-valuenow={index + 1}
      aria-valuetext={cur ? `Frame ${index + 1} of ${frames.length}, ${cur.label}` : 'No frames yet'}
      onPointerDown={pick}
      onKeyDown={keys}
    >
      <svg aria-hidden="true" viewBox={`0 0 ${Math.max(w, 1)} 76`}>
        {frames.length > 0 && w > 0 && (
          <>
            <line className="axis" x1={4} x2={w - 4} y1={46} y2={46} />
            {monthTicks(x0, x1, Math.max(2, Math.floor(w / 72)))
              .filter((m) => X(m) > 26 && X(m) < w - 26) // a label never runs off the edge
              .map((m) => (
              <g key={m}>
                <line className="axis" x1={X(m)} x2={X(m)} y1={46} y2={52} />
                <text x={X(m)} y={66} textAnchor="middle">
                  {new Date((m - 40_587) * 86_400_000).toISOString().slice(0, 7)}
                </text>
              </g>
            ))}
            {diff && frames.length > 1 && (
              <path className="bracket" d={`M${X(frames[0].mjd_mean)} 40v-3H${X(frames[frames.length - 1].mjd_mean)}v3`} />
            )}
            {frames.map((f, i) => (
              <g key={f.label} className={(diff ? i === 0 || i === frames.length - 1 : i === index) ? 'current' : undefined}>
                <rect className="span" x={X(spans[i][0])} y={25} width={Math.max(3, X(spans[i][1]) - X(spans[i][0]))} height={10} rx={2} />
                <circle className="dot" cx={X(f.mjd_mean)} cy={30} r={i === index && !diff ? 6 : 4} />
                <text x={X(f.mjd_mean)} y={14} textAnchor="middle">
                  {i + 1}
                </text>
              </g>
            ))}
          </>
        )}
      </svg>
    </div>
  )
}
