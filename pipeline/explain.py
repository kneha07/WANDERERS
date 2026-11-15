"""Write the plain-language explanations with Claude, headless, no API key needed.

    python pipeline/explain.py            # every analysed target
    python pipeline/explain.py barnard

Uses the Claude Code CLI in print mode (`claude -p`), which runs on the logged-in Claude Code
account. Claude only sees the measurements in target.json (no images, no web), and the rules
below forbid inventing facts. Output is saved to app/data/<id>/explain.json so the deployed site
is fully static.
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"

RULES = """You are the analyst inside WANDERERS, a public tool that shows real NASA SPHEREx and WISE images and
ESA Gaia data. You will get one object's measurements as JSON.
Rules:
- Use ONLY numbers and facts present in the JSON, plus general astronomy background a textbook would state.
- Never say "discovery" or "discovered by WANDERERS". Known objects are known; unmatched ones are candidates.
- If a measurement is flagged, saturated or uncertain, say so plainly.
- Plain language for a curious high-school student. No markdown, no bullet points, no headings.
"""

QUESTIONS = [
    "Why do we think this is what the card says?",
    "What would make you less sure?",
    "Why use both WISE and SPHEREx?",
]


def slim(t):
    keep = ("name", "kind", "reference", "target_in_gaia", "motion", "variability", "ir_color",
            "spectrum_points", "flagged_points", "spherex_visits", "evidence")
    s = {k: t.get(k) for k in keep}
    s["spectrum_summary"] = [{"lam": p["lam"], "flux_mjy": round(p["flux_mjy"], 4)} for p in t["spectrum"][::3]]
    return s


def ask(prompt):
    r = subprocess.run(["claude", "-p", prompt, "--output-format", "text"], capture_output=True, text=True, encoding="utf-8", timeout=240)   # UTF-8: Windows would read it as cp1252
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout.strip()


def explain(tid):
    f = DATA / tid / "target.json"
    t = json.loads(f.read_text())
    facts = json.dumps(slim(t), default=float)
    summary = ask(f"{RULES}\nMeasurements:\n{facts}\n\nIn at most 90 words, explain what this object is, what WANDERERS "
                  f"measured, and how sure we are.")
    qa = []
    for q in QUESTIONS:
        qa.append({"q": q, "a": ask(f"{RULES}\nMeasurements:\n{facts}\n\nQuestion: {q}\nAnswer in at most 70 words.")})
    out = {"summary": summary, "qa": qa, "model_note": "Written by Claude (Claude Code, headless) from target.json only."}
    (DATA / tid / "explain.json").write_text(json.dumps(out, indent=1))
    print(f"{t['name']}: {summary[:120]}…")


if __name__ == "__main__":
    # A Windows console is cp1252 by default and cannot print ″ (issue #46): write UTF-8, and never crash on a character.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ids = sys.argv[1:] or [p.parent.name for p in sorted(DATA.glob("*/target.json"))]
    for tid in ids:
        try:
            explain(tid)
        except Exception as e:
            print(f"!! {tid}: {e}")
