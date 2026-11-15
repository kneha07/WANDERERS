import sys, json, pickle
import numpy as np
W = r"C:\Users\user\Desktop\github\hackathon\nasa-space-apps-2026\.worktrees\movers"
sys.path.insert(0, W + r"\pipeline")
import analyze
cap = {}
orig = analyze.find_movers
def spy(*a, **k):
    cap["args"] = a
    return orig(*a, **k)
analyze.find_movers = spy
tid = sys.argv[1]
r = analyze.analyze(tid)
img_old, img_new, y_old, y_new, gw, stars, npix, mids = cap["args"]
from fetch import predict
ref = r["reference"]
p0 = [float(v) for v in gw.world_to_pixel(predict(ref, y_old))]
p1 = [float(v) for v in gw.world_to_pixel(predict(ref, y_new))]
print("predicted target path px", p0, "->", p1, "years", y_old, y_new, "n mids", len(mids))
print("track w2", [(p["mission"], round(p["year"],2), round(p["x"],1), round(p["y"],1)) for p in r["track"] if p["ch"]=="w2"])
A, B = analyze.find_sources(img_old), analyze.find_sources(img_new)
near = lambda p, L, rr: any(np.hypot(p[0]-q[0], p[1]-q[1]) < rr and abs(np.log(p[2]/q[2])) < np.log(4) for q in L)
def show(name, L, c):
    for p in L:
        if np.hypot(p[0]-c[0], p[1]-c[1]) < 8:
            print(f"  {name} source near target end: ({p[0]:.1f},{p[1]:.1f}) z={p[2]:.1f}")
show("A(2010)", A, p0); show("B(new)", B, p1)
a_only = [p for p in A if not near(p, B, 4) and np.isfinite(img_new[int(round(p[1])) % npix, int(round(p[0])) % npix])]
b_only = [p for p in B if not near(p, A, 4) and np.isfinite(img_old[int(round(p[1])) % npix, int(round(p[0])) % npix])]
print("len A,B", len(A), len(B), "a_only", len(a_only), "b_only", len(b_only))
show("a_only", a_only, p0); show("b_only", b_only, p1)
for name, L, c in (("a", A, p0), ("b", B, p1)):
    for p in L:
        if np.hypot(p[0]-c[0], p[1]-c[1]) < 8:
            other = B if name == "a" else A
            img_o = img_new if name == "a" else img_old
            blk = [(round(q[0],1), round(q[1],1), round(q[2],1)) for q in other if np.hypot(p[0]-q[0], p[1]-q[1]) < 4]
            print(f"  {name} end ({p[0]:.1f},{p[1]:.1f}) z={p[2]:.1f}: other-epoch sources within 4 px {blk}; other img finite={np.isfinite(img_o[int(round(p[1]))%npix, int(round(p[0]))%npix])}")
a_only6 = [p for p in a_only if p[2] >= 6]; b_only6 = [p for p in b_only if p[2] >= 6]
pairs = []
for i, a in enumerate(a_only6):
    for j, b in enumerate(b_only6):
        d = np.hypot(b[0]-a[0], b[1]-a[1])
        if 4 <= d <= 95:
            pairs.append((abs(np.log(b[2]/a[2])), d, i, j))
pairs.sort()
ta = [i for i, a in enumerate(a_only6) if np.hypot(a[0]-p0[0], a[1]-p0[1]) < 4]
tb = [j for j, b in enumerate(b_only6) if np.hypot(b[0]-p1[0], b[1]-p1[1]) < 4]
print("target a idx", ta, [a_only6[i] for i in ta], "target b idx", tb, [b_only6[j] for j in tb])
for k, (s, d, i, j) in enumerate(pairs):
    if i in ta or j in tb:
        print(f"  rank {k}: score {s:.3f} (ratio {np.exp(s):.2f}) d={d:.1f} a={tuple(round(v,1) for v in a_only6[i])} b={tuple(round(v,1) for v in b_only6[j])}")
print("movers", [(round(m["x0"],1), round(m["y0"],1), round(m["x1"],1), round(m["y1"],1), m["snr"]) for m in r["movers_experimental"]])
