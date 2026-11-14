// Local demo server for WANDERERS.
//   node server.js            then open http://localhost:8000
// Serves app/ as static files and adds POST /api/ask, which answers free-text questions with the
// Claude Code CLI in headless mode (`claude -p`): no API key needed, it uses your Claude Code login.
// Bound to 127.0.0.1 only. The deployed static site works without this server (pre-written answers).
const http = require("http"), fs = require("fs"), path = require("path"), { execFile, spawn } = require("child_process");
const ROOT = path.join(__dirname, "app"), PORT = process.env.PORT || 8000;
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
    } catch (e) { res.writeHead(400); res.end(JSON.stringify({ error: String(e.message || e) })); }
    return;
  }
  // static files, no directory traversal
  let p = path.normalize(path.join(ROOT, decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname)));
  if (!p.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "content-type": TYPES[path.extname(p)] || "application/octet-stream" }); res.end(data);
  });
}).listen(PORT, "127.0.0.1", () => console.log(`WANDERERS on http://localhost:${PORT}  (live Ask uses claude -p)`));
