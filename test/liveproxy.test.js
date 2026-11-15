// Tests for the live-mode proxy in server.js (/api/frames, /api/resolve, /api/about, /api/live-health -> FastAPI).
// A fake upstream stands in for the FastAPI server, so no Python and no network are needed.
// Run from the repository root:  node --test test/liveproxy.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http"), path = require("node:path"), { spawn } = require("node:child_process");

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const listen = (server) => new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server.address().port)));

// The fake upstream: echoes the path it got; for q=drop it sends the headers and part of the body, then dies.
function upstream() {
  return http.createServer((req, res) => {
    if (req.url.includes("q=drop")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.write('{"frames": [');
      return setTimeout(() => req.socket.destroy(), 50);
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ path: req.url }));
  });
}

async function withProxy(live, fn) {
  const port = 20000 + Math.floor(Math.random() * 20000), base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, ["server.js"], { env: { ...process.env, PORT: String(port), WANDERERS_LIVE: live }, stdio: "ignore", cwd: path.join(__dirname, "..") });
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

test("proxy: an upstream that dies mid-answer ends the browser's response instead of leaving it open", async () => {
  const fake = upstream(), port = await listen(fake);
  try {
    await withProxy(`http://127.0.0.1:${port}`, async (base) => {
      const res = await fetch(base + "/api/frames?q=drop", { signal: AbortSignal.timeout(5000) });
      const outcome = await res.text().then(() => "completed", (e) => (e.name === "TimeoutError" ? "hung" : "broken"));
      assert.equal(outcome, "broken");
    });
  } finally { fake.close(); }
});

test("proxy: /api/frames, /api/resolve and /api/about go to the live API with their query", async () => {
  const fake = upstream(), port = await listen(fake);
  try {
    await withProxy(`http://127.0.0.1:${port}`, async (base) => {
      for (const p of ["/api/frames?q=R%20Dra&fov=5", "/api/resolve?q=Wolf%20359", "/api/about?ra=10.5&dec=-2"])
        assert.deepEqual(await (await fetch(base + p)).json(), { path: p });
      assert.deepEqual(await (await fetch(base + "/api/live-health")).json(), { path: "/api/health" });
    });
  } finally { fake.close(); }
});

test("proxy: a live API that is not running gives 502 with a JSON detail", async () => {
  const gone = http.createServer(), closed = await listen(gone);
  await new Promise((ok) => gone.close(ok));   // a free port: nothing listens there now
  await withProxy(`http://127.0.0.1:${closed}`, async (base) => {
    const res = await fetch(base + "/api/frames?q=x");
    assert.equal(res.status, 502);
    assert.match((await res.json()).detail, /live SPHEREx server is not running/);
  });
});

test("proxy: a browser that leaves before a slow answer arrives does not crash the server (NH1)", async () => {
  // The live API answers after 800 ms; the browser gives up after 200 ms (a target switch during a cold load).
  const slow = http.createServer((req, res) => setTimeout(() => {
    if (res.destroyed) return;
    res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify({ path: req.url }));
  }, 800));
  const port = await listen(slow);
  try {
    await withProxy(`http://127.0.0.1:${port}`, async (base) => {
      await assert.rejects(fetch(base + "/api/frames?q=Gliese+445", { signal: AbortSignal.timeout(200) }));
      await wait(1200); // the slow answer arrives after the browser left
      assert.equal((await fetch(base + "/api/health")).status, 200);
      assert.deepEqual(await (await fetch(base + "/api/frames?q=R%20Dra")).json(), { path: "/api/frames?q=R%20Dra" });
    });
  } finally { slow.close(); }
});
