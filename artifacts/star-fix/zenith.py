import sys, numpy as np, warnings; warnings.filterwarnings('ignore')
from PIL import Image, ImageFilter
from astropy.wcs import WCS
from astropy.io.fits import Header
D = np.pi/180
def vec(ra, de): ra, de = ra*D, de*D; return np.array([np.cos(de)*np.cos(ra), np.cos(de)*np.sin(ra), np.sin(de)])
def radec(v): v = v/np.linalg.norm(v); return (np.arctan2(v[1], v[0])/D) % 360, np.arcsin(v[2])/D
P = {}
for i in '1234':
    f = f'{sys.argv[1]}/1 ({i}).jpeg'
    g = Image.open(f).convert('L'); W, H = g.size
    small = np.asarray(g.filter(ImageFilter.MedianFilter(15)).resize((W//32, H//32), Image.BOX), float)
    lin = (small/255)**2.2                                  # undo JPEG gamma
    yy, xx = np.mgrid[0:small.shape[0], 0:small.shape[1]]
    A = np.c_[np.ones(xx.size), xx.ravel(), yy.ravel()]
    out = {}
    for tag, img in (('jpeg', small), ('linear', lin)):
        a, bx, by = np.linalg.lstsq(A, img.ravel(), rcond=None)[0]
        out[tag] = (bx, by)
    bx, by = out['jpeg']
    tilt = np.degrees(np.arctan2(bx, by))                   # 0 = glow straight down the image
    w = WCS(Header.fromstring(open(f'out/wcs_{i}.hdr').read()))
    def sky(x, y, w=w): c = w.pixel_to_world(x, y); return vec(c.ra.deg, c.dec.deg)
    top, bot = small[:small.shape[0]//6].mean(), small[-small.shape[0]//6:].mean()
    P[i] = dict(W=W, H=H, tilt=tilt, sky=sky, ratio=bot/top)
    print(f'photo {i}: glow points {tilt:+.0f} deg from image-down, bottom/top glow ratio {bot/top:.1f} (jpeg) {(bot/top)**2.2:.1f} (linear)')

def curve(p, tilt_deg, n=181):
    """zenith candidates: walk from the image centre along 'up' (opposite the glow) for theta = 0..90 deg"""
    cx, cy = p['W']/2, p['H']/2; t = np.radians(tilt_deg)
    ux, uy = -np.sin(t), -np.cos(t)                         # up direction in pixels
    c = p['sky'](cx, cy); u = p['sky'](cx + 40*ux, cy + 40*uy) - c
    u -= c*np.dot(u, c); u /= np.linalg.norm(u)
    th = np.radians(np.linspace(0, 90, n))
    return np.outer(np.cos(th), c) + np.outer(np.sin(th), u), np.degrees(th)

def cross(a, b, ta, tb):
    za, tha = curve(P[a], ta); zb, thb = curve(P[b], tb)
    d = np.degrees(np.arccos(np.clip(za @ zb.T, -1, 1))); k = np.unravel_index(np.nanargmin(d), d.shape)
    z = za[k[0]] + zb[k[1]]; ra, de = radec(z)
    return ra, de, d[k], 90-tha[k[0]], 90-thb[k[1]]

rng = np.random.default_rng(1)
for a, b in (('2', '3'), ('1', '4')):
    ra, de, gap, alta, altb = cross(a, b, P[a]['tilt'], P[b]['tilt'])
    print(f'\nsession photos {a}+{b}: zenith RA {ra:.1f} deg ({ra/15:.2f} h)  Dec {de:.1f}  miss {gap:.1f} deg  centre alt {alta:.0f} / {altb:.0f}')
    s = np.array([cross(a, b, P[a]['tilt'] + rng.normal(0, 10), P[b]['tilt'] + rng.normal(0, 10))[:2] for _ in range(300)])
    good = s[np.isfinite(s[:, 1])]
    print(f'  with +-10 deg glow-direction error: Dec median {np.median(good[:,1]):.1f}, 68% range {np.percentile(good[:,1],16):.1f} .. {np.percentile(good[:,1],84):.1f}; '
          f'LST median {np.median(good[:,0])/15:.2f} h, 68% {np.percentile(good[:,0],16)/15:.2f} .. {np.percentile(good[:,0],84)/15:.2f} h')
    ra0, de0, *_ = cross(a, b, 0, 0)
    print(f'  if "up" = image top exactly (phone auto-rotate, no glow): RA {ra0/15:.2f} h  Dec {de0:.1f}')
