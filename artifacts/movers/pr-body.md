## What this changes

The mover search ("What else moved in this field?") now finds its own target. Closes #41.

**Root causes (measured):**
- WISE 0855: the right SPHEREx dot was removed as static. A 2010 dot 2.1 px away had a brightness ratio of 1.05. Its ratio to the 2010 end (4.08) also failed the `log(4)` brightness gate.
- Barnard's Star: the right pair ranked first, but saturation gave a peak ratio of 12.3, so the gate rejected it.

**Fix** (`pipeline/analyze.py`): try known paths first (the target's reference motion, then Gaia paths), matching each end by position within 4 px; then free pairs, sorted by brightness as before.

| Target | `target_recovered` on main | now | unexplained pairs |
|---|---|---|---|
| Barnard's Star | false | **true** | 0 |
| Epsilon Indi B | true | true | 0 |
| WISE 0855 | false | **true** | 0 |
| RW Aur, R Dra | (does not move) | (does not move) | 0 |

## Data: what a reviewer must know

1. **The image set is new.** The old cache could not be rebuilt (it grew past the 150-image cap, and the SPHEREx archive has grown). The five `target.json` files and their frames are rebuilt with main's `analyze.py` plus the fix, then `gaia_facts.py`, `evidence.py`, `vet.py`.
2. **Verdicts are unchanged** for all five targets (status, classification, confidence, checks passed). Quoted numbers shift, for example WISE 0855 methane 5.1× → "> 4×", R Dra apparent drift 0.52 → 0.09″/yr. Table: `artifacts/movers/explain-stale.md`.
3. **`explain.json` is not regenerated** (needs the Claude Code CLI). The five plain-language texts still quote the old numbers; same table.
4. Main's six newer targets (`pos_*`) and `index.json` are not changed: the scripts rewrote them with the same content, so I restored them.
5. Two tests in `test/frameinfo.test.js` pinned old frame counts; updated to the new image set (WISE 0855 41 of 150 flagged; Barnard 150 of 150).

**Snapshot:** tag `snapshot-2026-11-15-before-real-sky` is main before this PR and #40.

## Checks

| Command | Result |
|---|---|
| `node --test test/*.test.js` | 161 pass, 0 fail |
| `python -m unittest tests.test_evidence tests.test_vet` | 29 pass |
| `python -m unittest tests.test_movers` (new, needs numpy) | 3 pass |
| Browser: `observatory.html?target=wise0855` | card: "5 pairs … None is left unexplained. 1 known. 4 ruled out." (main: 4 pairs, target missed) |

Seen in the browser, also on main (not caused here): `<circle>` NaN errors in the console, filed as a separate issue.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
