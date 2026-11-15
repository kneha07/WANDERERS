// "Your sky now": where the target is in the observer's sky (altitude, azimuth, rise, set), with a sky dome.
import { useEffect, useMemo, useRef, useState } from 'react'
import { altAz, skyDay } from './sky'
import type { RaDec } from './sky'

export type Here = { name: string; lat: number; lon: number; tz?: string; source: 'city' | 'device' | 'manual' }

// Seattle first: the team is in Seattle. A few world cities, both hemispheres.
export const CITIES: Here[] = [
  { name: 'Seattle, USA', lat: 47.6062, lon: -122.3321, tz: 'America/Los_Angeles', source: 'city' },
  { name: 'New York, USA', lat: 40.7128, lon: -74.006, tz: 'America/New_York', source: 'city' },
  { name: 'London, UK', lat: 51.5074, lon: -0.1278, tz: 'Europe/London', source: 'city' },
  { name: 'Nairobi, Kenya', lat: -1.2921, lon: 36.8219, tz: 'Africa/Nairobi', source: 'city' },
  { name: 'Tokyo, Japan', lat: 35.6762, lon: 139.6503, tz: 'Asia/Tokyo', source: 'city' },
  { name: 'Sydney, Australia', lat: -33.8688, lon: 151.2093, tz: 'Australia/Sydney', source: 'city' },
  { name: 'Santiago, Chile', lat: -33.4489, lon: -70.6693, tz: 'America/Santiago', source: 'city' },
]

const POINTS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
export const compass = (az: number) => POINTS[Math.round((((az % 360) + 360) % 360) / 45) % 8]

function clock(d: Date, tz: string | undefined, now: Date) {
  const day = (x: Date) => x.toLocaleDateString('en-CA', { timeZone: tz })
  const t = d.toLocaleTimeString('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit' })
  return day(d) === day(now) ? t : `${d.toLocaleDateString('en-GB', { timeZone: tz, weekday: 'short' })} ${t}`
}

const R = 100 // horizon radius in the dome
const dome = (alt: number, az: number) => {
  const r = (R * (90 - Math.max(alt, 0))) / 90
  const a = (az * Math.PI) / 180
  return { x: 120 + r * Math.sin(a), y: 120 - r * Math.cos(a) } // map view from above: north up, east right
}

type Props = { star: RaDec; here: Here; setHere: (h: Here) => void; reduced: boolean; say: (t: string) => void }

export default function SkyNow({ star, here, setHere, reduced, say }: Props) {
  const [now, setNow] = useState(() => new Date())
  const [manual, setManual] = useState(here.source === 'manual')
  const [locating, setLocating] = useState(false)
  const [geoError, setGeoError] = useState('')
  const [t, setT] = useState(1) // animation progress along the past path, 0..1
  const raf = useRef(0)

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])

  const pos = altAz(star, here, now)
  const day = skyDay(star, here, now)
  // Today's path: the 12 hours before and after now, every 10 minutes.
  const path = useMemo(
    () =>
      Array.from({ length: 145 }, (_, k) => {
        const when = new Date(now.getTime() + (k - 72) * 600_000)
        return { k, ...altAz(star, here, when) }
      }),
    [star, here, now],
  )

  // On open (and for each new target or place) the dot runs along the last 12 hours to now. Reduced motion: no run.
  useEffect(() => {
    if (reduced) return setT(1)
    const t0 = performance.now()
    const step = (ms: number) => {
      const v = Math.min(1, Math.max(0, (ms - t0) / 1600)) // a frame time can be a little before t0
      setT(v)
      if (v < 1) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
  }, [star.ra, star.dec, here.lat, here.lon, reduced])

  const segs = (from: number, to: number) => {
    const out: string[] = []
    let cur: string[] = []
    for (const p of path.slice(from, to + 1)) {
      if (p.alt >= 0) {
        const q = dome(p.alt, p.az)
        cur.push(`${q.x.toFixed(1)},${q.y.toFixed(1)}`)
      } else if (cur.length) {
        out.push(cur.join(' ')) // the path dips below the horizon: end this segment
        cur = []
      }
    }
    if (cur.length) out.push(cur.join(' '))
    return out
  }
  const runAt = path[Math.round(72 * t)] ?? path[72]
  const dot = t < 1 ? runAt : { ...pos, k: 72 }
  const d = dome(dot.alt, dot.az)
  const up = pos.alt >= 0
  const tz = here.tz

  const sentence = up
    ? `${Math.round(pos.alt)}° above your horizon, towards the ${compass(pos.az)}.`
    : day.always === 'down'
      ? 'Below your horizon: it never rises from here.'
      : `Below your horizon now; rises at about ${clock(day.rise!, tz, now)} local, towards the ${compass(altAz(star, here, day.rise!).az)}.`

  const locate = () => {
    if (!('geolocation' in navigator)) return setGeoError('This browser cannot share a location. Pick a city instead.')
    setLocating(true)
    setGeoError('')
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLocating(false)
        setManual(false)
        setHere({ name: 'Your location', lat: p.coords.latitude, lon: p.coords.longitude, source: 'device' })
        say('Location found. It stays in this page only.')
      },
      (e) => {
        setLocating(false)
        setGeoError(`${e.code === 1 ? 'Permission denied' : 'Location not available'}. Pick a city or type a latitude and longitude.`)
      },
      { timeout: 15_000, maximumAge: 600_000 },
    )
  }

  const ang = Math.max(-35, Math.min(90, pos.alt)) * (Math.PI / 180) // below -35 deg the drawing stops; the number does not
  return (
    <>
      <div className="place-row">
        <label>
          Place
          <select
            value={manual ? 'manual' : here.source === 'device' ? 'device' : here.name}
            onChange={(e) => {
              const v = e.target.value
              setManual(v === 'manual')
              const city = CITIES.find((c) => c.name === v)
              if (city) setHere(city)
            }}
          >
            {here.source === 'device' && <option value="device">Your location</option>}
            {CITIES.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
            <option value="manual">Type a latitude and longitude…</option>
          </select>
        </label>
        <button type="button" onClick={locate} disabled={locating} aria-busy={locating}>
          {locating ? 'Locating…' : 'Use my location'}
        </button>
      </div>
      {manual && (
        <form
          className="place-row"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            const lat = Number(f.get('lat'))
            const lon = Number(f.get('lon'))
            if (!(Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) return setGeoError('Latitude is −90 to 90 and longitude is −180 to 180.')
            setGeoError('')
            setHere({ name: `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`, lat, lon, source: 'manual' })
          }}
        >
          <label>
            Lat
            <input name="lat" inputMode="decimal" defaultValue={here.lat.toFixed(4)} aria-label="Latitude, degrees north" />
          </label>
          <label>
            Lon
            <input name="lon" inputMode="decimal" defaultValue={here.lon.toFixed(4)} aria-label="Longitude, degrees east" />
          </label>
          <button type="submit">Apply</button>
        </form>
      )}
      {geoError && (
        <p className="error-text" role="alert">
          {geoError}
        </p>
      )}
      <p className="where" aria-live="polite">
        <strong>{sentence}</strong>
      </p>
      <div className="dome-wrap">
        <svg className="dome" viewBox="0 0 240 240" role="img" aria-label={`Sky dome for ${here.name}: ${sentence}`}>
          <circle className="horizon" cx={120} cy={120} r={R} />
          {[30, 60].map((a) => (
            <g key={a}>
              <circle className="alt-ring" cx={120} cy={120} r={(R * (90 - a)) / 90} />
              <text x={123} y={120 - (R * (90 - a)) / 90 - 3}>
                {a}°
              </text>
            </g>
          ))}
          <text x={123} y={117}>
            90°
          </text>
          <text className="compass" x={120} y={13} textAnchor="middle">
            N
          </text>
          <text className="compass" x={120} y={236} textAnchor="middle">
            S
          </text>
          <text className="compass" x={231} y={124} textAnchor="middle">
            E
          </text>
          <text className="compass" x={9} y={124} textAnchor="middle">
            W
          </text>
          {segs(0, 72).map((pts, k) => (
            <polyline key={`p${k}`} className="path-past" points={pts} />
          ))}
          {segs(72, 144).map((pts, k) => (
            <polyline key={`f${k}`} className="path-future" points={pts} />
          ))}
          <circle className={dot.alt >= 0 ? 'star' : 'star below'} cx={d.x} cy={d.y} r={7} />
        </svg>
        <svg className="dome" viewBox="0 0 240 200" role="img" aria-label={`Side view: altitude ${pos.alt.toFixed(1)} degrees`}>
          <path className="arc" d="M140 140 A100 100 0 0 0 40 40" />
          {[0, 15, 30, 45, 60, 75, 90].map((a) => {
            const r = (a * Math.PI) / 180
            return (
              <g key={a}>
                <line className="arc" x1={40 + 100 * Math.cos(r)} y1={140 - 100 * Math.sin(r)} x2={40 + 107 * Math.cos(r)} y2={140 - 107 * Math.sin(r)} />
                <text x={40 + 120 * Math.cos(r)} y={144 - 120 * Math.sin(r)} textAnchor="middle">
                  {a}°
                </text>
              </g>
            )
          })}
          <line className="ground" x1={8} x2={236} y1={140} y2={140} />
          <text x={236} y={134} textAnchor="end">
            horizon
          </text>
          <line className={up ? 'sight' : 'sight below'} x1={40} y1={140} x2={40 + 90 * Math.cos(ang)} y2={140 - 90 * Math.sin(ang)} />
          <circle className={up ? 'star' : 'star below'} cx={40 + 90 * Math.cos(ang)} cy={140 - 90 * Math.sin(ang)} r={6} />
          <text className="compass" x={40} y={158} textAnchor="middle">
            you
          </text>
          <text x={8} y={194}>
            side view, facing {compass(pos.az)}
          </text>
        </svg>
      </div>
      <dl className="kv">
        <dt>Altitude</dt>
        <dd>{pos.alt.toFixed(1)}°</dd>
        <dt>Azimuth</dt>
        <dd>
          {pos.az.toFixed(1)}° ({compass(pos.az)})
        </dd>
        <dt>Highest</dt>
        <dd>
          {clock(day.transit, tz, now)} at {day.transitAlt.toFixed(0)}°{day.transitAlt < 0 && ' (still below the horizon)'}
        </dd>
        <dt>Rises</dt>
        <dd>{day.always === 'up' ? 'never sets from here' : day.always === 'down' ? 'never rises from here' : clock(day.rise!, tz, now)}</dd>
        <dt>Sets</dt>
        <dd>{day.always ? '–' : clock(day.set!, tz, now)}</dd>
        <dt>Place</dt>
        <dd>
          {here.name} ({here.lat.toFixed(2)}°, {here.lon.toFixed(2)}°)
          <span className="sub">times {tz ? `in ${tz}` : "in your computer's time zone"}</span>
        </dd>
      </dl>
      <p className="hint">
        Map view from above: you stand at the center and the circle is your horizon. The amber line is the target's path over
        the last 12 hours (solid) and the next 12 hours (dashed). Geometric horizon, no refraction; about 0.1° accuracy.
      </p>
      <p className="hint">Your location stays in this page's memory only. It is not sent anywhere and not saved.</p>
    </>
  )
}
