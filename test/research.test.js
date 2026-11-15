// Research exports and table tools (app/research.js) and the file-name helper (app/share.js).
// node --test test/research.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Rs = require("../app/research.js");
const { safeName } = require("../app/share.js");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
const target = (id) => JSON.parse(read(`app/data/${id}/target.json`));
// The evidence-card line of a target that starts with `start`.
const card = (id, start) => target(id).evidence.checks.map((x) => x.text).find((x) => x.startsWith(start));
const parseCSV = (s) => s.trim().split("\n").map((l) => l.match(/("([^"]|"")*"|[^,]*)(,|$)/g).filter((x, i, a) => i < a.length - 1 || x !== "").map((c) => c.replace(/,$/, "").replace(/^"|"$/g, "").replace(/""/g, '"')));

test("summary: measured, catalogue and interpretation are labelled, with the real numbers", () => {
  const md = Rs.summary(target("barnard"), { url: "https://example.org/observatory.html?target=barnard", release: "SPHEREx Quick Release 3", generated: "2026-11-15" });
  assert.match(md, /^# Barnard's Star · WANDERERS observation summary/);
  assert.match(md, /_Measured_ .*_Catalogue_/);
  // The numbers come from target.json, so a data refresh (new epochs) does not break this test.
  const t = target("barnard"), v = t.variability, sg = (x) => (x >= 0 ? "+" : "") + x.toFixed(3);
  assert.ok(md.includes(`- Measured: ${t.motion.measured_arcsec_per_yr.toFixed(3)}″/yr`));
  assert.ok(md.includes(`- Catalogue (Gaia DR3, epoch 2016): ${t.motion.expected_arcsec_per_yr.toFixed(3)}″/yr`));
  assert.ok(md.includes(`Δm = ${sg(v.delta_mag)} ± ${v.uncertainty_mag.toFixed(3)} mag (1σ; positive = fainter)`));
  assert.match(md, /## Evidence \(_Interpretation_/);
  assert.ok(md.includes(`✓ ${card("barnard", "Moved ").split(" (")[0]}`));
  assert.match(md, /Residual vs predicted position: rms [\d.]+″/);
  assert.match(md, /SPHEREx Quick Release 3/);
  assert.match(md, /Candidates are never discoveries/);
  assert.match(md, /Generated 2026-11-15/);
});

test("summary: a motion the evidence calls insignificant says so; literature sources are cited", () => {
  const md = Rs.summary(target("r_dra"), { generated: "2026-11-15" });
  assert.match(md, /Evidence rule: No measurable motion between 2010 and 2026\. The measured value above is not a significant detection/);
  assert.match(Rs.summary(target("wise0855")), /Luhman & Esplin 2016, AJ 152, 78/);
  assert.match(Rs.summary(target("wise0855")), /Brightness change\n- Not measured for this target\./);
});

test("track CSV: one row per measured position, with the residual column", () => {
  const t = target("barnard"), rows = parseCSV(Rs.trackCSV(t));
  assert.deepEqual(rows[0], ["epoch_yr", "mission", "channel", "ra_deg", "dec_deg", "x_px", "y_px", "pred_x_px", "pred_y_px", "offset_from_prediction_arcsec"]);
  assert.equal(rows.length - 1, t.track.length);
  const wise = rows.find((r) => r[1] === "WISE" && r[2] === "w2");
  assert.equal(wise[0], "2010.5000");
  assert.ok(Math.abs(+wise[9] - t.track.find((p) => p.mission === "WISE" && p.ch === "w2").offset_arcsec) < 0.001);
});

test("spectrum CSV matches the target's spectrum", () => {
  const t = target("wise0855"), rows = parseCSV(Rs.spectrumCSV(t));
  assert.deepEqual(rows[0], ["wavelength_um", "flux_mJy", "n_images"]);
  assert.equal(rows.length - 1, t.spectrum.length);
});

test("short summary for sharing is factual and short", () => {
  const s = Rs.shortSummary(target("barnard"), "https://example.org/x");
  const moved = card("barnard", "Moved ").split(" (")[0], [meas, cat] = card("barnard", "Measured speed").split(": ")[1].split("″/yr")[0].split(" vs ");
  assert.ok(s.startsWith(`Barnard's Star: Nearby star with fast proper motion. ${moved}; measured ${meas}″/yr vs catalogue ${cat}″/yr.`), s);
  assert.ok(s.length < 300);
  assert.ok(Rs.shortSummary(target("r_dra")).includes(card("r_dra", "Faded by ").split(" mag")[0] + " mag"));
});

test("research table: rows, search, class filter, sort with blanks last, CSV quoting", () => {
  const list = JSON.parse(read("app/data/index.json")), targets = Object.fromEntries(list.map((e) => [e.id, target(e.id)]));
  const rows = Rs.tableRows(list, targets);
  assert.equal(rows.length, list.length);
  assert.deepEqual(Rs.filterRows(rows, { q: "barnard" }).map((r) => r.id), ["barnard"]);
  const cls = rows.find((r) => r.id === "wise0855").cls;
  assert.ok(Rs.filterRows(rows, { cls }).every((r) => r.cls === cls));
  const byMotion = Rs.sortRows(rows, "measured", -1);
  assert.equal(byMotion[0].id, "barnard");
  const withBlank = Rs.sortRows([{ dmag: null }, { dmag: 0.2 }, { dmag: -0.1 }], "dmag", 1);
  assert.deepEqual(withBlank.map((r) => r.dmag), [-0.1, 0.2, null]);
  const csv = Rs.rowsCSV(rows);
  const parsed = parseCSV(csv);
  assert.equal(parsed.length - 1, rows.length);
  assert.ok(csv.includes('"Barnard\'s Star"') || csv.includes("Barnard's Star"));
  assert.equal(Rs.toCSV(["a"], [['x,"y"']]), 'a\n"x,""y"""\n');
});

test("safe file names", () => {
  assert.equal(safeName("Tonight’s sky!", "png"), "tonights-sky.png");
  assert.equal(safeName("", "csv"), "wanderers.csv");
  assert.equal(safeName("../../etc/passwd", "md"), "etcpasswd.md");
});
