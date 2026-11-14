# Live explorer API contract: `GET /api/frames`

Status: contract for the mission-control redesign (lane 1 backend, lane 2 frontend). The backend owns this file.
If the backend must differ from the contract, the difference is written in the "Differences" section below.

## Request

`GET /api/frames?q=<name or RA/Dec>&fov=5&per_group=12&det=`

| Parameter | Meaning |
|---|---|
| `q` | Name, decimal degrees (`269.45 4.69`) or sexagesimal (`17h57m48.5s +04d41m36s`) |
| `fov` | Field of view, arcmin, 2 to 15 (default 5) |
| `per_group` | Images per survey epoch, 1 to 30 (default 12) |
| `det` | Empty: all detectors stacked. `D1` to `D6`: one detector only |

Errors: HTTP 400 (bad input), 404 (no images), 502 (IRSA failed, or the live server is down behind `server.js`),
all with `{"detail": "..."}`.

## Response

Existing fields (unchanged):

| Field | Type | Meaning |
|---|---|---|
| `query`, `name` | string, string or null | What was asked; resolved name (null for RA/Dec) |
| `center` | `{ra, dec}` | Center of the view, degrees (the 2026.0 position when the proper motion is known) |
| `pm` | `{pmra, pmdec}` or null | Proper motion, mas/yr (pmra includes cos Dec) |
| `det` | string or null | The detector filter used |
| `fov_arcmin`, `pixel_arcsec`, `size_px` | numbers | View size; the PNGs are `size_px` x `size_px`, north up, east left |
| `frames[i]` | object | One stacked frame per survey epoch, in time order |
| `frames[i].label` | string | Date range of the epoch, unique, e.g. `"2025-08-15 to 09-05"` |
| `frames[i].mjd_mean`, `.date` | number, string | Mean epoch of the images used |
| `frames[i].n_images` | number | Images stacked |
| `frames[i].ring` | `{x, y}` or null | Predicted target position, PNG pixels, origin top-left (null without proper motion) |
| `frames[i].png` | string | `data:image/png;base64,...` |
| `detectors["Dn"][j]` | `{group_index, n_images, png}` | Per-detector frames; `group_index` points into `frames` |
| `difference` | `{png, from, to}` or null | Last frame minus first frame (null with fewer than 2 frames) |
| `n_images_used`, `n_failed`, `cached` | number, number, bool | Totals and cache status |

Additions:

```
frames[i] += {
  wavelength_um: [min, max],          // over the images used in this frame (detector band edges)
  detectors: ["D1", ...],             // detectors present in this frame
  saturated: bool,                    // the target's core has no data (saturated) in this frame
  centroid: {x, y, ex, ey} | null,    // PNG pixels, origin top-left, like ring; null if < 5 sigma (see Differences)
  photometry: {flux, err} | null,     // aperture at the target position (ring if PM known, else center); null if saturated
  rgb_png: string | null              // false-colour PNG, same size and orientation as png; null with det
}
detectors["Dn"][j] += { photometry: {flux, err} | null, wavelength_um: [min, max] }
photometry_unit: string               // top level, e.g. "mJy (aperture r=2.5 px, sky annulus 4-7 px)"
gaia: { release: "Gaia DR3", epoch_mjd: 57388.5,
        stars: [{source_id, ra, dec, pmra, pmdec, gmag, xy: [[x, y], ...one per frame]}] } | null
rgb: { channels: {blue: ["D1", "D2"], green: ["D3", "D4"], red: ["D5", "D6"]},
       wavelength_um: {blue: [min, max], green: [min, max], red: [min, max]},
       method: "Lupton asinh RGB (astropy)" } | null      // null with det
notes: [string]                       // e.g. "Gaia query failed; overlay off", "2 images failed after retries"
quality: { n_images_used, n_failed, cache_age_s }   // the old top-level n_images_used and n_failed stay too
```

- `source_id` is a string (Gaia ids exceed the JavaScript safe integer range).
- `gaia.stars[k].xy[i]` is the star moved by its proper motion to `frames[i].mjd_mean`, in PNG pixels.
- `gaia` lists at most 150 stars (G < 19, brightest first) that fall inside the view in at least one frame.
  The backend adds `gaia` on each request from a cached Gaia field, so after a failed Gaia query the next request
  tries again (`gaia` is null with a note until then).
- `centroid`: a round Gaussian is fitted per detector stack, then the frame gets the mean over its detectors.
  The fit is not pulled toward the ring, so `centroid - ring` is a real residual. `ex`, `ey` are 1-sigma, PNG
  pixels: the larger of the propagated fit errors and the detector scatter. Each fit has a floor of 0.1 px
  (0.3 px when the core has no data). Measured on 2026-11-14: the Barnard's Star, Kapteyn's Star and RW Aur
  centroids sit within 0.33 px of the ring on each axis.
- `photometry`: mJy in an r = 2.5 px aperture minus the median of the 4-7 px annulus, without aperture correction.
  A frame mixes detectors (wavelengths), so for a light curve compare `detectors["Dn"][j].photometry` of one
  detector between epochs.
- `rgb_png`: blue = mean of the D1 and D2 stacks (0.75-1.65 um), green = D3 and D4 (1.63-3.85 um), red = D5 and D6
  (3.81-5.01 um). All frames share one black level (the median of the channel pixels) and one asinh stretch (Q = 3,
  full scale at the 99.7th percentile), so the colours can be compared between frames. If a frame has no images for
  a channel, that channel is the mean of the other two and `notes` says so. Saturated cores are white and
  no-data pixels black, like `png`. Ordinary stars look blue-white; very red objects (cold brown dwarfs, dusty
  young stars such as RW Aur) look red. A frame RGB PNG is about 2 to 5 kB.

## Differences from the contract

- `centroid` for a **saturated** frame: the contract says null. The backend fits the unsaturated pixels around the
  core instead, and adds `saturated: true` inside the object. Reason: very bright movers such as
  Barnard's Star are saturated in every frame, but their position stays measurable from the star's wings; a null
  would hide the motion that the tool exists to show. The UI can draw these points hollow. `centroid` is null only
  when no source stands out (peak below 5 sigma of the frame noise).
- `photometry` is also null when the target's core has no data in **at least one detector** of the frame, even if
  `saturated` is false. (`saturated` looks at the all-detector stack, where the other detectors fill such a core.)
  Reason: the stack would then sum different detectors in the core and in the wings, so the flux would be wrong.
  `detectors["Dn"][j].photometry` stays where that detector has data. Example: RW Aur, survey 1: D1 and D3 have
  photometry, the frame has none. RW Aur is saturated in all detectors in surveys 2 and 3, so it has no flux there.

## Example (Barnard's Star, trimmed to 2 frames)

A real response (2026-11-14), trimmed to 2 of 6 frames, 2 detectors and 2 Gaia stars. PNG strings are shortened.

```json
{
  "query": "Barnard's Star",
  "name": "Barnard's star",
  "center": {"ra": 269.446268, "dec": 4.768204},
  "pm": {"pmra": -801.551, "pmdec": 10362.394},
  "det": null,
  "fov_arcmin": 5.0,
  "pixel_arcsec": 6.15,
  "size_px": 49,
  "frames": [
    {"label": "2025-08-15 to 09-05", "mjd_mean": 60913.5541, "date": "2025-08-26", "n_images": 12, "ring": {"x": 24.45, "y": 25.09}, "detectors": ["D1", "D2", "D3", "D4", "D5", "D6"], "wavelength_um": [0.746, 5.01], "centroid": {"x": 24.24, "ex": 0.123, "y": 24.993, "ey": 0.124, "saturated": true}, "photometry": null, "saturated": true, "png": "data:image/png;base64,iVBORw0KGgo...", "rgb_png": "data:image/png;base64,iVBORw0KGgo..."},
    {"label": "2025-09-30 to 10-01", "mjd_mean": 60948.9258, "date": "2025-09-30", "n_images": 10, "ring": {"x": 24.47, "y": 24.92}, "detectors": ["D1", "D4"], "wavelength_um": [0.746, 3.847], "centroid": {"x": 24.803, "ex": 0.214, "y": 24.976, "ey": 0.213, "saturated": true}, "photometry": null, "saturated": true, "png": "data:image/png;base64,iVBORw0KGgo...", "rgb_png": "data:image/png;base64,iVBORw0KGgo..."}
  ],
  "detectors": {
    "D1": [{"group_index": 0, "n_images": 2, "wavelength_um": [0.746, 1.117], "photometry": null, "png": "data:image/png;base64,iVBORw0KGgo..."}, {"group_index": 1, "n_images": 5, "wavelength_um": [0.746, 1.117], "photometry": null, "png": "data:image/png;base64,iVBORw0KGgo..."}],
    "D4": [{"group_index": 0, "n_images": 2, "wavelength_um": [2.403, 3.847], "photometry": null, "png": "data:image/png;base64,iVBORw0KGgo..."}, {"group_index": 1, "n_images": 5, "wavelength_um": [2.403, 3.847], "photometry": null, "png": "data:image/png;base64,iVBORw0KGgo..."}]
  },
  "difference": {"png": "data:image/png;base64,iVBORw0KGgo...", "from": "2025-08-15 to 09-05", "to": "2026-09-22"},
  "rgb": {"channels": {"blue": ["D1", "D2"], "green": ["D3", "D4"], "red": ["D5", "D6"]}, "wavelength_um": {"blue": [0.746, 1.65], "green": [1.63, 3.847], "red": [3.811, 5.01]}, "method": "Lupton asinh RGB (astropy)"},
  "photometry_unit": "mJy (aperture r = 2.5 px, sky from the 4-7 px annulus)",
  "gaia": {"release": "Gaia DR3", "epoch_mjd": 57388.5, "stars": [
    {"source_id": "4472832130942575872", "ra": 269.44850252543836, "dec": 4.739420051112412, "pmra": -801.5509783684709, "pmdec": 10362.394206546573, "gmag": 8.1939745, "xy": [[24.45, 25.09], [24.47, 24.92]]},
    {"source_id": "4472836292758713216", "ra": 269.443871611535, "dec": 4.796291416021129, "pmra": -6.158672306279798, "pmdec": 0.5128588102925811, "gmag": 11.862574, "xy": [[25.91, 8.06], [25.91, 8.06]]}
  ]},
  "notes": ["Colour image: 3 of 6 frames lack the detectors of one or two channels; there a missing channel shows the mean of the other channels, so the colours are less true.", "The target is saturated in 6 of 6 frames: centroids there come from the wings.", "No photometry in 6 of 6 frames: in at least one detector the aperture has no data (saturated core or detector edge). Per-detector photometry is given where it exists."],
  "n_images_used": 56,
  "n_failed": 0,
  "cached": false,
  "quality": {"n_images_used": 56, "n_failed": 0, "cache_age_s": 0}
}
```

An unsaturated frame and detector entry (WISE 0855, `det=D6`, so `rgb_png` is null):

```json
{"label": "2025-11-10 to 11-14", "saturated": false, "centroid": {"x": 24.562, "ex": 0.122, "y": 24.479, "ey": 0.122},
 "photometry": {"flux": 0.5712, "err": 0.0571}, "rgb_png": null}
{"group_index": 1, "n_images": 12, "wavelength_um": [4.412, 5.01], "photometry": {"flux": 0.5712, "err": 0.0571}, "png": "data:image/png;base64,iVBORw0KGgo..."}
```
