// Tests for test/run-all.js: reading test summaries and deciding pass or fail.
// Run from the repository root:  node --test test/runall.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { parseNodeSummary, parsePythonSummary, verdict, pythonFor } = require("./run-all.js");

test("reads the summary that node --test prints", () => {
  assert.deepEqual(parseNodeSummary("...\n# tests 9\n# suites 0\n# pass 7\n# fail 1\n# cancelled 0\n# skipped 1\n# todo 0\n"), { pass: 7, fail: 1, skipped: 1 });
  assert.deepEqual(parseNodeSummary(""), { pass: 0, fail: 0, skipped: 0 });
  assert.deepEqual(parseNodeSummary("# pass 25\n# fail 0\n# skipped 0"), { pass: 25, fail: 0, skipped: 0 });
});

test("reads the summary that unittest prints", () => {
  assert.deepEqual(parsePythonSummary("----\nRan 20 tests in 0.181s\n\nOK"), { ran: 20, skipped: 0, failed: false });
  assert.deepEqual(parsePythonSummary("Ran 0 tests in 0.291s\n\nOK (skipped=1)"), { ran: 0, skipped: 1, failed: false });
  assert.deepEqual(parsePythonSummary("Ran 3 tests in 0.1s\n\nFAILED (failures=1, errors=2, skipped=1)"), { ran: 3, skipped: 1, failed: true });
  assert.deepEqual(parsePythonSummary("Ran 1 test in 0.0s\n\nOK"), { ran: 1, skipped: 0, failed: false });
  assert.deepEqual(parsePythonSummary("Traceback ... ModuleNotFoundError"), { ran: 0, skipped: 0, failed: false });
});

const good = { name: "a", status: 0, fail: 0, skipped: 0 };

test("all passing is a pass in both modes", () => {
  for (const strict of [false, true]) assert.deepEqual(verdict([good, { ...good, name: "b" }], strict), { ok: true, problems: [], warnings: [] });
});

test("a failure fails in both modes, whether the exit code or the count says so", () => {
  for (const strict of [false, true]) {
    assert.equal(verdict([good, { name: "b", status: 1, fail: 0, skipped: 0 }], strict).ok, false);
    assert.equal(verdict([good, { name: "b", status: 0, fail: 2, skipped: 0 }], strict).ok, false);
  }
});

test("a skip is a warning in quick mode and a failure in strict mode", () => {
  const skipped = { name: "py", status: 0, fail: 0, skipped: 1 };
  const quick = verdict([good, skipped], false), strict = verdict([good, skipped], true);
  assert.deepEqual([quick.ok, quick.warnings.length, quick.problems.length], [true, 1, 0]);
  assert.deepEqual([strict.ok, strict.warnings.length, strict.problems.length], [false, 0, 1]);
  assert.match(strict.problems[0], /py: 1 skipped/);
});

test("a suite that could not start is a warning in quick mode and a failure in strict mode", () => {
  const notRun = { name: "py", notRun: "could not start python" };
  assert.deepEqual([verdict([good, notRun], false).ok, verdict([good, notRun], false).warnings.length], [true, 1]);
  assert.equal(verdict([good, notRun], true).ok, false);
  assert.match(verdict([good, notRun], true).problems[0], /not run \(could not start python\)/);
});

test("a failure is never hidden by a skip or a warning", () => {
  const r = verdict([{ name: "x", status: 1, fail: 1, skipped: 1 }, { name: "py", notRun: "no python" }], false);
  assert.equal(r.ok, false);
  assert.ok(r.problems.some((p) => /x: failed/.test(p)));
});

test("which Python runs the Python tests", () => {
  const root = path.join("/", "proj"), has = (...parts) => { const want = path.join(root, ...parts); return (p) => p === want; };
  assert.equal(pythonFor(root, { WANDERERS_PYTHON: "/opt/py" }, "linux", () => false), "/opt/py");
  assert.equal(pythonFor(root, {}, "linux", has(".venv", "bin", "python")), path.join(root, ".venv", "bin", "python"));
  assert.equal(pythonFor(root, {}, "linux", () => false), "python3");
  assert.equal(pythonFor(root, {}, "win32", has(".venv", "Scripts", "python.exe")), path.join(root, ".venv", "Scripts", "python.exe"));
  assert.equal(pythonFor(root, {}, "win32", () => false), "python");
  assert.equal(pythonFor(root, {}, "linux", has(".venv", "Scripts", "python.exe")), "python3");
});
