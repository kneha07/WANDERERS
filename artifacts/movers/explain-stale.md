# explain.json after the image-set refresh (#41)

The five `explain.json` texts were written by `pipeline/explain.py` (Claude CLI) from the old image set. They are **not regenerated**.
Every verdict is unchanged (status, classification, confidence, checks passed: same for all five targets). Only quoted numbers differ:

| Target | Text says | Card now says |
|---|---|---|
| Barnard's Star | 10.40″/yr; brightness +0.03 ± 0.03 mag | 10.39″/yr; -0.04 mag |
| Epsilon Indi B | 4.69″/yr, within 0.2%; -0.06 ± 0.03 mag; 69 of 180 points flagged | 4.72″/yr, 0.7%; -0.01 mag; 59 of 149 |
| WISE 0855-0714 | 8.27″/yr; methane test 5.1× | 8.24″/yr; methane test "> 4×" |
| RW Aurigae | brightness +0.03 mag; shift 0.57″ | +0.00 mag; shift 0.62″ |
| R Draconis | apparent drift 0.43″/yr; +0.34 mag | 0.09″/yr; +0.32 mag |

Fix: run `pipeline/explain.py` (needs the Claude Code CLI) and commit the five files.
