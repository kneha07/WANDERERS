// Write listenable starquake samples to artifacts/starquakes/ (model sound, same 42,000x speed-up for all):
//   sun.wav                      the Sun, 33 s (compare: Stanford SoSH's real-data hum near 126 Hz)
//   small_to_large.wav           five stars from dense to big, 8 s each, 1 s silence between
// Run from the repository root:  node scripts/starquake_samples.js
const fs = require("fs"), path = require("path");
const Q = require("../app/starquake.js");
const INFO = require("../app/data/starquake_stars.json");
const OUT = path.join(__dirname, "..", "artifacts", "starquakes");
fs.mkdirSync(OUT, { recursive: true });
const FS = 8000;
const one = (k, log2n, seed = 1) => Q.synth(Q.modes(Q.describe(INFO[k], null)), { fs: FS, log2n, seed }).samples;
fs.writeFileSync(path.join(OUT, "sun.wav"), Buffer.from(Q.wav(one("sun", 18), FS)));
const order = ["kic8006161", "sun", "kic6106415", "kic12258514", "kic3632418"];
const parts = order.map((k) => one(k, 16)), gap = new Float32Array(FS);
const seq = new Float32Array(parts.reduce((n, p) => n + p.length + gap.length, 0));
let o = 0; for (const p of parts) { seq.set(p, o); o += p.length + gap.length; }
fs.writeFileSync(path.join(OUT, "small_to_large.wav"), Buffer.from(Q.wav(seq, FS)));
console.log("wrote", OUT, "order:", order.map((k) => `${INFO[k].name} (${Math.round(INFO[k].numax * 1e-6 * Q.SPEEDUP)} Hz)`).join(" → "));
