"""Fill the frame cache for the challenge test targets. Run from the repo root: python -m backend.precompute"""
import sys
import time

from fastapi import HTTPException

from backend.spherex import get_frames

TARGETS = ["Barnard's Star", "eps Ind B", "WISE J085510.83-071442.5", "RW Aur", "R Dra"]

if __name__ == "__main__":
    failed = 0
    for q in TARGETS:
        t0 = time.time()
        try:
            r = get_frames(q)
        except HTTPException as e:
            print(f"{q}: HTTP {e.status_code}: {e.detail}")
            failed += 1
            continue
        print(f"{q}: {len(r['frames'])} frames, {r['n_images_used']} images used, {r['n_failed']} failed, "
              f"cached={r['cached']}, {time.time() - t0:.1f} s")
    sys.exit(1 if failed else 0)
