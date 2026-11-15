# Longitude from the measured LST, then a joint fit of (lat, lon) against the sky-glow "up" in all four photos.
import sys, numpy as np, warnings; warnings.filterwarnings('ignore')
from PIL import Image, ImageFilter
from astropy.wcs import WCS
from astropy.io.fits import Header
from astropy.time import Time
import astropy.units as u
D = np.pi/180
utc = Time('2026-06-15T09:00:00')                      # 19:00 at GMT+10
gmst = utc.sidereal_time('mean', longitude=0*u.deg).hour
print(f'GMST at {utc.iso} UTC = {gmst:.2f} h')
for name, lst, lo, hi in (('photos 2+3', 10.97, 10.51, 11.43), ('photos 1+4', 9.97, 9.66, 10.50), ('2+3, up=image top', 11.43, None, None)):
    lon = lambda h: ((h - gmst) * 15 + 180) % 360 - 180
    rng = f' (68 %: {lon(lo):.0f} .. {lon(hi):.0f})' if lo else ''
    print(f'  {name}: LST {lst} h -> longitude {lon(lst):.0f} E{rng}')

def vec(ra, de): ra, de = ra*D, de*D; return np.array([np.cos(de)*np.cos(ra), np.cos(de)*np.sin(ra), np.sin(de)])
P = {}
for i in '1234':
    g = Image.open(f'{sys.argv[1]}/1 ({i}).jpeg').convert('L'); W, H = g.size
    s = np.asarray(g.filter(ImageFilter.MedianFilter(15)).resize((W//32, H//32), Image.BOX), float)
    yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]]
    _, bx, by = np.linalg.lstsq(np.c_[np.ones(xx.size), xx.ravel(), yy.ravel()], s.ravel(), rcond=None)[0]
    w = WCS(Header.fromstring(open(f'out/wcs_{i}.hdr').read()))
    cx, cy = W/2, H/2; cc = w.pixel_to_world(cx, cy); c = vec(cc.ra.deg, cc.dec.deg)
    P[i] = dict(w=w, cx=cx, cy=cy, c=c, H=H)
    bm = w.pixel_to_world(cx, H - 1); P[i]['b'] = vec(bm.ra.deg, bm.dec.deg)
    P[i]['up_obs'] = -np.degrees(np.arctan2(bx, by))   # observed up angle from the glow, 0 = image top, + = right

def up_pred(p, z):
    """angle (deg, 0 = image top, + = right) of the direction from photo centre toward zenith z"""
    c = p['c']; t = z - c*np.dot(c, z); t /= np.linalg.norm(t)
    q = np.cos(1*D)*c + np.sin(1*D)*t
    ra, de = np.arctan2(q[1], q[0])/D % 360, np.arcsin(q[2])/D
    x, y = p['w'].all_world2pix([[ra, de]], 0)[0]
    return np.degrees(np.arctan2(x - p['cx'], -(y - p['cy'])))

lats = np.arange(-10, -66, -1.0); lons = np.arange(90, 181, 1.0)
best = []
for sig_up, label in ((15, 'glow up (+-15 deg)'), (None, 'image top up (+-15 deg)')):
    S = np.full((lats.size, lons.size), np.inf)
    for a, lat in enumerate(lats):
        for b, lon in enumerate(lons):
            lst = (gmst*15 + lon) % 360; z = vec(lst, lat); cost = 0
            for p in P.values():
                alt_c = 90 - np.degrees(np.arccos(np.dot(p['c'], z))); alt_b = 90 - np.degrees(np.arccos(np.dot(p['b'], z)))
                if alt_b < -5 or alt_c < 10: cost = np.inf; break          # the whole photo shows sky
                obs = p['up_obs'] if sig_up else 0.0
                d = (up_pred(p, z) - obs + 180) % 360 - 180
                cost += (d / 15) ** 2
            S[a, b] = cost
    k = np.unravel_index(np.argmin(S), S.shape)
    zone = (lons >= 141) & (lons <= 154)
    kz = np.unravel_index(np.argmin(S[:, zone]), S[:, zone].shape)
    ok = S <= S[k] + 2.3                                   # ~68 % region for 2 parameters
    print(f'\n{label}: best lat {lats[k[0]]:.0f}, lon {lons[k[1]]:.0f} E, cost {S[k]:.1f}; '
          f'68 % lat {lats[ok.any(1)].max():.0f}..{lats[ok.any(1)].min():.0f}, lon {lons[ok.any(0)].min():.0f}..{lons[ok.any(0)].max():.0f}')
    print(f'  best inside the GMT+10 land band (141-154 E): lat {lats[kz[0]]:.0f}, lon {lons[zone][kz[1]]:.0f} E, cost {S[:, zone][kz]:.1f}')
    for i, p in P.items():
        lat, lon = lats[k[0]], lons[k[1]]; z = vec((gmst*15 + lon) % 360, lat)
        print(f'   photo {i}: glow up {p["up_obs"]:+.0f}, predicted up {up_pred(p, z):+.0f}, centre alt {90-np.degrees(np.arccos(np.dot(p["c"], z))):.0f}')
