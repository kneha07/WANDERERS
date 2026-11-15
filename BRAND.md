# WANDERERS brand guide

**The sky is never still.** The identity is built on a single scientific idea: measured positional change between epochs.

## The symbol: Orbit Epochs

An observation emblem: the field of view of a telescope, with an orbit crossing it and the object's positions measured over time.

- **Open field circle** (ink): the field of view. It is open along the orbit's major axis: the object is not confined to one frame.
- **Inclined ellipse** (accent, thin): the orbit, a precise geometric path rather than a decorative ring.
- **Focus** (small ink dot): the point the orbit is measured around.
- **Two hollow rings**: earlier epochs, recorded but past.
- **Solid point with a four-tick reticle**: the newest measured position, the one being observed now.

It is drawn on a 40-unit grid (field centre 20, 20; radius 15.5; orbit 13.2 × 6.2 at −28°) and comes in three optical sizes, so line weights stay right at every size:

| Cut | Use | Field / orbit line | Detail |
|---|---|---|---|
| Full | 48 px and up, print, social | 2.5 / 1.15 | everything |
| UI | 24–40 px, site navigation | 3.2 / 1.7 | everything, heavier |
| Favicon | 16–32 px | 4.2 / 2.6 | field, orbit, newest point only |

## Files (`app/brand/`, `app/favicon.svg`)

| File | Use |
|---|---|
| `logo-horizontal-light.svg` / `-dark.svg` | Full-cut emblem + wordmark, on light / dark backgrounds |
| `logo-compact-light.svg` / `-dark.svg` | UI-cut emblem + wordmark with tighter spacing, for phone navigation and small placements |
| `symbol-light.svg` / `symbol-dark.svg` | Emblem only (avatars, app icons, social) |
| `app/favicon.svg` (also `web/public/favicon.svg`) | Favicon cut; switches colours with the OS theme |

On the website the logo is inline SVG (UI cut) coloured by CSS tokens, so it follows the Day/Night toggle automatically.
The wordmark in the logo SVGs is live text in Sora ExtraBold; outline it before sending files to print.

## Wordmark

`WANDERERS` in **Sora ExtraBold 800**, all caps, tracking **−0.025em**. Sora's capitals are naturally compact: relative to word width the uppercase is about 11% lower than the earlier Space Grotesk wordmark, with no scaling or distortion.

Never stretch or squash the letters, never set it thin, extended or wide-tracked.

## Spacing and size

- Clear space on every side = 1/4 of the emblem height.
- Gap between emblem and wordmark = about 0.28 × the emblem height (9 px with the 32 px navigation emblem).
- Wordmark cap height ≈ 0.42 × the emblem height.
- Minimum size: emblem 16 px (favicon cut), horizontal logo 140 px wide.

## Do not

Rotate, recolour outside the palette, add glows or gradients, put it on busy imagery without a solid backing, close the field circle, add extra orbits (it becomes an atom icon), or reorder the epochs (hollow = past, solid with reticle = now).

## Colour

| Token | Day Observatory | Night Observatory |
|---|---|---|
| Background | `#F6F8FB` | `#0B1422` |
| Surface | `#FFFFFF` | `#152438` |
| Text | `#172B45` | `#F1F5FA` |
| Secondary text | `#52677D` | `#B5C9DE` |
| Accent | `#2864C5` | `#8AB6EF` |
| Secondary accent | `#4D8796` | `#7FB8C4` |
| Border | `#DCE4ED` | `#293B50` |
| Observation viewer | `#081321` | `#050B14` |

Tokens live in `app/brand.css`. Scientific imagery always sits on the viewer colour and is never inverted or recoloured when the theme changes.

## Type

| Role | Face |
|---|---|
| Wordmark | Sora 800 |
| Hero headlines | Manrope 800 |
| Section headings | Manrope 700 |
| Navigation, UI | Inter 500–600 |
| Body | Inter 400 |
| Coordinates, wavelengths, dates, measurements | IBM Plex Mono 400–500 |

All four families are SIL Open Font License, loaded from Google Fonts.

## Provenance labels

Every visual says what it is: **Real data** / **Measured** (pipeline output), **AI · Claude** (written interpretation), **Illustration** (explanatory diagram, not data).
