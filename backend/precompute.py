"""Fill the frame cache for the challenge test targets. Run from the repo root: python -m backend.precompute"""
import sys
import time

from fastapi import HTTPException

from backend.spherex import get_frames

# (query, detector): the web app opens WISE 0855 with the D6 (4.4-5 um) stack, where the cold brown dwarf is bright.
TARGETS = [("Barnard's Star", ""), ("eps Ind B", ""), ("WISE J085510.83-071442.5", ""),
           ("WISE J085510.83-071442.5", "D6"), ("RW Aur", ""), ("R Dra", ""), ("Kapteyn's Star", "")]

if __name__ == "__main__":
    failed = 0
    for q, det in TARGETS:
        t0 = time.time()
        label = f"{q} {det}".strip()
        try:
            r = get_frames(q, det=det)
        except HTTPException as e:
            print(f"{label}: HTTP {e.status_code}: {e.detail}")
            failed += 1
            continue
        print(f"{label}: {len(r['frames'])} frames, {r['n_images_used']} images used, {r['n_failed']} failed, "
              f"cached={r['cached']}, {time.time() - t0:.1f} s")
    sys.exit(1 if failed else 0)
