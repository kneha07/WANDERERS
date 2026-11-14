"""Keeps the Python files runnable on the Python version the project promises.

start.js and docs/blink/README.md say "Python 3.11 or newer". Python 3.12 relaxed one rule that 3.11 still has: inside an
f-string, an expression may reuse the quote that delimits the f-string (PEP 701). Code written that way runs on 3.12+ and is a
SyntaxError on 3.11. This happened once: pipeline/analyze.py used  f"...{[... for ch in ("w2","w1")]}..."  and failed on 3.11.

Two checks over every Python file in the repository:
  1. it compiles (on 3.11 this catches the problem directly);
  2. on 3.12+, where the line above would compile, a tokenizer scan finds any string literal that reuses its f-string's quote.

No third-party packages needed. Run from the repository root:  python3 test/test_python_compat.py -v
"""
import io
import py_compile
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "background", "__pycache__", "dist"}


def python_files():
    out = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS or part.startswith(".venv") for part in rel.parts):
            continue
        out.append(p)
    return sorted(out)


def reused_quotes(source):
    """(line, text) of every string inside an f-string expression that uses the f-string's own quote. 3.12+ only."""
    hits, stack = [], []
    for t in tokenize.generate_tokens(io.StringIO(source).readline):
        name = tokenize.tok_name[t.type]
        if name == "FSTRING_START":
            stack.append(t.string[-1])
        elif name == "FSTRING_END" and stack:
            stack.pop()
        elif name == "STRING" and stack and t.string.lstrip("rbfuRBFU")[:1] == stack[-1]:
            hits.append((t.start[0], t.string[:30]))
    return hits


class TestPythonCompat(unittest.TestCase):
    def test_files_are_found(self):
        names = {p.name for p in python_files()}
        self.assertGreaterEqual(len(names), 15)
        self.assertIn("analyze.py", names)

    def test_every_file_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            for p in python_files():
                with self.subTest(file=str(p.relative_to(ROOT))):
                    try:
                        py_compile.compile(str(p), cfile=str(Path(tmp) / (p.stem + ".pyc")), doraise=True)
                    except py_compile.PyCompileError as exc:
                        self.fail(f"{p.relative_to(ROOT)} does not compile on Python {sys.version_info.major}.{sys.version_info.minor}: {exc.msg}")

    @unittest.skipIf(sys.version_info < (3, 12), "the tokenizer scan needs Python 3.12; on 3.11 the compile check above catches it")
    def test_no_quote_reuse_inside_f_strings(self):
        for p in python_files():
            with self.subTest(file=str(p.relative_to(ROOT))):
                hits = reused_quotes(p.read_text(encoding="utf-8"))
                self.assertEqual(hits, [], f"{p.relative_to(ROOT)} reuses an f-string's quote inside it (SyntaxError on Python 3.11, "
                                          f"which the docs promise to support): {hits}")

    @unittest.skipIf(sys.version_info < (3, 12), "needs the 3.12 tokenizer")
    def test_the_scan_really_catches_the_old_bug(self):
        bad = 'x = f"{[c for c in ("w2","w1")]}"\n'
        self.assertEqual([h[0] for h in reused_quotes(bad)], [1, 1])
        good = "x = f\"{[c for c in ('w2','w1')]}\"\n"
        self.assertEqual(reused_quotes(good), [])
        self.assertEqual(reused_quotes('y = f"{a}" + "plain"\n'), [])


if __name__ == "__main__":
    unittest.main()
