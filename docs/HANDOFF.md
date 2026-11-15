# Handoff: WANDERERS follow-up work

Written 2026-11-14 for the agent that continues this work. Read this file first, then only the document that your current task points to.

## Where things stand

| Branch | State | Holds |
|---|---|---|
| `origin/main` (`35cb320`) | the team's integrated code | the base for all new work |
| `feature/insights` (worktree `.worktrees/insights`) | 6 commits ahead of `origin/main`, **not pushed** | insight facts and limits on the evidence card, two label fixes, the vetted mover list, and the three documents below |
| local `main` | behind `origin/main` by 51 commits, with other people's commits on top | leave it alone |
| `feat/explore-redesign` (worktree `.worktrees/redesign`) | someone is working there now | leave it alone |

Documents on `feature/insights`:

- `docs/product-gaps.md`: who the users are, the ranked gaps, the boundaries of the tool, what is done, what comes next.
- `docs/specs/sky-compass-real-sky.md`: the full spec for the real-sky feature (task 2).
- `docs/HANDOFF.md`: this file.

## Tasks, in order

Finish one task before you start the next. Each ends on its own check.

### 1. Land `feature/insights`

1. In `.worktrees/insights`, run the checks in **Checks** below. All pass.
2. Push the branch and open a pull request to `main` on `kneha07/WANDERERS` with `gh`. This repository works through pull requests (#12 to #19); merging is the humans' decision.
3. In the pull request body, list the three behaviour changes a reviewer must know: RW Aurigae now reads "Known variable star, quiet in these snapshots"; a shift below the detection limit is labelled "apparent drift"; `evidence.py` now imports `vet.py` when a target has no `changes` block.

**Done when** the pull request is open and its description names the test commands and their results.

### 2. Real sky behind Sky Compass

Follow `docs/specs/sky-compass-real-sky.md` from top to bottom. It has six steps; each has a "Done when" list, and each step can be its own pull request.

Start a new worktree from `origin/main`, and bring the spec with you:

```bash
git.exe worktree add .worktrees/real-sky -b feature/real-sky origin/main
cd .worktrees/real-sky && git.exe checkout feature/insights -- docs/specs/sky-compass-real-sky.md docs/HANDOFF.md
```

Three things in the spec are marked unverified. Settle them with the test the spec names before you build on them:

- the sign of `aladin.setRotation` and the meaning of `setFoV` in the `STG` projection (spec step 3, registration test);
- which tile URLs Aladin really requests (spec step 5, ground-truth check);
- where the north pole falls in the nested pixel numbering (spec step 5, last unit test).

When a spec statement and a measurement disagree, the measurement wins: change the spec in the same commit and say why in the commit message.

**Done when** every "Done when" item in the spec is met, or is listed in the pull request as not met with the reason.

### 3. Make the mover search find its own targets

The vetting is done (`pipeline/vet.py`). The search it vets (`find_movers` in `pipeline/analyze.py`) is not: it recovers its own target in 1 of the 3 fields where the target moves. `target.json → changes.target_recovered` records this per field, and the page shows it.

1. Get the image cache: `pipeline/fetch.py all` into `data/cache/` (needs the pipeline packages, see **Environment**; IRSA can be slow).
2. Reproduce on WISE 0855: the 2010 dot of the target is paired with the wrong SPHEREx dot. Find out why the right dot lost (missing from `b_only`, or beaten in the brightness sort).
3. Fix the pairing. First idea to test: try pairs that match a known path (the target's reference motion, then Gaia paths) before the brightness-sorted free pairs.
4. Run `analyze.py`, `evidence.py`, `vet.py` on the five targets.

**Done when** `target_recovered` is `true` for Barnard's Star, Epsilon Indi B and WISE 0855, the five fields still show 0 unexplained pairs (or each new one is examined and written up), and `tests/test_vet.py` plus a new test of the pairing on synthetic images pass.

### 4. The rest

Take the remaining items from "Next, in order of value" in `docs/product-gaps.md`: an asteroid check, one product instead of two (issues #6 and #9), a host for the live API, the 2010–2025 time line, production basics. Ask the user which one before you start; they are product decisions.

## Environment (what you cannot find by looking)

- **Two gits.** The repository lives on a Windows disk and its worktrees were made with Windows git. From WSL, use `git.exe` for every git command inside a worktree. WSL `git` reports those worktrees as broken and "prunable"; they are fine. Never run `git worktree prune` or `git worktree repair` from WSL.
- **Line endings.** Files are LF in the working tree. WSL `git status` in the main checkout shows false changes in `docs/agents/`; `git.exe status` is the truth.
- **Python in WSL** is bare: no pip, no numpy. It runs everything that needs only the standard library: `pipeline/evidence.py`, `pipeline/vet.py`, `tests/test_evidence.py`, `tests/test_vet.py`, `test/test_fov.py`.
- **Python with packages:** `backend/.venv/Scripts/python.exe` (Windows, callable from WSL) has numpy, astropy and scipy, but not astroquery or reproject. For `fetch.py` and `analyze.py`, make a venv inside your worktree and install `pipeline/requirements.txt`.
- **No image cache.** `data/cache/` is not in any checkout, so `analyze.py` cannot run until `fetch.py` has.
- **Browser checks.** No Linux browser works here. Headless Edge does:
  ```bash
  python3 -m http.server -d app 8017 &
  "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --disable-gpu --hide-scrollbars \
    --user-data-dir='C:\...\<worktree>\artifacts\<task>\prof' --window-size=1400,1700 --virtual-time-budget=8000 \
    --screenshot='C:\...\<worktree>\artifacts\<task>\shot.png' "http://localhost:8017/?target=wise0855&pick=2"
  ```
  Use Windows paths for the two file arguments, delete the `prof` folder afterwards, and read the PNG to check it. Phone sensors and the camera cannot be tested this way: say so in the pull request rather than claiming it.
- **Archives.** CDS in Strasbourg (`alasky`, `simbad`, `vizier` under `cds.unistra.fr`) was down on 2026-11-14. Working mirrors: `irsa.ipac.caltech.edu/data/hips/` for sky tiles, `simbad.harvard.edu` and `vizier.cfa.harvard.edu` for catalogues. Code that calls an archive tries a second host.
- **Hosting.** The static page is live at `https://rajryadav4.github.io/wanderers/` (sub-path `/wanderers/`, so use relative URLs). The live explorer, typed coordinates and "Ask" run only with the local servers.
- **Folder rules.** The workspace `CLAUDE.md` applies: worktrees under `.worktrees/`, logs and screenshots under `artifacts/` inside the worktree, nothing at the top level, remove a worktree when its branch merges.

## Checks

Run from the worktree root. State the result of each in the pull request.

```bash
node --test test/*.test.js                                # 61 pass on feature/insights
python3 -m unittest tests.test_evidence tests.test_vet    # 29 pass on feature/insights
python3 test/test_fov.py
node --check app/app.js app/compass.js server.js fields.js
```

`tests/test_data_quality.py` and `backend/` pytest need numpy: run them with a Python that has it, or report them as not run.

## Rules of the house

- **Say what the data supports.** Every number on the page carries its source or formula. An unmatched object is a "candidate", never a "discovery". A survey photograph is labelled as not live. A drawn sky is labelled as not a photograph.
- **Show limits next to results.** If a search can miss things, the page says so beside the result (see `changes.target_recovered`).
- **Regenerate, then commit data.** `app/data/*/target.json` is generated: change the pipeline, run it, and commit both. `explain.json` needs the Claude CLI (`pipeline/explain.py`); if a card's wording changes and you cannot regenerate it, check that the old text still agrees and say so.
- **Report honestly.** List what you did not test and what you could not verify. A short true report is worth more than a long confident one.
