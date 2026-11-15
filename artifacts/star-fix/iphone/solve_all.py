# Plate-solve every HEIC, fit a TAN sky map in display-pixel coordinates, store it with the metadata the app gets.
import sys, glob, io, os, json, math, struct, warnings; warnings.filterwarnings('ignore')
import numpy as np; np.math = math
import pillow_heif, exifread, tetra3
from PIL import Image
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.wcs.utils import fit_wcs_from_points
pillow_heif.register_heif_opener()
exec(open('meta.py').read().split('key = {}')[0].split('pillow_heif.register_heif_opener()')[1])   # apple_makernote()
t3 = tetra3.Tetra3(); out = {}
for f in sorted(glob.glob(sys.argv[1] + '/*.heic')):
    name = os.path.basename(f)[:-9]; im = Image.open(f); raw = im.info.get('exif', b'')
    t = exifread.process_file(io.BytesIO(raw[6:] if raw[:4] == b'Exif' else raw), details=False)
    g = lambda k: str(t.get(k, '')) or None
    hd = t.get('GPS GPSImgDirection'); heading = float(hd.values[0].num) / hd.values[0].den if hd else None
    rec = dict(time=g('EXIF DateTimeOriginal'), offset=g('EXIF OffsetTimeOriginal'), orient=g('Image Orientation'),
               heading=heading, accel=apple_makernote(raw).get(8), f35=g('EXIF FocalLengthIn35mmFilm'))
    gray = im.convert('L'); W0, H0 = gray.size; k = 2048 / max(W0, H0)
    gray = gray.resize((round(W0*k), round(H0*k)), Image.LANCZOS); W, H = gray.size
    rec.update(W=W, H=H, solved=False)
    for frac in (0.5, 0.35, 1.0):
        cw, ch = int(W*frac), int(H*frac); ox, oy = (W-cw)//2, (H-ch)//2
        crop = gray.crop((ox, oy, ox+cw, oy+ch))
        for sigma in (3, 2):
            cents = tetra3.get_centroids_from_image(crop, sigma=sigma, max_area=300, min_area=2)
            if len(cents) < 6: continue
            r = t3.solve_from_centroids(cents[:60], (ch, cw), solve_timeout=10000, return_matches=True)
            if r.get('RA') is not None: break
        if r.get('RA') is not None: break
    if r.get('RA') is not None and r['Matches'] >= 8:
        mc = np.array(r['matched_centroids']); ms = np.array(r['matched_stars'])
        wcs = fit_wcs_from_points((mc[:,1]+ox, mc[:,0]+oy), SkyCoord(ms[:,0]*u.deg, ms[:,1]*u.deg), projection='TAN')
        for _ in range(3):   # put the TAN tangent point on the lens axis (image centre), so the map is a pinhole about the centre
            wcs = fit_wcs_from_points((mc[:,1]+ox, mc[:,0]+oy), SkyCoord(ms[:,0]*u.deg, ms[:,1]*u.deg), projection='TAN', proj_point=wcs.pixel_to_world(W/2, H/2))
        open(f'heic/{name}.hdr', 'w').write(wcs.to_header_string())
        c = wcs.pixel_to_world(W/2, H/2)
        rec.update(solved=True, crop=frac, stars=len(cents), matches=int(r['Matches']), prob=float(r['Prob']),
                   ra=round(float(c.ra.deg), 2), dec=round(float(c.dec.deg), 2))
    else:
        rec.update(stars=len(cents) if 'cents' in dir() else 0)
    out[name] = rec
    print(name, rec['orient'], {k: rec.get(k) for k in ('solved', 'crop', 'stars', 'matches', 'prob', 'ra', 'dec')}, flush=True)
json.dump(out, open('heic/solves.json', 'w'), indent=1)
