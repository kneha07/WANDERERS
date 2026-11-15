// Star Fix solver process: one photo (bytes) -> pipeline/star_fix.py on stdin -> {code, body} for the HTTP reply.
// The process rules live here: no shell, the photo on stdin (never on disk), a time limit that stops the whole
// process tree, the last JSON line of stdout, and which of the two 500 answers applies. server.js is the HTTP adapter.
"use strict";
const { spawn } = require("child_process");
const DOWN = "Star Fix could not run. Start the app with start.cmd.", CRASH = "Could not read this photo.";
const WIN = process.platform === "win32";

// -> Promise of {code, body, gone}. body: the JSON line (200) or an error object. gone resolves when the process has
// ended, so the caller can hold its one-at-a-time slot until then; after a timeout the answer comes first.
function solvePhoto(buf, { python, script = "pipeline/star_fix.py", cwd = __dirname, timeoutMs = 60000 }) {
  let ended;
  const gone = new Promise((ok) => (ended = ok));
  return new Promise((answer) => {
    const p = spawn(python, [script], { cwd, detached: !WIN });   // POSIX: its own process group, so a kill takes the tree
    let out = "", err = "", sent = false;
    const reply = (code, body) => { if (!sent) { sent = true; clearTimeout(timer); answer({ code, body, gone }); } };
    const timer = setTimeout(() => {
      // Windows: the venv python.exe is a launcher with a child interpreter; /T kills the whole tree, as start.js does.
      if (WIN) spawn("taskkill", ["/pid", String(p.pid), "/T", "/F"], { stdio: "ignore" }).on("error", () => {});
      else try { process.kill(-p.pid, "SIGKILL"); } catch { /* already ended */ }
      reply(504, { error: "timed out" });
    }, timeoutMs);
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => { if (err.length < 1e5) err += d; });   // the solver logs here; read only to tell the 500s apart
    p.stdin.on("error", () => {});   // Python may exit before it has read everything
    p.on("error", () => { ended(); reply(500, { error: DOWN, status: "setup" }); });   // no Python
    p.on("close", (code) => {
      ended();
      const line = out.split("\n").map((l) => l.trim()).filter((l) => l.startsWith("{")).pop();
      try { if (code === 0 && JSON.parse(line).status) return reply(200, line); } catch { /* no JSON line */ }
      reply(500, /No module named/.test(err) ? { error: DOWN, status: "setup" } : { error: CRASH });   // setup missing, or this photo
    });
    p.stdin.end(buf);
  });
}

module.exports = { solvePhoto };
