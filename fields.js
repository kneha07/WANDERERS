// On-demand sky fields for WANDERERS.
// When a user types coordinates that are not cached yet, run the existing pipeline for them
// (fetch.py --ra --dec, then analyze.py, then evidence.py) and report progress.
//
//   POST /api/field   {"ra": 133.795, "dec": -7.245, "fov": 600}  ->  {status, tid | job, stage}
//                     fov (optional) is the side of the field in arcseconds: a whole number, 60 to 900.
//   GET  /api/job?id=<job>                              ->  {status, stage, detail, tid, error}
//
// One job runs at a time (the steps write into app/data/ and rewrite index.json), a few can wait.
// Needs a local Python environment with pipeline/requirements.txt installed and network access to IRSA.
"use strict";
const { spawn } = require("child_process");
const fs = require("fs"), path = require("path");

const DEFAULT_FOV = 300, MIN_FOV = 60, MAX_FOV = 900;   // arcsec; same limits as pipeline/fov.py
const MAX_ACTIVE = 4;                 // running + waiting
const STEP_TIMEOUT_MS = 20 * 60 * 1000;
const KEEP_MS = 30 * 60 * 1000;       // how long finished jobs stay queryable

function defaultPython(root) {
  if (process.env.WANDERERS_PYTHON) return process.env.WANDERERS_PYTHON;
  const venv = path.join(root, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python3";
}

// Runs one pipeline script; resolves with its output, rejects on non-zero exit or timeout.
function realRunner(root, python) {
  return (script, args, onLine) => new Promise((resolve, reject) => {
    const p = spawn(python, [path.join(root, "pipeline", script), ...args], { cwd: root });
    let out = "";
    const timer = setTimeout(() => { p.kill(); reject(new Error(script + " timed out")); }, STEP_TIMEOUT_MS);
    const feed = (b) => { const s = b.toString(); out += s; s.split("\n").forEach((l) => l.trim() && onLine(l.trim())); };
    p.stdout.on("data", feed); p.stderr.on("data", feed);
    p.on("error", (e) => { clearTimeout(timer); reject(e); });
    p.on("close", (code) => { clearTimeout(timer); code === 0 ? resolve(out) : reject(new Error(script + " exited with code " + code)); });
  });
}

function httpError(status, message) { const e = new Error(message); e.status = status; return e; }

function createFieldService(opts = {}) {
  const root = opts.root || __dirname;
  const dataDir = opts.dataDir || path.join(root, "app", "data");
  const run = opts.run || realRunner(root, defaultPython(root));
  const jobs = new Map(), queue = [];
  let running = false;

  // Same id that pipeline/fetch.py add_position() makes (via pipeline/fov.py), so cached fields are found
  // without a job. The default field keeps the original format; other sizes get a "_f<arcsec>" suffix.
  const idFor = (ra, dec, fov = DEFAULT_FOV) =>
    `pos_${ra.toFixed(4)}_${(dec < 0 ? "-" : "+") + Math.abs(dec).toFixed(4)}`.replace(/\./g, "p").replace(/\+/g, "n").replace(/-/g, "s")
    + (fov === DEFAULT_FOV ? "" : `_f${fov}`);
  const jobKey = (ra, dec, fov = DEFAULT_FOV) => `${ra.toFixed(4)}_${dec.toFixed(4)}` + (fov === DEFAULT_FOV ? "" : `_f${fov}`);
  const hasData = (tid) => fs.existsSync(path.join(dataDir, tid, "target.json"));
  // Never show server paths to the browser.
  const clean = (s) => String(s || "").split(root).join(".").replace(/\/(Users|home)\/[^\s:]+/g, "<path>").slice(0, 200);
  const view = (j) => ({ job: j.key, status: j.status, stage: j.stage, detail: j.detail || "",
                         tid: j.status === "done" ? j.tid : undefined, error: j.status === "error" ? j.error : undefined });
  const active = () => [...jobs.values()].filter((j) => j.status === "queued" || j.status === "running").length;
  const prune = () => { const now = Date.now(); for (const [k, j] of jobs) if (j.finished && now - j.finished > KEEP_MS) jobs.delete(k); };

  async function work(j) {
    const log = (l) => { j.detail = clean(l).slice(0, 120); };
    j.status = "running"; j.stage = "Downloading images (step 1 of 3)";
    const out = await run("fetch.py", ["--ra", String(j.ra), "--dec", String(j.dec), "--fov", String(j.fov)], log);
    const m = /target id:\s*([A-Za-z0-9_]+)/.exec(out);
    if (!m) throw new Error("Could not register this position.");
    j.tid = m[1];
    j.stage = "Measuring motion and spectrum (step 2 of 3)"; j.detail = "";
    await run("analyze.py", [j.tid], log);
    // analyze.py reports per-target failures on stdout and still exits 0, so check for its output.
    if (!hasData(j.tid)) throw new Error("No usable SPHEREx data was found for these coordinates.");
    j.stage = "Building the evidence card (step 3 of 3)"; j.detail = "";
    await run("evidence.py", [], log);
    j.status = "done"; j.stage = "Ready"; j.detail = "";
  }

  async function pump() {
    if (running) return;
    const j = queue.shift();
    if (!j) return;
    running = true;
    try { await work(j); }
    catch (e) { j.status = "error"; j.stage = "Failed"; j.error = clean(e.message) || "Something went wrong."; }
    finally { running = false; j.finished = Date.now(); prune(); pump(); }
  }

  // Returns {status:"ready", tid} for cached fields, otherwise a job view.
  function start(ra, dec, fov = DEFAULT_FOV) {
    if (!Number.isFinite(ra) || !Number.isFinite(dec) || ra < 0 || ra >= 360 || dec < -90 || dec > 90)
      throw httpError(400, "RA must be 0-360 degrees and Dec -90 to 90 degrees.");
    if (!Number.isInteger(fov) || fov < MIN_FOV || fov > MAX_FOV)
      throw httpError(400, `Field of view must be a whole number of arcseconds, ${MIN_FOV} to ${MAX_FOV}.`);
    const tid = idFor(ra, dec, fov);
    if (hasData(tid)) return { status: "ready", tid };
    const key = jobKey(ra, dec, fov), old = jobs.get(key);
    if (old && old.status !== "error") return view(old);
    if (active() >= MAX_ACTIVE) throw httpError(429, "Several fields are being prepared. Try again in a few minutes.");
    const j = { key, ra, dec, fov, tid, status: "queued", stage: "Waiting in line", detail: "" };
    jobs.set(key, j); queue.push(j); pump();
    return view(j);
  }

  function status(id) {
    if (!/^[0-9.]+_-?[0-9.]+(_f[0-9]+)?$/.test(id || "")) throw httpError(400, "Bad job id.");
    const j = jobs.get(id);
    if (!j) throw httpError(404, "Unknown job.");
    return view(j);
  }

  function readJson(req, limit = 2000) {
    return new Promise((ok, bad) => {
      let n = 0, over = false; const chunks = [];
      req.on("data", (c) => {
        n += c.length;
        if (over) return;                       // keep draining, but stop storing
        if (n > limit) { over = true; chunks.length = 0; bad(httpError(413, "Request too large.")); } else chunks.push(c);
      });
      req.on("end", () => { if (over) return; try { ok(JSON.parse(Buffer.concat(chunks).toString())); } catch { bad(httpError(400, "Bad JSON.")); } });
      req.on("error", bad);
    });
  }

  // Returns true if the request was for one of our routes.
  function handle(req, res, url) {
    const send = (code, obj) => {
      // After a 413 close the connection once the reply is out, so a huge upload is not read to the end.
      res.writeHead(code, { "content-type": "application/json", ...(code === 413 ? { connection: "close" } : {}) });
      res.end(JSON.stringify(obj), () => { if (code === 413) req.destroy(); });
    };
    const fail = (e) => send(e.status || 500, { error: e.status ? e.message : "Server error." });
    if (req.method === "POST" && url.pathname === "/api/field") {
      readJson(req).then((b) => {
        if (typeof b.ra !== "number" || typeof b.dec !== "number") throw httpError(400, "ra and dec must be numbers.");
        if (b.fov !== undefined && typeof b.fov !== "number") throw httpError(400, "fov must be a number.");
        const r = start(b.ra, b.dec, b.fov === undefined ? DEFAULT_FOV : b.fov); send(r.status === "ready" ? 200 : 202, r);
      }).catch(fail);
      return true;
    }
    if (req.method === "GET" && url.pathname === "/api/job") {
      try { send(200, status(url.searchParams.get("id"))); } catch (e) { fail(e); }
      return true;
    }
    return false;
  }

  return { start, status, handle, idFor };
}

module.exports = { createFieldService };
