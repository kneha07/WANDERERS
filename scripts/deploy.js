#!/usr/bin/env node
// Deploy the WANDERERS static site (app/). Two methods; see docs/deploy.md.
//   node scripts/deploy.js check         check that app/ has its entry pages (no network)
//   node scripts/deploy.js pages         start the GitHub Pages workflow for main (needs gh, logged in)
//   node scripts/deploy.js cloudflare    publish app/ to the Cloudflare Worker in wrangler.jsonc (needs a Cloudflare login)
"use strict";
const { spawnSync } = require("child_process"), fs = require("fs"), path = require("path");
const ROOT = path.join(__dirname, "..");
// The same list as .github/workflows/pages.yml
const ENTRY = ["index.html", "observatory.html", "compass.html", "stories.html", "survey.html", "sw.js", "data/index.json"];

const missing = (appDir = path.join(ROOT, "app")) =>
  ENTRY.filter((f) => !(fs.existsSync(path.join(appDir, f)) && fs.statSync(path.join(appDir, f)).size > 0));

// npx is npx.cmd on Windows and needs a shell: pass one string (fixed words only, so nothing to escape), as start.js does
const run = (cmd, args, quiet = false) => {
  const io = quiet ? "ignore" : "inherit";
  const r = cmd === "npx" ? spawnSync(`npx ${args.join(" ")}`, { cwd: ROOT, stdio: io, shell: true })
    : spawnSync(cmd, args, { cwd: ROOT, stdio: io });
  return r.error ? 127 : r.status ?? 1;
};

function pages() {
  if (run("gh", ["--version"], true) === 127) { console.error("Install the GitHub CLI (gh) and run: gh auth login"); return 1; }
  if (run("gh", ["api", "repos/{owner}/{repo}/pages"], true) !== 0) {
    console.error("GitHub Pages is not on for this repository. A repository admin turns it on once:\n" +
      "  Settings -> Pages -> Build and deployment -> Source: GitHub Actions");
    return 1;
  }
  // The workflow also runs by itself on each push to main; this starts it now, for main
  if (run("gh", ["workflow", "run", "pages.yml", "--ref", "main"]) !== 0) return 1;
  console.log("Started. Follow it with: gh run watch   (the site is at the address in Settings -> Pages)");
  return 0;
}

function main([mode]) {
  if (!["check", "pages", "cloudflare"].includes(mode)) {
    console.error("Usage: node scripts/deploy.js check | pages | cloudflare");
    return 2;
  }
  const m = missing();
  if (m.length) { console.error("app/ is missing: " + m.join(", ")); return 1; }
  console.log("app/ has its entry pages.");
  if (mode === "pages") return pages();
  if (mode === "cloudflare") return run("npx", ["-y", "wrangler@4", "deploy"]);   // reads wrangler.jsonc
  return 0;
}

if (require.main === module) process.exit(main(process.argv.slice(2)));
module.exports = { missing, ENTRY };
