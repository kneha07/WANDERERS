#!/usr/bin/env node
// Runs every test in the repository: the Node tests (test/*.test.js) and the Python tests (test/test_*.py).
//
//   node test/run-all.js            a quick run. Tests that need the pipeline packages are skipped, with a warning.
//   node test/run-all.js --strict   a skipped test, or a missing Python, counts as a FAILURE.
//                                   Same with WANDERERS_STRICT=1 or CI=true. Use this in CI, so a machine
//                                   without the packages can never look green.
//
// Exit code 0 only if nothing failed (and, in strict mode, nothing was skipped).
"use strict";
const { spawnSync } = require("node:child_process");
const fs = require("node:fs"), path = require("node:path");

// Which Python runs the Python tests: WANDERERS_PYTHON, else the project's venv, else python3 ("python" on Windows).
// Same order the on-demand field service uses; kept here so this file needs nothing else from the repository.
function pythonFor(root, env = process.env, platform = process.platform, exists = fs.existsSync) {
  if (env.WANDERERS_PYTHON) return env.WANDERERS_PYTHON;
  const win = platform === "win32";
  for (const parts of win ? [[".venv", "Scripts", "python.exe"], [".venv", "bin", "python"]] : [[".venv", "bin", "python"]]) {
    const p = path.join(root, ...parts);
    if (exists(p)) return p;
  }
  return win ? "python" : "python3";
}

// `node --test` ends with TAP lines such as "# pass 9", "# fail 0", "# skipped 0".
function parseNodeSummary(out) {
  const get = (k) => { const m = new RegExp(`^# ${k} (\\d+)`, "m").exec(out); return m ? Number(m[1]) : 0; };
  return { pass: get("pass"), fail: get("fail"), skipped: get("skipped") };
}

// unittest ends with "Ran 20 tests in 0.2s" and then "OK", "OK (skipped=1)" or "FAILED (failures=1, errors=2)".
function parsePythonSummary(out) {
  const ran = /^Ran (\d+) tests?/m.exec(out), skipped = /skipped=(\d+)/.exec(out);
  return { ran: ran ? Number(ran[1]) : 0, skipped: skipped ? Number(skipped[1]) : 0, failed: /^FAILED/m.test(out) };
}

// results: [{ name, status, fail, skipped, notRun? }]. Strict mode turns skips and "not run" into problems.
function verdict(results, strict) {
  const problems = [], warnings = [];
  for (const r of results) {
    if (r.notRun) { (strict ? problems : warnings).push(`${r.name}: not run (${r.notRun})`); continue; }
    if (r.status !== 0 || r.fail > 0) problems.push(`${r.name}: failed`);
    if (r.skipped > 0) (strict ? problems : warnings).push(`${r.name}: ${r.skipped} skipped`);
  }
  return { ok: problems.length === 0, problems, warnings };
}

function main() {
  const root = path.join(__dirname, "..");
  const strict = process.argv.includes("--strict") || process.env.WANDERERS_STRICT === "1" || process.env.CI === "true";
  const env = { ...process.env, ...(strict ? { WANDERERS_STRICT: "1" } : {}) };
  const results = [], show = (r, detail) => console.log(`${r.status === 0 && !r.fail && !r.notRun ? "ok  " : r.notRun ? "--  " : "FAIL"} ${r.name.padEnd(34)} ${detail}`);

  // Node tests. Node 22 needs real file paths, so each file is run by name.
  for (const f of fs.readdirSync(__dirname).filter((n) => n.endsWith(".test.js")).sort()) {
    const name = `test/${f}`, p = spawnSync(process.execPath, ["--test", name], { cwd: root, env, encoding: "utf8" });
    const s = parseNodeSummary(p.stdout || ""), r = { name, status: p.status, fail: s.fail, skipped: s.skipped };
    results.push(r);
    show(r, `${s.pass} passed${s.fail ? `, ${s.fail} FAILED` : ""}${s.skipped ? `, ${s.skipped} skipped` : ""}`);
    if (p.status !== 0) console.log((p.stdout || "").split("\n").filter((l) => /^not ok|error:|^# (fail|pass)/.test(l)).slice(0, 12).join("\n"));
  }

  // Python tests (unittest style, so no extra package is needed to run them).
  const py = pythonFor(root);
  const p = spawnSync(py, ["-m", "unittest", "discover", "-s", "test", "-p", "test_*.py"], { cwd: root, env, encoding: "utf8" });
  const name = "test/test_*.py (Python)";
  if (p.error) {
    const r = { name, notRun: `could not start "${py}": install Python 3, or set WANDERERS_PYTHON` };
    results.push(r); show(r, r.notRun);
  } else {
    const out = (p.stderr || "") + (p.stdout || ""), s = parsePythonSummary(out), r = { name, status: p.status, fail: s.failed ? 1 : 0, skipped: s.skipped };
    results.push(r);
    show(r, `${s.ran} ran${s.failed ? ", FAILED" : ""}${s.skipped ? `, ${s.skipped} suite(s) skipped (packages missing: pip install -r pipeline/requirements.txt)` : ""}`);
    if (p.status !== 0) console.log(out.split("\n").slice(-14).join("\n"));
  }

  const v = verdict(results, strict);
  console.log(`\n${strict ? "STRICT mode" : "Quick mode"}: ${v.ok ? "PASS" : "FAIL"}`);
  v.warnings.forEach((w) => console.log(`  warning: ${w}`));
  v.problems.forEach((w) => console.log(`  problem: ${w}`));
  if (v.warnings.length) console.log("  Something was skipped, so this is not a full green. Run with --strict to make that a failure.");
  process.exit(v.ok ? 0 : 1);
}

if (require.main === module) main();
module.exports = { parseNodeSummary, parsePythonSummary, verdict, pythonFor };
