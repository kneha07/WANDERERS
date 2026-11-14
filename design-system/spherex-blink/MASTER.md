# Design system: WANDERERS Explore (SPHEREx Blink)

Direction: **mission control**. The page looks like an instrument console. It is inspired by NASA mission
displays, but it is **not NASA-branded**.

## Brand rule

- Never use the NASA insignia ("meatball"), the NASA logotype ("worm") or the NASA seal.
  NASA policy does not let a third party imply NASA endorsement.
- Say where the data comes from, in the footer, on every screen:
  "Data: NASA/JPL-Caltech/IPAC SPHEREx (IRSA), ESA Gaia DR3, CDS. Not an official NASA product."
- The product name is "WANDERERS · Explore". Do not call it a NASA tool.

## Colours

Every colour is a CSS variable in `web/src/index.css`. Components use the variables only, never a raw hex.

| Role | Hex | CSS variable | Use |
|---|---|---|---|
| Page | `#0B1426` | `--page` | Page background |
| Panel | `#101C33` | `--panel` | Instrument panels, top bar |
| Raised | `#1A2A47` | `--raised` | Buttons, inputs, table header, selected tab |
| Line | `#2A3B5C` | `--line` | 1px panel borders, dividers, chart grid |
| Text | `#E8EEF8` | `--text` | Body text |
| Muted | `#9AA8C2` | `--muted` | Labels, help text, axis labels (7.1:1 on the panel) |
| Action | `#D42B14` | `--action` | **Primary buttons only**, with white text. It is the NASA red `#FC3D21`, made darker so that white text has 4.9:1. |
| Action hover | `#B52310` | `--action-hover` | Hover of a primary button |
| Data blue | `#7CC4FF` | `--data` | Links, focus ring, selection, current frame, flipbook field on the sky map |
| Amber | `#FFB547` | `--amber` | "Where to look" ring, candidates, predicted track |
| Green | `#4FD1A5` | `--known` | "Known in catalog": Gaia circles, a candidate that matches a Gaia star |
| Error | `#FF7A7A` | `--error` | Errors and failed states, always with an icon and text |

- Never show meaning by colour alone. Errors have an icon and text. The ring, the Gaia circles and the candidates
  differ in shape too (thick ring, thin circle, numbered square), and the legend names them.
- The sky image and the difference image stay grayscale. Never tint the science pixels.
- `#FC3D21` itself appears only as a thin accent line (for example the active tab underline), never under text.

## Typography

- **UI:** Public Sans (the US Web Design System font), from Google Fonts with `display=swap`.
  Fallback: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`. Body 15px, line-height 1.5.
- **Numbers:** IBM Plex Mono, from Google Fonts, fallback `ui-monospace, "Cascadia Mono", Consolas, monospace`.
  Use it with `font-variant-numeric: tabular-nums` for every number, coordinate, date, MJD and pixel value,
  so that values do not change width.
- **Instrument labels:** panel titles are small (12px), uppercase, letter-spaced (0.08em), muted, 600 weight.

## Spacing and shape

- 8px grid: 4, 8, 16, 24, 32, 48 px. Align panel edges to the grid.
- Panels: 1px `--line` border, 4px radius, no shadow. Controls: 4px radius.
- Desktop (1024px and wider): top bar, then the flipbook column and a 380px right rail with tabs
  (Task, Data, Field guide), then a grid of instrument panels, then the frames table.
- Phone (below 1024px): one column in the same order. 375px must work with no horizontal scroll.
- Flipbook: square, `aspect-ratio: 1`, max 640px, `image-rendering: pixelated`.

## Interaction

- Tap targets 44 × 44 px or more, with 8px or more between them.
- Visible focus ring: `2px solid var(--data)`, offset 2px. Never remove the outline.
- `cursor: pointer` on everything clickable. Hover transitions 150 to 200 ms, colour and opacity only.
- Icons: inline SVG or text glyphs with an `aria-label`. No emoji as icons.
- `prefers-reduced-motion`: no autoplay, no transitions, the sky map jumps instead of a zoom animation,
  and the sky dome shows a static dot.
- One layer at most (the tutorial dialog). Esc, the close button, a backdrop click and browser Back close it.
  Focus returns to the control that opened it.
- One toast at a time. A new toast replaces the old one. No `confirm()` and no `alert()`.
- The URL owns the place: `?q=&fov=&view=&det=&c=`. A new search pushes a history entry. A toggle or a new
  candidate replaces it. Back returns to the previous target in one press.
- Loading: the search button shows its busy state in less than 100 ms. The loading text appears after 300 ms and
  stays at least 500 ms. A skeleton holds the size of the image box. Elapsed seconds count up. After 180 s the
  request stops and an error with Retry shows.
- Each panel has an error boundary and its own loading, empty and error states. A failure of the sky map,
  Gaia or the location never breaks the flipbook.
- Responsive checks at 375, 768, 1024 and 1440 px.

## Pre-delivery checklist

- [ ] Text contrast 4.5:1 or more (body text 7:1 or more on the panel)
- [ ] Visible focus on every control; full keyboard use
- [ ] No emoji icons; every icon button has a label
- [ ] Tap targets 44px or more
- [ ] CLS below 0.1 (image box reserved, numbers tabular)
- [ ] Reduced motion respected
- [ ] 375 / 768 / 1024 / 1440 px with no horizontal scroll
- [ ] No NASA insignia, logotype or seal; the footer says "Not an official NASA product."
- [ ] No raw hex colour in a component; every colour is a token
- [ ] No meaning by colour alone (icon, shape or text with every colour)
