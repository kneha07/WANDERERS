// POST /api/star-fix in server.js: one photo (raw bytes) in, one JSON result out. Runs real servers on free ports.
// node --test test/starfix-server.test.js
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs"), http = require("node:http"), net = require("node:net"), os = require("node:os"), path = require("node:path");
const { pickPython } = require("../fields");

const ROOT = path.join(__dirname, "..");
const DOWN = "Star Fix could not run. Start the app with start.cmd.", CRASH = "Could not read this photo.";
const PATHLIKE = /[A-Za-z]:\\|\/Users\/|\/home\/|\\\\|Traceback|\.py\b/;   // no response may show a server path
const kids = [];

const freePort = () => new Promise((ok, bad) => { const s = net.createServer(); s.once("error", bad); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => ok(p)); }); });
async function startServer(env) {
  const port = await freePort(), base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, ["server.js"], { cwd: ROOT, env: { ...env, PORT: String(port) }, stdio: "ignore" });
  kids.push(child);
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(base + "/api/health")).ok) return base; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server did not start");
}
const post = (base, body) => fetch(base + "/api/star-fix", { method: "POST", body });
async function answer(r) { const text = await r.text(); assert.doesNotMatch(text, PATHLIKE); return { status: r.status, text, json: JSON.parse(text) }; }

const env = { ...process.env }; delete env.WANDERERS_PY;
const hasPackages = spawnSync(pickPython(ROOT), ["-c", "import pillow_heif, PIL, astropy"], { cwd: ROOT }).status === 0;
let real, broken, crashing, noPackage;
const shadow = fs.mkdtempSync(path.join(os.tmpdir(), "starfix-"));   // a pillow_heif that fails to import, first on PYTHONPATH
fs.writeFileSync(path.join(shadow, "pillow_heif.py"), "import no_such_module_for_star_fix\n");
before(async () => {
  real = await startServer(env);
  broken = await startServer({ ...env, WANDERERS_PY: path.join(ROOT, "no-such-python.exe") });
  crashing = await startServer({ ...env, WANDERERS_PY: process.execPath });   // node runs star_fix.py: a crash after start
  noPackage = await startServer({ ...env, PYTHONPATH: shadow });
});
after(() => { kids.forEach((k) => k.kill()); fs.rmSync(shadow, { recursive: true, force: true }); });

test("an empty body is 400 'no photo'", async () => {
  assert.deepEqual(await answer(await post(real, "")), { status: 400, text: '{"error":"no photo"}', json: { error: "no photo" } });
});

test("a 31 MB body is refused (413 or a closed connection) and the server still answers after it", async () => {
  try {
    const r = await post(real, Buffer.alloc(31 * 1024 * 1024, 7));
    assert.deepEqual(await answer(r), { status: 413, text: '{"error":"photo too large"}', json: { error: "photo too large" } });
  } catch (e) {
    if (e.code === "ERR_ASSERTION") throw e;   // otherwise fetch saw the connection close: allowed
  }
  assert.equal((await fetch(real + "/api/health")).status, 200);
});

test("random bytes come back as 200 bad_file", { skip: !hasPackages && "the Python packages are not installed" }, async () => {
  const r = await answer(await post(real, Buffer.from("this is not a photo, just some text bytes")));
  assert.deepEqual([r.status, r.json], [200, { status: "bad_file" }]);
});

test("without Python the answer is 500 with the fixed message and no path", async () => {
  const r = await answer(await post(broken, Buffer.from("bytes")));
  assert.deepEqual([r.status, r.json], [500, { error: DOWN }]);
});

test("a crash after the start is 500 'Could not read this photo.'; a missing package is the start message", async () => {
  const r = await answer(await post(crashing, Buffer.from("bytes")));
  assert.deepEqual([r.status, r.json], [500, { error: CRASH }]);
  const m = await answer(await post(noPackage, Buffer.from("bytes")));
  assert.deepEqual([m.status, m.json], [500, { error: DOWN }]);
});

test("a second photo while one is being read is 409 'busy'", async () => {
  const first = http.request(broken + "/api/star-fix", { method: "POST" });   // the body is not finished yet
  const firstDone = new Promise((ok) => first.on("response", (res) => { res.resume(); res.on("end", () => ok(res.statusCode)); }));
  first.write("part of a photo");
  await new Promise((r) => setTimeout(r, 200));
  const r = await answer(await post(broken, Buffer.from("another photo")));
  assert.deepEqual([r.status, r.json], [409, { error: "busy" }]);
  first.end(" and the rest");
  assert.equal(await firstDone, 500);
  assert.equal((await answer(await post(broken, Buffer.from("again")))).status, 500, "the slot is free again");
});

test("server.js looks for Python as fields.js does: no python3 literal (A9, issue #27)", () => {
  const src = fs.readFileSync(path.join(ROOT, "server.js"), "utf8");
  assert.doesNotMatch(src, /python3/);
  assert.match(src, /const PY = process\.env\.WANDERERS_PY \|\| pickPython\(__dirname\);/);
  assert.match(src, /\{[^}]*\bpickPython\b[^}]*\} = require\("\.\/fields"\)/);
});
