#!/usr/bin/env node
// One-click boot for WANDERERS and its live "Explore any patch" mode.
//   node start.js [--precompute] [--no-open]   (or double-click start.cmd on Windows, start.command on macOS)
// 1. Sets up backend/.venv, the root .venv (on-demand fields) and web/ when they are missing or out of date.
// 2. Starts the live SPHEREx API (port 8001) and server.js (port 8000), or reuses ours if they already run.
// 3. Waits for both, then opens http://localhost:8000. Ctrl+C (or closing the window) stops both.
// Needs Node.js and Python 3.11+. No npm packages beyond web/'s own.
// PORT and LIVE_PORT (default 8000 and 8001) let a second copy run next to the first one.
const { spawn, spawnSync } = require("child_process"), fs = require("fs"), path = require("path");
const http = require("http"), net = require("net"), readline = require("readline");
const ROOT = __dirname, WEB = path.join(ROOT, "web"), WIN = process.platform === "win32";
const VENV_PY = path.join(ROOT, "backend", ".venv", WIN ? "Scripts\\python.exe" : "bin/python");
// The teammates' on-demand fields (fields.js -> pipeline/fetch.py) need their own packages in the root .venv.
const PIPE_PY = path.join(ROOT, ".venv", WIN ? "Scripts\\python.exe" : "bin/python");
const PIPE_REQ = path.join(ROOT, "pipeline", "requirements.txt");
const PORT = Number(process.env.PORT) || 8000, LIVE_PORT = Number(process.env.LIVE_PORT) || 8001;
const APP_URL = `http://localhost:${PORT}`, API_HEALTH = `http://127.0.0.1:${LIVE_PORT}/api/health`;
const kids = [];
let stopping = false;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const step = (msg) => console.log(`\n== ${msg}`);

function run(cmd, argv, { cwd = ROOT, soft = false } = {}) {
  console.log(`> ${cmd} ${argv.join(" ")}`);
  // npm is npm.cmd on Windows and needs a shell: pass one string (fixed words only, so nothing to escape)
  const r = WIN && cmd === "npm"
    ? spawnSync(`npm ${argv.join(" ")}`, { cwd, stdio: "inherit", shell: true })
    : spawnSync(cmd, argv, { cwd, stdio: "inherit" });
  if (r.status === 0) return true;
  if (soft) { console.log(`(continuing: "${cmd} ${argv.join(" ")}" failed)`); return false; }
  console.error(`Failed: ${cmd} ${argv.join(" ")}`);
  process.exit(1);
}

function findPython() {
  for (const [cmd, pre] of [["python3", []], ["python", []], ["py", ["-3"]]]) {
    const r = spawnSync(cmd, [...pre, "-c", "import sys; print(sys.version_info >= (3, 11))"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "True") return [cmd, pre];
  }
  return null;
}

function newestMtime(p) {
  const s = fs.statSync(p);
  if (!s.isDirectory()) return s.mtimeMs;
  return Math.max(s.mtimeMs, ...fs.readdirSync(p).map((f) => newestMtime(path.join(p, f))));
}

function get(url, timeout = 1500) {
  return new Promise((ok) => {
    const req = http.get(url, { timeout }, (res) => {
      let body = ""; res.on("data", (c) => (body += c)); res.on("end", () => ok({ status: res.statusCode, body }));
    });
    req.on("timeout", () => req.destroy()); req.on("error", () => ok(null));
  });
}

const listening = (port) => new Promise((ok) => {
  const s = net.connect(port, "127.0.0.1");
  s.once("connect", () => { s.destroy(); ok(true); }); s.once("error", () => ok(false));
});

async function isOurs(port) {
  if (port === LIVE_PORT) { const r = await get(API_HEALTH); return !!r && r.status === 200 && r.body.includes('"ok"'); }
  const [h, home] = await Promise.all([get(`http://127.0.0.1:${PORT}/api/health`), get(`http://127.0.0.1:${PORT}/`)]);
  return !!h && h.body.trim() === "ok" && !!home && home.body.includes("WANDERERS");
}

function start(name, cmd, argv, env = process.env) {
  const p = spawn(cmd, argv, { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] });
  for (const s of [p.stdout, p.stderr]) readline.createInterface({ input: s }).on("line", (l) => console.log(`[${name}] ${l}`));
  p.on("exit", (code) => { if (!stopping) { console.log(`[${name}] stopped (exit ${code}); stopping the rest.`); shutdown(1); } });
  kids.push(p);
}

function killKids() {
  for (const p of kids) {
    if (p.exitCode !== null || p.signalCode) continue;
    // /T: the venv python.exe on Windows is a launcher with a child interpreter; kill the whole tree.
    if (WIN) spawnSync("taskkill", ["/pid", String(p.pid), "/T", "/F"], { stdio: "ignore" });
    else p.kill("SIGTERM");
  }
}

function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  console.log("\nStopping the servers…");
  killKids();
  process.exit(code);
}
process.on("SIGINT", () => shutdown(0)); // Ctrl+C
process.on("SIGTERM", () => shutdown(0));
process.on("SIGHUP", () => shutdown(0)); // Windows: the console window was closed
process.on("exit", killKids); // last resort: never leave orphans

function openBrowser(url) {
  const [cmd, argv] = WIN ? ["cmd", ["/c", "start", "", url]] : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
  spawn(cmd, argv, { stdio: "ignore", detached: true }).on("error", () => console.log(`Open ${url} in your browser.`)).unref();
}

(async () => {
  if (!fs.existsSync(VENV_PY)) {
    step("Setting up the Python environment (backend/.venv), once");
    const py = findPython();
    if (!py) { console.error("Python 3.11 or newer is needed: https://www.python.org/downloads/"); process.exit(1); }
    run(py[0], [...py[1], "-m", "venv", path.join("backend", ".venv")]);
    run(VENV_PY, ["-m", "pip", "install", "-r", path.join("backend", "requirements.txt")]);
  }
  // The root .venv: without it a field job for new coordinates fails ("No module named 'pyvo'") and Star Fix
  // cannot read photos. Checked by importing pyvo, pillow_heif and tetra3, so a broken, half-done or older
  // install is repaired on the next start.
  if (!fs.existsSync(PIPE_REQ)) console.log("\n(No pipeline/requirements.txt: skipping the root .venv; on-demand fields are off.)");
  else if (!fs.existsSync(PIPE_PY) || spawnSync(PIPE_PY, ["-c", "import pyvo, pillow_heif, tetra3"], { stdio: "ignore" }).status !== 0) {
    step("Setting up the Python environment for on-demand fields and Star Fix (.venv, pipeline/requirements.txt), once");
    const py = fs.existsSync(PIPE_PY) ? [PIPE_PY, []] : findPython();
    if (!py) console.log("(Python 3.11 or newer is needed for on-demand fields; the rest works without it.)");
    else if (py[0] === PIPE_PY || run(py[0], [...py[1], "-m", "venv", ".venv"], { soft: true })) {
      run(PIPE_PY, ["-m", "pip", "install", "-r", PIPE_REQ], { soft: true });
      // The Star Fix solver. Its old Pillow pin makes pip build Pillow from source, which fails on Windows;
      // what it really needs (numpy, scipy, pillow) is in requirements.txt.
      run(PIPE_PY, ["-m", "pip", "install", "--no-deps", "cedar-solve==0.5.1"], { soft: true });
    }
  }
  if (!fs.existsSync(path.join(WEB, "node_modules"))) {
    step("Installing the web app packages (web/node_modules), once");
    run("npm", ["ci"], { cwd: WEB });
  }
  const dist = path.join(WEB, "dist", "index.html");
  const sources = ["src", "index.html", "vite.config.ts", "package.json"].map((f) => path.join(WEB, f));
  if (!fs.existsSync(dist) || Math.max(...sources.map(newestMtime)) > fs.statSync(dist).mtimeMs) {
    step("Building the explorer (web/dist)");
    run("npm", ["run", "build"], { cwd: WEB });
  }
  if (process.argv.includes("--precompute")) {
    step("Precomputing the five challenge targets (a few minutes the first time)");
    run(VENV_PY, ["-m", "backend.precompute"], { soft: true });
  }

  step("Starting the servers");
  // fields.js looks only for .venv/bin/python, so on Windows it is told where the root venv's python is.
  const webEnv = { ...process.env, PORT: String(PORT), WANDERERS_LIVE: `http://127.0.0.1:${LIVE_PORT}` };
  if (fs.existsSync(PIPE_PY)) Object.assign(webEnv, { WANDERERS_PYTHON: process.env.WANDERERS_PYTHON || PIPE_PY, WANDERERS_PY: process.env.WANDERERS_PY || PIPE_PY });
  for (const [port, name, cmd, argv, env] of [
    [LIVE_PORT, "api", VENV_PY, ["-m", "uvicorn", "backend.app:app", "--port", String(LIVE_PORT)]],
    [PORT, "web", process.execPath, [path.join(ROOT, "server.js")], webEnv],
  ]) {
    if (!(await listening(port))) start(name, cmd, argv, env);
    else if (await isOurs(port)) console.log(`Port ${port}: our server already runs; reusing it.`);
    else {
      console.error(`Port ${port} is in use by another program. Stop that program (or free the port), then run start.js again.`);
      shutdown(1);
    }
  }

  const t0 = Date.now();
  while (!((await get(API_HEALTH)) && (await get(`http://127.0.0.1:${PORT}/`)))) {
    if (Date.now() - t0 > 60000) {
      console.error("The servers did not answer within 60 s. Read the [api] and [web] lines above for the reason.");
      shutdown(1);
    }
    await sleep(500);
  }
  console.log(`\nReady: ${APP_URL}  (live explorer: ${APP_URL}/explore/)`);
  if (!process.argv.includes("--no-open")) openBrowser(APP_URL);
  if (kids.length) console.log("Press Ctrl+C to stop.");
})();
