import sys, numpy as np
from PIL import Image, ImageFilter
from astropy.wcs import WCS
from astropy.io.fits import Header
D = np.pi/180
def vec(ra, de): ra, de = ra*D, de*D; return np.array([np.cos(de)*np.cos(ra), np.cos(de)*np.sin(ra), np.sin(de)])
P = {}
for i in '1234':
    g = Image.open(f'{sys.argv[1]}/1 ({i}).jpeg').convert('L'); W, H = g.size
    s = np.asarray(g.filter(ImageFilter.MedianFilter(15)).resize((W//32, H//32), Image.BOX), float)
    yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]]
    _, bx, by = np.linalg.lstsq(np.c_[np.ones(xx.size), xx.ravel(), yy.ravel()], s.ravel(), rcond=None)[0]
    w = WCS(Header.fromstring(open(f'out/wcs_{i}.hdr').read()))
    cx, cy = W/2, H/2; cc = w.pixel_to_world(cx, cy); c = vec(cc.ra.deg, cc.dec.deg)
    P[i] = dict(w=w, cx=cx, cy=cy, c=c, up_obs=np.degrees(np.arctan2(-bx, -by)) * -1, H=H)   # obs "up" angle, 0 = image top, + = toward right
    bm = w.pixel_to_world(cx, H - 1); P[i]['b'] = vec(bm.ra.deg, bm.dec.deg)
    P[i]['up_obs'] = -np.degrees(np.arctan2(bx, by))

def up_pred(p, z):
    """angle (deg, 0 = image top, + = right) of the direction from photo centre toward zenith z"""
    c = p['c']; t = z - c*np.dot(c, z); t /= np.linalg.norm(t)
    q = np.cos(1*D)*c + np.sin(1*D)*t
    ra, de = np.arctan2(q[1], q[0])/D % 360, np.arcsin(q[2])/D
    x, y = p['w'].all_world2pix([[ra, de]], 0)[0]
    return np.degrees(np.arctan2(x - p['cx'], -(y - p['cy'])))

