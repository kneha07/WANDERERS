// Local demo server for WANDERERS.
//   node server.js            then open http://localhost:8000
// Serves app/ as static files and adds POST /api/ask, which answers free-text questions with the
// Claude Code CLI in headless mode (`claude -p`): no API key needed, it uses your Claude Code login.
// Bound to 127.0.0.1 only. The deployed static site works without this server (pre-written answers).
const http = require("http"), fs = require("fs"), path = require("path"), { execFile } = require("child_process");
const ROOT = path.join(__dirname, "app"), PORT = process.env.PORT || 8000;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml" };
const RULES = `You are the analyst inside WANDERERS, a public tool built on real NASA SPHEREx and WISE images and ESA Gaia data.
Use ONLY the measurements in the JSON below plus textbook astronomy background. Never say "discovery".
If something is flagged or uncertain, say so. Plain language, at most 90 words, no markdown.`;

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
