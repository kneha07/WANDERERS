// Tests for on-demand fields (fields.js). No network and no Python needed: the pipeline is faked.
// Run from the repository root:  node --test test/
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn } = require("node:child_process");
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
    if (script === "fetch.py") return `target id: ${svc.idFor(+args[1], +args[3])}\n`;
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
