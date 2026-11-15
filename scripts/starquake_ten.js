// Ten stars' starquakes, smallest/densest (highest pitch) to largest, each from the best source we have:
// a real Kepler recording, published measurements, or a prediction from the scaling relations.
// Writes artifacts/starquakes/10_stars/NN_<name>.wav (16 s each, 8 kHz, 16-bit) and a README.md listing them.
// Run from the repository root:  node scripts/starquake_ten.js
const fs = require("fs"), path = require("path");
const Q = require("../app/starquake.js");
const INFO = require("../app/data/starquake_stars.json");
const STARS = require("../app/data/stars/index.json").stars;
const OUT = path.join(__dirname, "..", "artifacts", "starquakes", "10_stars");
const FS = 8000, LOG2N = 17;                                     // 2^17 samples at 8 kHz = 16.4 s

// [label, star-database key or starquake_stars.json key]
const PICK = [
  ["Barnard's Star", "hip87937"], ["61 Cygni A", "hip104214"], ["Tau Ceti", "hip8102"], ["Alpha Centauri B", "hip71681"],
  ["KIC 8006161", "kic8006161"], ["The Sun", "sun"], ["Alpha Centauri A", "hip71683"], ["KIC 6106415", "kic6106415"],
  ["Procyon", "hip37279"], ["Arcturus", "hip69673"],
];

function readWav(file) {                                          // our own 16-bit mono PCM files
  const b = fs.readFileSync(file), fs0 = b.readUInt32LE(24);
  let off = 12; while (b.toString("ascii", off, off + 4) !== "data") off += 8 + b.readUInt32LE(off + 4);
  const n = b.readUInt32LE(off + 4) / 2, x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = b.readInt16LE(off + 8 + 2 * i) / 32768;
  return { x, fs: fs0 };
}

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });
const rows = [];
PICK.forEach(([label, key], i) => {
  const info = INFO[key] || null, row = STARS.find((s) => s.key === key) || null;
  const d = Q.describe(info, row);
  if (d.kind === "none") throw new Error(`${label}: ${d.why}`);
  const sp = Q.speedupFor(d.numax), file = `${String(i + 1).padStart(2, "0")}_${label.toLowerCase().replace(/'/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}.wav`;
  let samples;
  if (info && info.recording) {                                   // real Kepler recording: take the first 16.4 s
    const w = readWav(path.join(__dirname, "..", "app", info.recording));
    if (w.fs !== FS) throw new Error("unexpected sample rate");
    samples = w.x.slice(0, 1 << LOG2N);
    const fade = Math.floor(0.4 * FS);
    for (let j = 0; j < fade; j++) samples[samples.length - 1 - j] *= j / fade;
  } else {
    samples = Q.synth(Q.modes(d), { speedup: sp.speedup, fs: FS, log2n: LOG2N, seed: i + 1 }).samples;
  }
  fs.writeFileSync(path.join(OUT, file), Buffer.from(Q.wav(samples, FS)));
  const src = d.kind === "measured" ? `Real Kepler light curve (${info.ref.split(" (")[0]})` : d.kind === "published" ? d.ref : `Predicted: ${d.how}`;
  rows.push({ n: i + 1, file, label, kind: d.kind, numax: d.numax, dnu: d.dnu, hz: sp.hz, beat: d.dnu * 1e-6 * sp.speedup, extra: sp.extra, src, note: d.note });
  console.log(`${file.padEnd(28)} ${d.kind.padEnd(9)} nu_max ${d.numax.toFixed(1).padStart(7)} uHz -> ${sp.hz.toFixed(0).padStart(3)} Hz` + (sp.extra > 1 ? ` (42,000x and ${sp.extra}x more)` : ""));
});

const f = (v) => (v < 10 ? v.toFixed(2) : v < 100 ? v.toFixed(1) : Math.round(v).toLocaleString("en-US"));
fs.writeFileSync(path.join(OUT, "README.md"), `# Ten stars' starquakes

Smallest and densest (highest pitch) to largest. Each star's internal sound waves are sped up **42,000×**, the speed-up
Stanford's SoSH project used for the Sun, so pitch compares fairly. Arcturus is a red giant: at 42,000× it would sit
below hearing, so it gets one extra, stated speed-up. Each file is 16 s at 8 kHz. Use headphones for the low ones.

Made by \`node scripts/starquake_ten.js\` (model: \`app/starquake.js\`; recordings: \`pipeline/starquake.py\`).

| # | File | Star | How we know | ν_max (µHz) | Δν (µHz) | Hum | Beats |
|---|---|---|---|---|---|---|---|
${rows.map((r) => `| ${r.n} | \`${r.file}\` | ${r.label} | **${r.kind[0].toUpperCase() + r.kind.slice(1)}** | ${f(r.numax)} | ${f(r.dnu)} | ${f(r.hz)} Hz${r.extra > 1 ? ` (×${r.extra} more)` : ""} | ${r.beat.toFixed(1)} Hz |`).join("\n")}

- **Measured**: a real recording, made from Kepler photometry. The measured mode spacing matches Lund et al. 2017 to within 0.5%.
- **Published**: ν_max and Δν measured by astronomers; the mode pattern comes from theory.
${rows.filter((r) => r.kind === "published").map((r) => `  - ${r.label}: ${r.src}`).join("\n")}
- **Predicted**: size, mass and temperature estimated from the star catalogue, then the asteroseismic scaling relations. Expect errors of tens of percent.
${rows.filter((r) => r.kind === "predicted").map((r) => `  - ${r.label}: ${r.src}.${r.note ? ` ${r.note}` : ""}`).join("\n")}
`);
console.log("wrote", OUT);
