// Tests for on-demand fields (fields.js). No network and no Python needed: the pipeline is faked.
// Run from the repository root:  node --test test/
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { createFieldService } = require("../fields");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "wanderers-"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 2000) { const t = Date.now(); while (Date.now() - t < ms) { const v = fn(); if (v) return v; await wait(10); } throw new Error("timed out"); }

// A fake pipeline: records calls, writes target.json when analyze.py runs (unless told not to).
function fake(dataDir, { analyzeWrites = true, failOn = null, delay = 0 } = {}) {
  const calls = [];
  const run = async (script, args, onLine) => {
    calls.push([script, ...args]);
    onLine(`running ${script}`);
    if (delay) await wait(delay);
    if (script === failOn) throw new Error(`${script} exited with code 1 at ${dataDir}/secret`);
    if (script === "fetch.py") return `target id: ${svc.idFor(+args[1], +args[3], +args[5])}\n`;
    if (script === "analyze.py" && analyzeWrites) { fs.mkdirSync(path.join(dataDir, args[0]), { recursive: true }); fs.writeFileSync(path.join(dataDir, args[0], "target.json"), "{}"); }
    return "";
  };
  const svc = createFieldService({ root: dataDir, dataDir, run });
  return { svc, calls };
}

test("target id matches pipeline/fetch.py add_position", () => {
  const { svc } = fake(tmp());
  assert.equal(svc.idFor(133.7951, -7.2451), "pos_133p7951_s7p2451");
  assert.equal(svc.idFor(76.9564, 30.4014), "pos_76p9564_n30p4014");
  assert.equal(svc.idFor(0, 0), "pos_0p0000_n0p0000");
});

test("rejects out-of-range or non-finite coordinates", () => {
  const { svc } = fake(tmp());
  for (const [ra, dec] of [[360, 0], [-1, 0], [10, 91], [10, -91], [NaN, 0], [0, Infinity]])
    assert.throws(() => svc.start(ra, dec), (e) => e.status === 400, `${ra},${dec}`);
});

test("cached field returns ready without running the pipeline", () => {
  const dir = tmp(), { svc, calls } = fake(dir);
  const tid = svc.idFor(10, 20);
  fs.mkdirSync(path.join(dir, tid)); fs.writeFileSync(path.join(dir, tid, "target.json"), "{}");
  assert.deepEqual(svc.start(10, 20), { status: "ready", tid });
  assert.equal(calls.length, 0);
});

test("new field runs fetch, analyze, evidence in order and finishes", async () => {
  const dir = tmp(), { svc, calls } = fake(dir);
  const j = svc.start(55.5, -12.25);
  assert.ok(["queued", "running"].includes(j.status));
  const done = await until(() => { const s = svc.status(j.job); return s.status === "done" && s; });
  assert.equal(done.tid, svc.idFor(55.5, -12.25));
  assert.deepEqual(calls.map((c) => c[0]), ["fetch.py", "analyze.py", "evidence.py"]);
});

test("the same field asked twice shares one job", async () => {
  const dir = tmp(), { svc, calls } = fake(dir, { delay: 30 });
  const a = svc.start(1, 2), b = svc.start(1, 2);
  assert.equal(a.job, b.job);
  await until(() => svc.status(a.job).status === "done");
  assert.equal(calls.filter((c) => c[0] === "fetch.py").length, 1);
});

test("jobs run one at a time", async () => {
  const dir = tmp(); let live = 0, peak = 0;
  const svc = createFieldService({ root: dir, dataDir: dir, run: async (script, args) => {
    live++; peak = Math.max(peak, live); await wait(15); live--;
    if (script === "fetch.py") return `target id: x${args[1].replace(/\W/g, "")}\n`;
    if (script === "analyze.py") { fs.mkdirSync(path.join(dir, args[0]), { recursive: true }); fs.writeFileSync(path.join(dir, args[0], "target.json"), "{}"); }
    return "";
  } });
  const jobs = [svc.start(1, 1), svc.start(2, 2), svc.start(3, 3)];
  await until(() => jobs.every((j) => svc.status(j.job).status === "done"), 4000);
  assert.equal(peak, 1);
});

test("limits how many fields can wait", () => {
  const dir = tmp(), { svc } = fake(dir, { delay: 200 });
  for (let i = 1; i <= 4; i++) svc.start(i, i);
  assert.throws(() => svc.start(50, 50), (e) => e.status === 429);
});

test("no SPHEREx data: reports an error, not success", async () => {
  const dir = tmp(), { svc, calls } = fake(dir, { analyzeWrites: false });
  const j = svc.start(200, 40);
  const s = await until(() => { const x = svc.status(j.job); return x.status === "error" && x; });
  assert.match(s.error, /No usable SPHEREx data/);
  assert.ok(!calls.some((c) => c[0] === "evidence.py"));
});

test("a failed field can be retried", async () => {
  const dir = tmp(), { svc } = fake(dir, { failOn: "fetch.py" });
  const j = svc.start(5, 5);
  await until(() => svc.status(j.job).status === "error");
  const again = svc.start(5, 5);
  assert.ok(["queued", "running"].includes(again.status));
});

test("error text never contains server paths", async () => {
  const dir = tmp(), { svc } = fake(dir, { failOn: "fetch.py" });
  const j = svc.start(7, 7);
  const s = await until(() => { const x = svc.status(j.job); return x.status === "error" && x; });
  assert.ok(!s.error.includes(dir), s.error);
  assert.doesNotMatch(s.error, /\/(Users|home|var|tmp)\//);
});

test("job ids are validated", () => {
  const { svc } = fake(tmp());
  for (const id of ["../etc", "", "a_b", null]) assert.throws(() => svc.status(id), (e) => e.status === 400);
  assert.throws(() => svc.status("1.0000_2.0000"), (e) => e.status === 404);
});

// ---- HTTP layer: start the real server (validation paths only, no pipeline is run) ----
async function withServer(fn) {
  const port = 20000 + Math.floor(Math.random() * 20000), base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, ["server.js"], { env: { ...process.env, PORT: String(port) }, stdio: "ignore", cwd: path.join(__dirname, "..") });
  try {
    let up = false;
    for (let i = 0; i < 60 && !up; i++) {
      if (child.exitCode !== null) throw new Error("server exited");
      try { up = (await fetch(base + "/api/health")).ok; } catch { await wait(100); }
    }
    if (!up) throw new Error("server did not start");
    await fn(base);
  } finally { child.kill(); }
}
const post = (base, p, body) => fetch(base + p, { method: "POST", headers: { "content-type": "application/json" }, body: typeof body === "string" ? body : JSON.stringify(body) });

test("HTTP: /api/field rejects bad input without starting work", async () => {
  await withServer(async (base) => {
    assert.equal((await post(base, "/api/field", "{")).status, 400);
    for (const body of ["null", "[]", "5"]) {                       // valid JSON, but not an object: a client error, not a 500
      const r = await post(base, "/api/field", body);
      assert.equal(r.status, 400, body); assert.match((await r.json()).error, /ra and dec must be numbers/, body);
    }
    assert.equal((await post(base, "/api/field", { ra: "10", dec: 5 })).status, 400);
    assert.equal((await post(base, "/api/field", { ra: 400, dec: 5 })).status, 400);
    assert.equal((await post(base, "/api/field", { ra: 10, dec: -100 })).status, 400);
    assert.equal((await post(base, "/api/field", "x".repeat(5000))).status, 413);
  });
});

test("HTTP: /api/job rejects bad ids and unknown jobs", async () => {
  await withServer(async (base) => {
    assert.equal((await fetch(base + "/api/job?id=../x")).status, 400);
    assert.equal((await fetch(base + "/api/job")).status, 400);
    assert.equal((await fetch(base + "/api/job?id=1.0000_2.0000")).status, 404);
  });
});

// ---- field of view ----
test("field of view: ids, jobs and the fetch command", async () => {
  const dir = tmp(), { svc, calls } = fake(dir);
  assert.equal(svc.idFor(133.7951, -7.2451, 300), "pos_133p7951_s7p2451");          // default keeps the old id
  assert.equal(svc.idFor(133.7951, -7.2451, 600), "pos_133p7951_s7p2451_f600");
  const a = svc.start(20, 30), b = svc.start(20, 30, 600), c = svc.start(20, 30, 600);
  assert.notEqual(a.job, b.job, "different field sizes are different jobs");
  assert.equal(b.job, c.job, "same size shares a job");
  assert.match(b.job, /_f600$/);
  await until(() => ["done"].includes(svc.status(a.job).status) && svc.status(b.job).status === "done", 4000);
  assert.equal(svc.status(b.job).tid, "pos_20p0000_n30p0000_f600");
  const fetches = calls.filter((x) => x[0] === "fetch.py").map((x) => x.slice(1).join(" "));
  assert.ok(fetches.includes("--ra 20 --dec 30 --fov 300"), fetches.join(" | "));
  assert.ok(fetches.includes("--ra 20 --dec 30 --fov 600"), fetches.join(" | "));
});

test("field of view: a cached field of that size is ready, other sizes are not", () => {
  const dir = tmp(), { svc, calls } = fake(dir, { delay: 50 });
  const tid = svc.idFor(10, 20, 120);
  fs.mkdirSync(path.join(dir, tid)); fs.writeFileSync(path.join(dir, tid, "target.json"), "{}");
  assert.deepEqual(svc.start(10, 20, 120), { status: "ready", tid });
  assert.notEqual(svc.start(10, 20, 300).status, "ready");
});

test("field of view must be a whole number from 60 to 900", () => {
  const { svc } = fake(tmp());
  for (const f of [59, 901, 0, -300, 300.5, NaN, Infinity, "300"]) assert.throws(() => svc.start(10, 20, f), (e) => e.status === 400, String(f));
  for (const f of [60, 120, 300, 600, 900]) assert.doesNotThrow(() => fake(tmp()).svc.start(10, 20, f), String(f));   // a fresh service each: four can wait at most
});

test("job ids with a field-of-view suffix are accepted, junk is not", () => {
  const { svc } = fake(tmp());
  assert.throws(() => svc.status("1.0000_2.0000_f600"), (e) => e.status === 404);   // valid format, unknown job
  for (const id of ["1.0000_2.0000_f", "1.0000_2.0000_fx", "1.0000_2.0000_f600_f600", "../_f600"]) assert.throws(() => svc.status(id), (e) => e.status === 400, id);
});

test("ids match pipeline/fov.py (Python) for many positions and sizes", { skip: spawnSync("python3", ["--version"]).status !== 0 && "python3 not available" }, () => {
  const { svc } = fake(tmp()), cases = [];
  for (const [ra, dec] of [[133.7951, -7.2451], [76.9564, 30.4014], [0, 0], [248.16734, 66.75501], [10.00005, -0.00004], [359.9999, -89.9999]])
    for (const fov of [60, 120, 300, 600, 900]) cases.push([ra, dec, fov]);
  const code = "import sys, json\nsys.path.insert(0, 'pipeline')\nimport fov\n" +
    "print(json.dumps([fov.position_id(r, d, f) for r, d, f in json.loads(sys.argv[1])]))";
  const r = spawnSync("python3", ["-I", "-c", code, JSON.stringify(cases)], { cwd: path.join(__dirname, "..") });
  assert.equal(r.status, 0, String(r.stderr));
  const py = JSON.parse(r.stdout.toString());
  cases.forEach(([ra, dec, fov], i) => assert.equal(svc.idFor(ra, dec, fov), py[i], `${ra},${dec},${fov}`));
});

test("HTTP: /api/field rejects a bad field of view", async () => {
  await withServer(async (base) => {
    assert.equal((await post(base, "/api/field", { ra: 10, dec: 5, fov: "600" })).status, 400);
    assert.equal((await post(base, "/api/field", { ra: 10, dec: 5, fov: 5000 })).status, 400);
    assert.equal((await post(base, "/api/field", { ra: 10, dec: 5, fov: 12.5 })).status, 400);
  });
});
