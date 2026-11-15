import sys, glob, math, json, warnings
warnings.filterwarnings('ignore')
import numpy as np; np.math = math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import tetra3
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.wcs.utils import fit_wcs_from_points

NAMED = {'Canopus':(95.988,-52.696),'Miaplacidus':(138.300,-69.717),'Avior':(125.628,-59.509),'Aspidiske':(139.273,-59.275),
 'theta Car':(160.739,-64.394),'Acrux':(186.650,-63.099),'Mimosa':(191.930,-59.689),'Gacrux':(187.791,-57.113),'delta Cru':(183.786,-58.749),
 'alpha Cen':(219.902,-60.834),'Hadar':(210.956,-60.373),'Suhail':(136.999,-43.433),'Regor':(122.383,-47.337),'delta Vel':(131.176,-54.708),
 'kappa Vel':(140.528,-55.011),'Naos':(120.896,-40.003),'Achernar':(24.429,-57.237),'alpha Mus':(189.296,-69.136),'beta Mus':(191.570,-68.108),
 'alpha TrA':(252.166,-69.028),'gamma Cen':(190.379,-48.960),'Sirius':(101.287,-16.716),'eta Car neb':(161.265,-59.685),
 'LMC':(80.89,-69.76),'SMC':(13.19,-72.83),'S. CEL. POLE':(0.0,-90.0)}
t3 = tetra3.Tetra3()
res = {}
for f in sorted(glob.glob(sys.argv[1] + '/*.jpeg')):
    name = f[-10:]
    rgb = Image.open(f).convert('RGB'); full = rgb.convert('L'); W, H = full.size
    for frac in (0.5, 1.0):
        cw, ch = int(W*frac), int(H*frac); ox, oy = (W-cw)//2, (H-ch)//2
        img = full.crop((ox, oy, ox+cw, oy+ch))
        cents = tetra3.get_centroids_from_image(img, sigma=3, max_area=300, min_area=2)
        r = t3.solve_from_centroids(cents[:60], (ch, cw), solve_timeout=15000, return_matches=True, distortion=None)
        if r.get('RA') is not None: break
    mc = np.array(r['matched_centroids']); ms = np.array(r['matched_stars'])
    xy = (mc[:,1] + ox, mc[:,0] + oy)
    sky = SkyCoord(ms[:,0]*u.deg, ms[:,1]*u.deg)
    wcs = fit_wcs_from_points(xy, sky, projection='TAN', sip_degree=None)
    px, py = wcs.world_to_pixel(sky); resid = np.hypot(px-xy[0], py-xy[1])
    scale = abs(wcs.proj_plane_pixel_scales()[0].to(u.deg).value)
    def at(x, y):
        c = wcs.pixel_to_world(x, y); return round(float(c.ra.deg),2), round(float(c.dec.deg),2)
    # sky glow: faint-sky level (20th percentile after star removal) in edge bands
    g = np.asarray(full.filter(ImageFilter.MedianFilter(9)), float)
    band = lambda a: float(np.percentile(a, 20))
    glow = {'top': band(g[:H//8]), 'bottom': band(g[-H//8:]), 'left': band(g[:, :W//8]), 'right': band(g[:, -W//8:])}
    res[name] = dict(W=W, H=H, crop=frac, matches=int(r['Matches']), prob=float(r['Prob']), resid_px=round(float(np.median(resid)),1),
        scale_arcmin_px=round(scale*60,3), center=at(W/2,H/2), top_mid=at(W/2,0), bottom_mid=at(W/2,H-1), glow=glow,
        hip=[int(c) for c in r['matched_catID']][:60])
    # annotate
    d = ImageDraw.Draw(rgb)
    try: font = ImageFont.truetype('arial.ttf', 34)
    except Exception: font = ImageFont.load_default()
    for (x, y) in zip(*xy): d.ellipse((x-14, y-14, x+14, y+14), outline=(0,255,120), width=3)
    inframe = []
    for n, (ra, de) in NAMED.items():
        x, y = wcs.world_to_pixel(SkyCoord(ra*u.deg, de*u.deg))
        if not (np.isfinite(x) and -50 < x < W+50 and -50 < y < H+50): continue
        inframe.append(n)
        col = (255,80,80) if n == 'S. CEL. POLE' else (255,220,0)
        d.line((x-30, y, x-12, y), fill=col, width=4); d.line((x+12, y, x+30, y), fill=col, width=4)
        d.line((x, y-30, x, y-12), fill=col, width=4); d.line((x, y+12, x, y+30), fill=col, width=4)
        d.text((x+36, y-18), n, fill=col, font=font)
    res[name]['named_in_frame'] = inframe
    rgb.save('out/annot_' + name.replace(' ', '').replace('(', '').replace(')', '') , quality=85)
    with open('out/wcs_' + name[3] + '.hdr', 'w') as fh: fh.write(wcs.to_header_string())
print(json.dumps(res, indent=1))
