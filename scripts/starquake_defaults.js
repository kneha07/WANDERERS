// Pre-make the starquake sound of every default star (the analysed targets and the stars with ready profiles),
// so the page can play them instantly; any other star is generated in the browser when it is opened.
// Writes app/data/starquake/model/<key>.wav (12 s, 8 kHz, 16-bit), index.json, and targets.json (target id -> star key).
// Run from the repository root:  node scripts/starquake_defaults.js
const fs = require("fs"), path = require("path");
const Q = require("../app/starquake.js");
const ROOT = path.join(__dirname, "..", "app", "data");
const INFO = require(path.join(ROOT, "starquake_stars.json"));
const STARS = require(path.join(ROOT, "stars", "index.json")).stars;
const OUT = path.join(ROOT, "starquake", "model");
const FS = 8000, LOG2N = 17;                                  // 16.4 s synthesised, first 12 s kept
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

// target id -> star key (by name, else by the star index's WANDERERS tag)
const targets = {};
for (const t of require(path.join(ROOT, "index.json"))) {
  const s = STARS.find((x) => norm(x.name) === norm(t.name) || (x.aliases || []).some((a) => norm(a) === norm(t.name))) || STARS.find((x) => x.wanderers === t.id);
  if (s) targets[t.id] = s.key;
}
const profiles = fs.existsSync(path.join(ROOT, "stars", "profile", "index.json")) ? require(path.join(ROOT, "stars", "profile", "index.json")) : [];
const keys = [...new Set(["sun", ...Object.values(targets), ...profiles])];
fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const made = [];
keys.forEach((key, i) => {
  const pf = path.join(ROOT, "stars", "profile", `${key}.json`), prof = fs.existsSync(pf) ? JSON.parse(fs.readFileSync(pf, "utf8")) : null;
  const d = Q.describe(Q.withProfile(INFO[key] || null, prof), STARS.find((s) => s.key === key) || null);   // same inputs as the page
  if (d.kind === "none") return console.log(`   ${key}: no starquakes (${d.why.slice(0, 50)}…)`);
  const sp = Q.speedupFor(d.numax), s = Q.synth(Q.modes(d), { speedup: sp.speedup, fs: FS, log2n: LOG2N, seed: 1 }).samples.slice(0, 12 * FS);
  const fade = Math.floor(0.4 * FS); for (let j = 0; j < fade; j++) s[s.length - 1 - j] *= j / fade;
  fs.writeFileSync(path.join(OUT, `${key}.wav`), Buffer.from(Q.wav(s, FS)));
  made.push(key); console.log(`${key.padEnd(24)} ${d.kind.padEnd(9)} ${sp.hz.toFixed(0).padStart(4)} Hz`);
});
fs.writeFileSync(path.join(OUT, "index.json"), JSON.stringify(made.sort()));
fs.writeFileSync(path.join(ROOT, "starquake", "targets.json"), JSON.stringify(targets, null, 1));
console.log(`made ${made.length} sounds; ${Object.keys(targets).length} targets mapped`);
