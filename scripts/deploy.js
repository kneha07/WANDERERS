#!/usr/bin/env node
// Deploy WANDERERS. See docs/deploy.md for which way to pick.
//   node scripts/deploy.js check              check that app/ has its entry pages (no network)
//   node scripts/deploy.js static             publish app/ to the Cloudflare Worker in wrangler.jsonc (free)
//   node scripts/deploy.js tunnel [port]      share the full app on this computer through a Cloudflare tunnel
// For tunnel, start the app first (node start.js). With no TUNNEL_TOKEN_FILE it makes a free quick tunnel with a
// random https://*.trycloudflare.com address; with TUNNEL_TOKEN_FILE it runs your named tunnel (fixed hostname).
"use strict";
const { spawnSync } = require("child_process"), fs = require("fs"), path = require("path");
const ROOT = path.join(__dirname, ".."), WIN = process.platform === "win32";
// The same list as .github/workflows/pages.yml
const ENTRY = ["index.html", "observatory.html", "compass.html", "stories.html", "survey.html", "sw.js", "data/index.json"];

const missing = (appDir = path.join(ROOT, "app")) =>
  ENTRY.filter((f) => !(fs.existsSync(path.join(appDir, f)) && fs.statSync(path.join(appDir, f)).size > 0));

function cloudflared() {   // winget puts it here and the PATH of an open shell does not have it yet
  const win = ["C:/Program Files (x86)/cloudflared/cloudflared.exe", "C:/Program Files/cloudflared/cloudflared.exe"];
  return (WIN && win.find((p) => fs.existsSync(p))) || "cloudflared";
}

// npx is npx.cmd on Windows and needs a shell: pass one string (fixed words only, so nothing to escape), as start.js does
const run = (cmd, args) => (cmd === "npx"
  ? spawnSync(`npx ${args.join(" ")}`, { cwd: ROOT, stdio: "inherit", shell: true })
  : spawnSync(cmd, args, { cwd: ROOT, stdio: "inherit" })).status ?? 1;

async function main([mode, port = "8000"]) {
  if (mode === "check" || mode === "static") {
    const m = missing();
    if (m.length) { console.error("app/ is missing: " + m.join(", ")); return 1; }
    console.log("app/ has its entry pages.");
    if (mode === "check") return 0;
    return run("npx", ["-y", "wrangler@4", "deploy"]);   // reads wrangler.jsonc; asks you to log in the first time
  }
  if (mode === "tunnel") {
    const url = `http://localhost:${port}`;
    const up = await fetch(url + "/api/health").then((r) => r.ok, () => false);
    if (!up) { console.error(`Nothing answers at ${url}/api/health. Start the app first: node start.js`); return 1; }
    const tok = process.env.TUNNEL_TOKEN_FILE;
    const args = tok ? ["tunnel", "--no-autoupdate", "run", "--token-file", tok] : ["tunnel", "--no-autoupdate", "--url", url];
    console.log(tok ? "Running your named tunnel. Ctrl+C stops it." : "Look for the https://….trycloudflare.com line below. Ctrl+C stops it.");
    const code = run(cloudflared(), args);
    if (code !== 0 && code !== 130) console.error("cloudflared failed. Install it: winget install Cloudflare.cloudflared (or brew install cloudflared)");
    return code;
  }
  console.error("Usage: node scripts/deploy.js check | static | tunnel [port]");
  return 2;
}

if (require.main === module) main(process.argv.slice(2)).then((c) => process.exit(c));
module.exports = { missing, ENTRY };
