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
  photometry: {flux, err} | null      // aperture at the target position (ring if PM known, else center); null if saturated
}
detectors["Dn"][j] += { photometry: {flux, err} | null, wavelength_um: [min, max] }
photometry_unit: string               // top level, e.g. "mJy (aperture r=2.5 px, sky annulus 4-7 px)"
gaia: { release: "Gaia DR3", epoch_mjd: 57388.5,
        stars: [{source_id, ra, dec, pmra, pmdec, gmag, xy: [[x, y], ...one per frame]}] } | null
notes: [string]                       // e.g. "Gaia query failed; overlay off", "2 images failed after retries"
quality: { n_images_used, n_failed, cache_age_s }   // the old top-level n_images_used and n_failed stay too
```

- `source_id` is a string (Gaia ids exceed the JavaScript safe integer range).
- `gaia.stars[k].xy[i]` is the star moved by its proper motion to `frames[i].mjd_mean`, in PNG pixels.
- `gaia` lists at most 150 stars (G < 19, brightest first) that fall inside the view in at least one frame.

## Differences from the contract

- `centroid` for a **saturated** frame: the contract says null. The backend gives the centroid of the unsaturated
  pixels around the core instead, and adds `saturated: true` inside the object. Reason: very bright movers such as
  Barnard's Star are saturated in every frame, but their position stays measurable from the star's wings; a null
  would hide the motion that the tool exists to show. The UI can draw these points hollow. `centroid` is null only
  when no source stands out (peak below 5 sigma of the frame noise).

## Example (Barnard's Star, trimmed to 2 frames)

The existing fields below are from a real response. The new fields are filled in by the implementation and this
example is replaced with a live response after the implementation lands.

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
    {"label": "2025-08-15 to 09-05", "mjd_mean": 60913.5541, "date": "2025-08-26", "n_images": 12,
     "ring": {"x": 24.45, "y": 25.09}, "saturated": true, "png": "data:image/png;base64,iVBORw0KGgo..."},
    {"label": "2025-09-30 to 10-01", "mjd_mean": 60948.9258, "date": "2025-09-30", "n_images": 10,
     "ring": {"x": 24.47, "y": 24.92}, "saturated": true, "png": "data:image/png;base64,iVBORw0KGgo..."}
  ],
  "detectors": {"D1": [{"group_index": 0, "n_images": 2, "png": "data:image/png;base64,iVBORw0KGgo..."}]},
  "difference": {"png": "data:image/png;base64,iVBORw0KGgo...", "from": "2025-08-15 to 09-05", "to": "2026-09-22"},
  "n_images_used": 56,
  "n_failed": 0,
  "cached": false
}
```
