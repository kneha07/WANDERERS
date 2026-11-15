import json, subprocess, sys
W = r"C:\Users\user\Desktop\github\hackathon\nasa-space-apps-2026\.worktrees\movers"
def r(x, n=3):
    return round(x, n) if isinstance(x, float) else x
for tid in ["barnard", "eps_indi_b", "wise0855", "rw_aur", "r_dra"]:
    old = json.loads(subprocess.run(["git", "-C", W, "show", f"HEAD:app/data/{tid}/target.json"], capture_output=True, text=True, encoding="utf-8").stdout)
    new = json.load(open(f"{W}/app/data/{tid}/target.json", encoding="utf-8"))
    print("==", tid)
    for k in ["shift_arcsec", "measured_arcsec_per_yr", "measured_pmra", "measured_pmdec", "to_year"]:
        print(f"  motion.{k}: {r((old['motion'] or {}).get(k))} -> {r((new['motion'] or {}).get(k))}")
    print("  variability:", r((old['variability'] or {}).get('delta_mag')), "->", r((new['variability'] or {}).get('delta_mag')),
          r((old['variability'] or {}).get('uncertainty_mag')), "->", r((new['variability'] or {}).get('uncertainty_mag')))
    print("  ir ratio:", r(old['ir_color'].get('ratio'), 2), "->", r(new['ir_color'].get('ratio'), 2), "f3p3_err", r(old['ir_color'].get('f3p3_err'),4), "->", r(new['ir_color'].get('f3p3_err'),4))
    print("  points/flagged:", old['spectrum_points'], old['flagged_points'], "->", new['spectrum_points'], new['flagged_points'])
    print("  visits:", [(r(v['year'],2), v['n_images']) for v in old['spherex_visits']], "->", [(r(v['year'],2), v['n_images']) for v in new['spherex_visits']])
    oe, ne = old.get('evidence', {}), new.get('evidence', {})
    for k in sorted(set(oe) | set(ne)):
        if oe.get(k) != ne.get(k):
            print(f"  evidence.{k} changed:\n    OLD {json.dumps(oe.get(k), ensure_ascii=False)[:600]}\n    NEW {json.dumps(ne.get(k), ensure_ascii=False)[:600]}")
    if old.get('insights') != new.get('insights'):
        print("  insights changed:\n    OLD", json.dumps(old.get('insights'), ensure_ascii=False)[:900], "\n    NEW", json.dumps(new.get('insights'), ensure_ascii=False)[:900])
