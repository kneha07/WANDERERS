// Local demo server for WANDERERS.
//   node server.js            then open http://localhost:8000
// Serves app/ as static files and adds POST /api/ask, which answers free-text questions with the
// Claude Code CLI in headless mode (`claude -p`): no API key needed, it uses your Claude Code login.
// Bound to 127.0.0.1 only. The deployed static site works without this server (pre-written answers).
const http = require("http"), fs = require("fs"), path = require("path"), { execFile, spawn } = require("child_process");
const { pipeline } = require("stream");
const ROOT = path.join(__dirname, "app"), PORT = process.env.PORT || 8000;
const fields = require("./fields").createFieldService();
// "Explore any patch" live mode: the React app (web/, built to web/dist) and its FastAPI server (backend/, port 8001).
const EXPLORE = path.join(__dirname, "web", "dist"), LIVE = process.env.WANDERERS_LIVE || "http://127.0.0.1:8001";
const LIVE_ROUTES = new Set(["/api/frames", "/api/resolve", "/api/about"]);
const LIVE_DOWN = "The live SPHEREx server is not running. Start it with: node start.js " +
  "(or: backend/.venv/bin/python -m uvicorn backend.app:app --port 8001).";
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml" };
const RULES = `You are the analyst inside WANDERERS, a public tool built on real NASA SPHEREx and WISE images and ESA Gaia data.
Use ONLY the measurements in the JSON below plus textbook astronomy background. Never say "discovery".
If something is flagged or uncertain, say so. Plain language, at most 90 words, no markdown.`;

// ---- live lookup of any sky position: runs the pipeline as a background job ----
const PY = process.env.WANDERERS_PY || (fs.existsSync(path.join(__dirname, ".venv/bin/python")) ? path.join(__dirname, ".venv/bin/python") : "python3");
const jobs = new Map(); let jobSeq = 0, busy = null;

function runStep(job, args) {
  return new Promise((ok, bad) => {
    const p = spawn(PY, args, { cwd: __dirname });
    const onData = (d) => d.toString().split("\n").map((l) => l.trim()).filter((l) => l && !/retry|INFO|WARNING/i.test(l))
      .forEach((l) => { job.log.push(l); const m = l.match(/target id: (\S+)/); if (m) job.id = m[1]; });
    p.stdout.on("data", onData); p.stderr.on("data", onData);
    p.on("close", (code) => (code === 0 ? ok() : bad(new Error(`step failed (${args[0]})`))));
  });
}

async function lookup(job, ra, dec, fov = 300) {
  try {
    job.log.push(`Finding SPHEREx, WISE and Gaia data at RA ${ra.toFixed(4)}, Dec ${dec.toFixed(4)}…`);
    await runStep(job, ["-u", "pipeline/fetch.py", "--ra", String(ra), "--dec", String(dec), "--max", "36", "--fov", String(fov)]);
    if (!job.id) throw new Error("no target id");
    job.log.push("Measuring motion, spectrum and brightness…");
    await runStep(job, ["-u", "pipeline/analyze.py", job.id]);
    await runStep(job, ["-u", "pipeline/evidence.py"]);
    job.status = "done";
  } catch (e) { job.status = "error"; job.log.push(String(e.message || e)); }
  finally { busy = null; }
}

// ---- star database: learn one star's path with pipeline/star_ml.py (one at a time) ----
const starJobs = new Map(); let starSeq = 0, starBusy = null, starKeys = null;
function knownStarKeys() {
  if (!starKeys) {
    try { starKeys = new Set(JSON.parse(fs.readFileSync(path.join(ROOT, "data", "stars", "index.json"), "utf8")).stars.map((s) => s.key)); }
    catch { starKeys = new Set(); }
  }
  return starKeys;
}
function learnStar(job, key) {
  const p = spawn(PY, ["-u", "pipeline/star_ml.py", key], { cwd: __dirname });
  const onData = (d) => d.toString().split("\n").map((l) => l.trim()).filter(Boolean)
    .forEach((l) => job.log.push(l.replace(/^==\s*/, "").replace(/^!!\s*/, "")));
  p.stdout.on("data", onData); p.stderr.on("data", () => {});
  p.on("close", (code) => {
    job.status = code === 0 && fs.existsSync(path.join(ROOT, "data", "stars", "pred", key + ".json")) ? "done" : "error";
    if (job.status === "error" && !job.log.length) job.log.push("the model could not be fitted");
    starBusy = null;
  });
}

function slim(t) {
  const keep = ["name", "kind", "reference", "target_in_gaia", "motion", "variability", "ir_color",
    "spectrum_points", "flagged_points", "spherex_visits", "evidence"];
  const o = {}; for (const k of keep) o[k] = t[k];
  o.spectrum_summary = (t.spectrum || []).filter((_, i) => i % 3 === 0);
  return o;
}

function body(req, limit = 20000) {
  return new Promise((ok, bad) => {
    let n = 0, chunks = [];
    req.on("data", (c) => { n += c.length; if (n > limit) { bad(new Error("too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => ok(Buffer.concat(chunks).toString())); req.on("error", bad);
  });
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/api/health") { res.writeHead(200); return res.end("ok"); }
  if (req.method === "POST" && url.pathname === "/api/lookup") {
    res.setHeader("content-type", "application/json");
    try {
      const { ra, dec, fov } = JSON.parse(await body(req));
      const f = [300, 600, 900].includes(Number(fov)) ? Number(fov) : 300;
      const a = Number(ra), d = Number(dec);
      if (!Number.isFinite(a) || !Number.isFinite(d) || a < 0 || a >= 360 || d < -90 || d > 90) throw new Error("RA must be 0-360 and Dec -90 to 90 degrees");
      if (busy) { res.writeHead(409); return res.end(JSON.stringify({ error: "Another lookup is running", job: busy })); }
      const n = String(++jobSeq), job = { status: "running", log: [], id: null, started: Date.now() };
      jobs.set(n, job); busy = n; lookup(job, a, d, f);
      res.writeHead(202); return res.end(JSON.stringify({ job: n }));
    } catch (e) { res.writeHead(400); return res.end(JSON.stringify({ error: String(e.message || e) })); }
  }
  if (url.pathname.startsWith("/api/job/")) {
    const job = jobs.get(url.pathname.slice(9));
    res.writeHead(job ? 200 : 404, { "content-type": "application/json" });
    return res.end(JSON.stringify(job ? { status: job.status, id: job.id, log: job.log.slice(-8), seconds: Math.round((Date.now() - job.started) / 1000) } : { error: "no such job" }));
  }
  if (req.method === "POST" && url.pathname === "/api/star-predict") {
    res.setHeader("content-type", "application/json");
    try {
      const { key } = JSON.parse(await body(req, 500));
      if (!/^[a-z0-9_]{1,40}$/.test(key || "") || !knownStarKeys().has(key)) throw new Error("unknown star");
      if (starBusy) { res.writeHead(409); return res.end(JSON.stringify({ error: "Another star is being learnt; try again in a minute", job: starBusy })); }
      const n = String(++starSeq), job = { status: "running", log: [], started: Date.now() };
      starJobs.set(n, job); starBusy = n; learnStar(job, key);
      res.writeHead(202); return res.end(JSON.stringify({ job: n }));
    } catch (e) { res.writeHead(400); return res.end(JSON.stringify({ error: e instanceof SyntaxError ? "bad JSON" : String(e.message || e) })); }
  }
  if (url.pathname.startsWith("/api/star-job/")) {
    const job = starJobs.get(url.pathname.slice(14));
    res.writeHead(job ? 200 : 404, { "content-type": "application/json" });
    return res.end(JSON.stringify(job ? { status: job.status, log: job.log.slice(-6), seconds: Math.round((Date.now() - job.started) / 1000) } : { error: "no such job" }));
  }
  if (fields.handle(req, res, url)) return;   // /api/field and /api/job: prepare new sky patches on demand
  if (req.method === "POST" && url.pathname === "/api/ask") {
    res.setHeader("content-type", "application/json");
    try {
      const { target, question } = JSON.parse(await body(req));
      if (!/^[a-z0-9_]+$/.test(target || "") || typeof question !== "string" || !question.trim() || question.length > 500)
        throw new Error("bad request");
      const t = JSON.parse(fs.readFileSync(path.join(ROOT, "data", target, "target.json"), "utf8"));
      const prompt = `${RULES}\nMeasurements:\n${JSON.stringify(slim(t))}\n\nQuestion: ${question}`;
      execFile("claude", ["-p", prompt, "--output-format", "text"], { timeout: 120000, maxBuffer: 1e6 }, (err, out, errOut) => {
        if (err) { res.writeHead(502); return res.end(JSON.stringify({ error: "Claude CLI failed: " + (errOut || err.message).slice(0, 200) })); }
        res.writeHead(200); res.end(JSON.stringify({ answer: out.trim() }));
      });
    } catch (e) {   // never send fs errors (they hold server paths) to the client
      if (e.code === "ENOENT") { res.writeHead(404); return res.end(JSON.stringify({ error: "unknown target" })); }
      res.writeHead(400); res.end(JSON.stringify({ error: e instanceof SyntaxError ? "bad JSON" : String(e.message || e) }));
    }
    return;
  }
  // live mode API: proxy to the FastAPI server; /api/live-health maps to its /api/health
  if (req.method === "GET" && (LIVE_ROUTES.has(url.pathname) || url.pathname === "/api/live-health")) {
    const target = LIVE + (LIVE_ROUTES.has(url.pathname) ? url.pathname + url.search : "/api/health");
    // pipeline, not pipe: if the backend dies mid-answer the browser's response is destroyed (no endless wait).
    // A browser that leaves (a new target during a cold load) aborts the upstream request; an answer that still
    // arrives is dropped. No error here may escape: one would stop the whole server.
    const up = http.get(target, (r) => {
      if (res.destroyed || res.writableEnded) return r.destroy();
      res.writeHead(r.statusCode, { "content-type": r.headers["content-type"] || "application/json" });
      pipeline(r, res, () => {});   // premature close of either side: both are destroyed, nothing is thrown
    });
    up.on("error", () => {
      if (res.destroyed || res.writableEnded) return;
      if (res.headersSent) return res.destroy();
      res.writeHead(502, { "content-type": "application/json" }); res.end(JSON.stringify({ detail: LIVE_DOWN }));
    });
    res.on("close", () => { if (!res.writableFinished) up.destroy(); });
    return;
  }
  // live mode app: web/dist under /explore/, no directory traversal, unknown routes fall back to index.html
  if (url.pathname === "/explore") { res.writeHead(301, { location: "/explore/" + url.search }); return res.end(); }
  if (url.pathname.startsWith("/explore/")) {
    let rel; try { rel = decodeURIComponent(url.pathname.slice("/explore".length)); } catch { res.writeHead(400); return res.end("bad url"); }
    const f = path.normalize(path.join(EXPLORE, rel));
    if (f !== EXPLORE && !f.startsWith(EXPLORE + path.sep)) { res.writeHead(403); return res.end(); }
    const send = (file, fallback) => fs.readFile(file, (err, data) => {
      if (!err) { res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" }); return res.end(data); }
      if (fallback) return send(path.join(EXPLORE, "index.html"), false);
      res.writeHead(404); res.end("not found (build the live explorer first: npm run build in web/, or node start.js)");
    });
    return send(f, !path.extname(f) || f === EXPLORE);
  }
  // static files, no directory traversal
  let p;
  try { p = path.normalize(path.join(ROOT, decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname))); }
  catch { res.writeHead(400); return res.end("bad URL"); }   // malformed %-escape must not crash the server
  if (!p.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "content-type": TYPES[path.extname(p)] || "application/octet-stream" }); res.end(data);
  });
}).listen(PORT, "127.0.0.1", () => console.log(`WANDERERS on http://localhost:${PORT}  (live Ask uses claude -p)`));
