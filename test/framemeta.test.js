// Tests for the six-detector switch and the per-frame observation / data-quality panel:
// app/frameinfo.js (pure functions) and the Observatory page (app.js) in the fake browser.
// Run from the repository root:  node --test test/framemeta.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const FI = require("../app/frameinfo.js");
const { openPage } = require("./fakepage");

const ROOT = path.join(__dirname, "..");
const dataDir = path.join(ROOT, "app", "data");
const load = (id) => JSON.parse(fs.readFileSync(path.join(dataDir, id, "target.json"), "utf8"));
const INDEX = JSON.parse(fs.readFileSync(path.join(dataDir, "index.json"), "utf8"));
const regenerated = INDEX.every((e) => { const t = load(e.id); return t.frames.all && t.flag_legend; });
const real = { skip: !regenerated && "app/data was not regenerated with the combined channel" };
const open = (q, opts) => openPage("observatory.html", q, opts);
const search = (p) => new URLSearchParams(p.window.location.search);

// ---------- a small synthetic target ----------
const spx = (o = {}) => ({ year: 2025.4, label: "SPHEREx May 2025", mission: "SPHEREx", png: "d6_spherex_v1.png", n_images: 8,
  obs: { mission: "SPHEREx", instrument: "SPHEREx detector D6 (MWIR array)", detectors: [6], band_um: [4.42, 5.0], lam_um: [4.621, 4.983],
    start: "2025-05-05 16:51", end: "2025-05-12 03:10", time_note: "mid-exposure times", lam_note: "WCS-WAVE" },
  quality: { verdict: "caution", reason: "2 of 8 images are saturated at the target.", flags_checked: true,
    flag_counts: { HALO: 3, OVERFLOW: 2 }, pixel_flag_counts: { OVERFLOW: 2 }, n_saturated: 2, aperture_px: 29, bad_px_worst: 5, images_with_bad_px: 3 },
  ...o });
const T = {
  detector_bands: { 1: [0.75, 1.09], 6: [4.42, 5.0] },
  frames: {
    w2: [{ year: 2010.5, label: "WISE 2010", mission: "WISE", png: "w2_wise2010.png",
      obs: { mission: "WISE", instrument: "WISE W2 band · AllWISE atlas image", lam_um: [4.618, 4.618], start: "2010-05-03 08:45", end: "2010-11-13 11:18" },
      quality: { verdict: "poor", reason: "The star's core is saturated.", flags_checked: false, n_saturated: 1, aperture_px: 29, bad_px_worst: 12 } }, spx()],
    w1: [spx()], d1: [spx({ obs: { ...spx().obs, detectors: [1] } })], d6: [spx()], d3: [],
    all: [spx({ png: "all_spherex_v1.png", obs: { ...spx().obs, detectors: [1, 2, 3, 4, 5, 6], band_um: [0.75, 5.0], instrument: "SPHEREx detectors D1, D2, D3, D4, D5, D6" },
      quality: { ...spx().quality, verdict: "good", reason: "All 6 detector co-adds are good at the target.", detector_verdicts: { 1: "good", 6: "caution" } } })],
  },
};
const chip = (m, k) => (m.chips.find((c) => c.k === k) || {}).v;

// ---------- channel groups and the switch ----------
test("channels split into wavelength-matched, individual detectors and combined; empty channels are left out", () => {
  const g = FI.channelGroups(T);
  assert.deepEqual(g, { wavelength: ["w2", "w1"], detectors: ["d1", "d6"], combined: "all" });
  assert.deepEqual(FI.channelGroups(null), { wavelength: [], detectors: [], combined: null });
  assert.deepEqual(FI.channelGroups({ frames: { w2: [{}], toString: [{}] } }).wavelength, ["w2", "toString"]);
});

test("each channel belongs to one half of the switch", () => {
  assert.equal(FI.detectorMode("all"), "combined");
  for (const c of ["d1", "d6"]) assert.equal(FI.detectorMode(c), "individual");
  for (const c of ["w1", "w2", "d7", "d", "", undefined]) assert.equal(FI.detectorMode(c), null);
});

test("switch state: the mode follows the channel and Individual returns to the detector picked before", () => {
  let s = FI.switchState(T, "all", "d6");
  assert.equal(s.mode, "combined");
  assert.equal(s.individual.channel, "d6");
  assert.deepEqual(s.picks.map((p) => [p.ch, p.on]), [["d1", false], ["d6", false]]);
  s = FI.switchState(T, "d1", "d6");
  assert.equal(s.mode, "individual"); assert.equal(s.individual.channel, "d1");
  assert.equal(s.picks[0].range, "0.75–1.09 µm");
  s = FI.switchState(T, "w2", "d3");                     // d3 has no frames: the first detector instead
  assert.equal(s.mode, null); assert.equal(s.individual.channel, "d1");
  assert.equal(s.combined.channel, "all"); assert.equal(s.show, true);
});

test("switch state without a combined channel or without detectors", () => {
  const noAll = { frames: { w2: [{}], d2: [{}] } };
  const s = FI.switchState(noAll, "d2");
  assert.equal(s.combined.available, false); assert.equal(s.individual.available, true);
  assert.equal(s.picks[0].range, "1.10–1.62 µm");        // built-in detector bands when target.json has none
  const none = FI.switchState({ frames: { w2: [{}] } }, "w2");
  assert.equal(none.show, false); assert.equal(none.individual.channel, null);
});

test("arrow keys move through a radio group and wrap; Home and End jump; other keys do nothing", () => {
  const ids = ["d1", "d2", "d3"];
  assert.equal(FI.radioStep(ids, "d1", "ArrowRight"), "d2");
  assert.equal(FI.radioStep(ids, "d3", "ArrowDown"), "d1");
  assert.equal(FI.radioStep(ids, "d1", "ArrowLeft"), "d3");
  assert.equal(FI.radioStep(ids, "d2", "ArrowUp"), "d1");
  assert.equal(FI.radioStep(ids, "d2", "Home"), "d1");
  assert.equal(FI.radioStep(ids, "d2", "End"), "d3");
  assert.equal(FI.radioStep(ids, "d2", "Enter"), null);
  assert.equal(FI.radioStep([], "d2", "ArrowRight"), null);
  assert.equal(FI.radioStep(ids, "w2", "ArrowRight"), "d2");   // from outside the group: as if on the first
});

// ---------- the panel for one frame ----------
test("panel for a SPHEREx detector frame: mission, detector and range, wavelength, dates, stack, flags, saturation, bad pixels", () => {
  const m = FI.frameMeta(T, "d6", 0);
  assert.deepEqual(m.verdict, { level: "caution", label: "Caution", reason: "2 of 8 images are saturated at the target." });
  assert.equal(chip(m, "Mission"), "SPHEREx");
  assert.equal(chip(m, "Instrument"), "SPHEREx detector D6 (MWIR array)");
  assert.equal(chip(m, "Detector"), "D6 · 4.42–5.00 µm");
  assert.equal(chip(m, "λ at target"), "4.62–4.98 µm");
  assert.equal(chip(m, "Observed"), "2025-05-05 16:51 → 2025-05-12 03:10 UTC");
  assert.equal(chip(m, "Stacked"), "8 images");
  assert.equal(chip(m, "Flags at target pixel"), "OVERFLOW ×2");
  assert.equal(chip(m, "Flags within 3 px"), "HALO ×3, OVERFLOW ×2");
  assert.equal(chip(m, "Target saturated"), "yes, in 2 of 8 images");
  assert.equal(chip(m, "Bad pixels near target"), "5 of 29 in the worst image · 3 of 8 images affected");
  assert.equal(m.chips.find((c) => c.k === "Target saturated").tone, "bad");
  assert.equal(m.chips.find((c) => c.k === "λ at target").title, "WCS-WAVE");
});

test("panel for the combined frame lists the detectors and each detector's verdict", () => {
  const m = FI.frameMeta(T, "all", 0);
  assert.equal(m.verdict.level, "good");
  assert.equal(chip(m, "Detectors"), "D1, D2, D3, D4, D5, D6 · 0.75–5.00 µm");
  assert.equal(chip(m, "Each detector"), "D1 good · D6 caution");
  assert.equal(m.chips.find((c) => c.k === "Each detector").tone, "warn");
});

test("panel for a WISE frame: no flag planes, a saturated core, blank pixels", () => {
  const m = FI.frameMeta(T, "w2", 0);
  assert.equal(m.verdict.label, "Poor");
  assert.equal(chip(m, "Mission"), "WISE");
  assert.equal(chip(m, "Detector"), undefined);                  // WISE has no SPHEREx detector
  assert.equal(chip(m, "λ at target"), "4.62 µm");
  assert.equal(chip(m, "Observed"), "2010-05-03 08:45 → 2010-11-13 11:18 UTC");
  assert.equal(chip(m, "Stacked"), "atlas co-add");
  assert.match(chip(m, "Flags at target"), /not checked/);
  assert.equal(chip(m, "Target saturated"), "yes (blank core)");
  assert.equal(chip(m, "Blank pixels near target"), "12 of 29");
});

test("panel for a frame from before the check: says 'not recorded' and 'Not assessed' instead of breaking", () => {
  const old = { frames: { w2: [{ year: 2025.3, label: "SPHEREx May 2025", mission: "SPHEREx", n_images: 3 }] } };
  const m = FI.frameMeta(old, "w2", 0);
  assert.deepEqual([m.verdict.level, m.verdict.label], ["unknown", "Not assessed"]);
  assert.equal(chip(m, "Mission"), "SPHEREx");
  assert.equal(chip(m, "Stacked"), "3 images");
  for (const k of ["Instrument", "Detector", "λ at target", "Observed", "Flags at target", "Target saturated", "Bad pixels near target"]) {
    assert.equal(chip(m, k), "not recorded", k);
    assert.equal(m.chips.find((c) => c.k === k).tone, "mute", k);
  }
  const odd = { frames: { w2: [{ mission: "SPHEREx", obs: { lam_um: "x", detectors: "6", start: 5 }, quality: { verdict: "great", n_saturated: "2" } }] } };
  assert.doesNotThrow(() => FI.frameMeta(odd, "w2", 0));
  assert.equal(FI.frameMeta(odd, "w2", 0).verdict.level, "unknown");
});

test("panel: no frame at that place gives null", () => {
  assert.equal(FI.frameMeta(T, "w2", 9), null);
  assert.equal(FI.frameMeta(T, "nope", 0), null);
  assert.equal(FI.frameMeta(null, "w2", 0), null);
});

test("dates: one time, one day, several days", () => {
  assert.equal(FI.timeText({ start: "2025-05-05 16:51", end: "2025-05-05 16:51" }), "2025-05-05 16:51 UTC");
  assert.equal(FI.timeText({ start: "2025-05-05 16:51", end: "2025-05-05 19:02" }), "2025-05-05 16:51–19:02 UTC");
  assert.equal(FI.timeText({ start: "2025-05-05 16:51", end: "2025-05-07 01:00" }), "2025-05-05 16:51 → 2025-05-07 01:00 UTC");
  assert.equal(FI.timeText({ start: "2025-05-05 16:51" }), "2025-05-05 16:51 UTC");
  assert.equal(FI.timeText({}), ""); assert.equal(FI.timeText(null), "");
});

test("wavelengths and detector bands are formatted to 0.01 µm; bad input gives an empty string", () => {
  assert.equal(FI.lamText([3.0, 3.8]), "3.00–3.80 µm");
  assert.equal(FI.lamText([4.618, 4.618]), "4.62 µm");
  assert.equal(FI.lamText([4.6]), "4.60 µm");
  assert.equal(FI.lamText(null), ""); assert.equal(FI.lamText([NaN, 2]), "");
  assert.equal(FI.bandText([0.75, 5]), "0.75–5.00 µm"); assert.equal(FI.bandText("0.75"), "");
  assert.equal(FI.detText({ detectors: [3] }, {}), "D3 · 1.63–2.41 µm");
  assert.equal(FI.detText({ detectors: [] }, {}), "");
});

test("the frame table row carries the verdict", () => {
  assert.deepEqual([FI.frameRow(spx()).verdict, FI.frameRow(spx()).verdictLabel], ["caution", "Caution"]);
  const bare = FI.frameRow({ label: "x", mission: "WISE", year: 2010.5 });
  assert.deepEqual([bare.verdict, bare.verdictLabel], [null, ""]);
});

// ---------- flag legend and image rows ----------
const META = {
  flag_legend: [
    { name: "TRANSIENT", bit: 0, description: "Transient detected during SUR", bad: true, images_aperture: 0, images_target_pixel: 0 },
    { name: "OVERFLOW", bit: 1, description: "Overflow detected during SUR", bad: true, images_aperture: 2, images_target_pixel: 1 },
    { name: "OUTLIER", bit: 19, description: "Pixel flagged by Detect Outliers", bad: false, images_aperture: 1, images_target_pixel: 0 },
    { name: "SOURCE", bit: 21, description: "Pixel mapped to a known source", bad: false, informational: true, images_aperture: 0, images_target_pixel: 0 },
  ],
  metadata: [
    { date: "2025-05-05 16:51", detector: 6, lam_um: 4.9, flags_at_target: ["OVERFLOW", "OUTLIER"], used_in_spectrum: false,
      flags_target_pixel: ["OVERFLOW"], saturated: true, aperture_px: 29, bad_px_aperture: 4, quality: "poor", quality_reason: "The pixel at the target is saturated (OVERFLOW flag)." },
    { date: "2025-05-06 01:00", detector: 1, lam_um: 0.9, flags_at_target: ["OVERFLOW"], used_in_spectrum: false,
      flags_target_pixel: [], saturated: false, aperture_px: 29, bad_px_aperture: 1, quality: "caution", quality_reason: "…" },
    { date: "2025-05-07 01:00", detector: 2, lam_um: null, flags_at_target: [], used_in_spectrum: true,
      flags_target_pixel: [], saturated: false, aperture_px: 29, bad_px_aperture: 0, quality: "good", quality_reason: "…" },
  ],
};

test("flag legend: meanings from the FITS headers, flags seen at this target first, then by bit", () => {
  const L = FI.flagLegend(META);
  assert.deepEqual(L.map((r) => r.name), ["OVERFLOW", "OUTLIER", "TRANSIENT", "SOURCE"]);
  assert.deepEqual(L[0], { name: "OVERFLOW", bit: 1, desc: "Overflow detected during SUR", bad: true, info: false, hidden: false, images: 2, pixel: 1 });
  assert.equal(L[3].info, true);
});

test("flag legend for data without one: names from the image list, bad or not from the pipeline's set", () => {
  const L = FI.flagLegend({ metadata: [{ flags_at_target: ["HALO", "OUTLIER"] }, { flags_at_target: ["HALO"] }] });
  assert.deepEqual(L.map((r) => [r.name, r.images, r.bad, r.desc]), [["HALO", 2, true, ""], ["OUTLIER", 1, false, ""]]);
  assert.deepEqual(FI.flagLegend({}), []);
});

test("image rows: readable flags with their meaning, saturation, bad pixels and the verdict", () => {
  const [a, b, c] = FI.imageRows(META);
  assert.deepEqual(a.pixel, [{ name: "OVERFLOW", desc: "Overflow detected during SUR", bad: true }]);
  assert.deepEqual(a.aperture.map((f) => [f.name, f.bad]), [["OVERFLOW", true], ["OUTLIER", false]]);
  assert.deepEqual([a.det, a.lam, a.saturated, a.badPx, a.verdict, a.verdictLabel, a.inSpectrum], ["D6", "4.9 µm", true, "4/29", "poor", "Poor", false]);
  assert.equal(b.verdict, "caution"); assert.equal(c.lam, "–"); assert.equal(c.inSpectrum, true);
});

test("image rows from data before the check: no verdict, no saturation, no bad-pixel count", () => {
  const [r] = FI.imageRows({ metadata: [{ date: "2025-05-05 16:51", detector: 3, lam_um: 2.4, flags_at_target: ["COLD"], used_in_spectrum: false }] });
  assert.deepEqual([r.pixel, r.saturated, r.badPx, r.verdict], [null, null, "", null]);
  assert.deepEqual(r.aperture, [{ name: "COLD", desc: "", bad: true }]);
  assert.deepEqual(FI.imageRows({}), []);
});

test("image summary counts verdicts, saturation, flags and spectrum use", () => {
  assert.deepEqual(FI.imageSummary(META), { n: 3, good: 1, caution: 1, poor: 1, assessed: true, saturated: 1, withFlags: 2, inSpectrum: 1 });
  assert.equal(FI.imageSummary({ metadata: [{ flags_at_target: [] }] }).assessed, false);
});

test("the page's copies of the pipeline's flag set and detector bands match pipeline/analyze.py", () => {
  const py = fs.readFileSync(path.join(ROOT, "pipeline", "analyze.py"), "utf8");
  const bad = /BAD_NAMES = \{([^}]*)\}/.exec(py)[1].match(/"([A-Z_]+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual([...FI.BAD_NAMES].sort(), bad.sort());
  const bands = /DETECTOR_BANDS = \{([^}]*)\}/.exec(py)[1];
  for (const [k, [lo, hi]] of Object.entries(FI.DETECTOR_BANDS)) assert.match(bands, new RegExp(`${k}: \\(${lo.toFixed(2)}, ${hi.toFixed(2)}\\)`), `D${k}`);
});

// ---------- real data ----------
test("real data: every frame of every target gives a panel with a verdict, mission and dates", real, () => {
  for (const { id } of INDEX) {
    const t = load(id);
    for (const ch of Object.keys(t.frames)) t.frames[ch].forEach((f, i) => {
      const m = FI.frameMeta(t, ch, i);
      assert.ok(["good", "caution", "poor"].includes(m.verdict.level), `${id} ${ch} ${i}`);
      assert.ok(m.verdict.reason.length > 10, `${id} ${ch} ${i}`);
      for (const k of ["Mission", "Instrument", "λ at target", "Observed", "Stacked"]) assert.notEqual(chip(m, k), "not recorded", `${id} ${ch} ${i} ${k}`);
    });
  }
});

test("real data: every flag seen at a target has its meaning in the legend", real, () => {
  for (const { id } of INDEX) {
    const t = load(id), L = Object.fromEntries(FI.flagLegend(t).map((r) => [r.name, r]));
    for (const r of FI.imageRows(t)) for (const f of r.aperture) assert.ok(L[f.name] && L[f.name].desc, `${id} ${f.name}`);
    assert.ok(L.OVERFLOW && L.OVERFLOW.bad, id);
  }
});

// ---------- the page ----------
test("page: ?ch=all opens the combined view; the switch says so and the URL keeps it", real, async (t) => {
  const p = open("?target=wise0855&ch=all");
  t.after(p.close);
  await p.settle(200);
  assert.deepEqual(p.errors, []);
  const n = load("wise0855").frames.all.length;
  assert.match(p.$("frameLbl").textContent, new RegExp(`^1/${n} · 2025`));
  assert.equal(p.$("detModeAll").getAttribute("aria-checked"), "true");
  assert.equal(p.$("detModeInd").getAttribute("aria-checked"), "false");
  assert.equal(p.$("detModeAll").getAttribute("tabindex"), "0");
  assert.equal(p.$("detPick").hidden, true);
  assert.equal(p.$("detSwitch").hidden, false);
  assert.match(p.$("stamp").textContent, /All 6 detectors combined \(0\.75–5\.0 µm\)/);
  assert.match(p.$("detNote").textContent, /divided by its own robust noise/);
  assert.equal(search(p).get("ch"), "all");
});

test("page: Individual detectors and Combined (all 6) switch the channel and the address", real, async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(200);
  assert.equal(p.$("detModeInd").getAttribute("aria-checked"), "false");      // on 4.6 µm: neither half is picked
  assert.equal(p.$("detModeAll").getAttribute("aria-checked"), "false");
  assert.equal(p.$("detModeInd").getAttribute("tabindex"), "0");               // but the group still has one tab stop
  assert.equal(p.$("detPick").hidden, true);
  p.$("detModeInd").click();
  assert.equal(search(p).get("ch"), "d1");
  assert.equal(p.$("detPick").hidden, false);
  assert.match(p.$("detPick").innerHTML, /data-ch="d1" class="on" role="radio" aria-checked="true" tabindex="0"/);
  assert.match(p.$("detPick").innerHTML, /data-ch="d2" class="" role="radio" aria-checked="false" tabindex="-1" title="Detector 2 · 1\.10–1\.62 µm"/);
  assert.match(p.$("channels").innerHTML, /data-ch="w2" class="" role="radio" aria-checked="false" tabindex="0"/);
  p.$("detModeAll").click();
  assert.equal(search(p).get("ch"), "all");
  assert.equal(p.$("frameLbl").textContent.split(" ")[0], `1/${load("barnard").frames.all.length}`);
  assert.deepEqual(p.errors, []);
});

test("page: back from Combined, Individual returns to the detector picked before", real, async (t) => {
  const p = open("?target=wise0855&ch=d4");
  t.after(p.close);
  await p.settle(200);
  p.$("detModeAll").click();
  assert.equal(search(p).get("ch"), "all");
  p.$("detModeInd").click();
  assert.equal(search(p).get("ch"), "d4");
});

test("page: arrow keys move through the detectors and the switch without stepping the time-lapse", real, async (t) => {
  const p = open("?target=wise0855&ch=d1");
  t.after(p.close);
  await p.settle(200);
  const ev = p.key(p.$("detPick"), "ArrowRight");
  assert.equal(ev.defaultPrevented, true);
  assert.equal(search(p).get("ch"), "d2");
  assert.match(p.$("frameLbl").textContent, /^1\//);                  // the frame did not move
  p.key(p.$("detPick"), "End");
  assert.equal(search(p).get("ch"), "d6");
  p.key(p.$("detPick"), "ArrowRight");                                  // wraps
  assert.equal(search(p).get("ch"), "d1");
  p.key(p.$("detMode"), "ArrowRight");
  assert.equal(search(p).get("ch"), "all");
  assert.equal(p.document.activeElement, p.$("detModeAll"));
  p.key(p.$("detMode"), "ArrowLeft");
  assert.equal(search(p).get("ch"), "d1");
  p.key(p.$("channels"), "ArrowLeft");                                 // into the wavelength group: 3.4 µm (wraps from the first)
  assert.equal(search(p).get("ch"), "w1");
  const other = p.key(p.$("detPick"), "a");                             // other keys pass through
  assert.equal(other.defaultPrevented, false);
  p.key(p.document.body, "ArrowRight");                                 // with nothing focused the arrows still blink
  assert.match(p.$("frameLbl").textContent, /^2\//);
});

test("page: the panel follows the frame as the time-lapse steps", real, async (t) => {
  const p = open("?target=wise0855");
  t.after(p.close);
  await p.settle(200);
  assert.match(p.$("fmVerdict").innerHTML, /Data quality: (Good|Caution|Poor)/);
  assert.match(p.$("fmChips").innerHTML, /Mission<\/span> <span class="fm-v">WISE</);
  assert.match(p.$("fmChips").innerHTML, /2010-05-03/);
  p.key(p.document.body, "ArrowRight");
  assert.match(p.$("fmChips").innerHTML, /Mission<\/span> <span class="fm-v">NEOWISE</);
  const w2 = load("wise0855").frames.w2, k = w2.findIndex((f) => f.mission === "SPHEREx");
  p.$("frame").value = String(k); p.fire(p.$("frame"), "input");
  assert.match(p.$("fmChips").innerHTML, /Detector<\/span> <span class="fm-v">D6 · 4\.42–5\.00 µm/);
  assert.match(p.$("fmChips").innerHTML, /Flags at target pixel/);
  assert.match(p.$("fmVerdict").className, new RegExp(`v-${w2[k].quality.verdict}`));
});

test("page: a computed picture says so instead of describing one frame; the commentary is quiet while playing", real, async (t) => {
  const p = open("?target=wise0855");
  t.after(p.close);
  await p.settle(200);
  p.$("stackAll").onclick();
  assert.match(p.$("fmVerdict").textContent, /computed picture/);
  assert.equal(p.$("fmChips").innerHTML, "");
  p.$("stackAll").onclick();
  p.key(p.document.body, " ");                                           // play
  await p.settle(700);
  assert.equal(p.$("fmVerdict").getAttribute("aria-live"), "off");
  p.key(p.document.body, " ");                                           // pause
  assert.equal(p.$("fmVerdict").getAttribute("aria-live"), "polite");
});

test("page: the image table shows readable flags, the legend and the rules", real, async (t) => {
  const p = open("?target=barnard");
  t.after(p.close);
  await p.settle(200);
  const box = p.$("metaBox").innerHTML;
  assert.match(box, /<abbr class="fl fl-bad" title="Overflow detected during SUR">OVERFLOW<\/abbr>/);
  assert.match(box, /What the flags mean/);
  assert.match(box, /How the verdict is decided/);
  assert.match(box, /Verdicts: <b class="v-good">\d+ good<\/b>/);
  assert.match(box, /\d+ saturated at the target pixel/);
  assert.match(box, /<th>Flags at target pixel<\/th><th>Flags within 3 px<\/th><th>Saturated<\/th><th>Bad px<\/th><th>Verdict<\/th>/);
  assert.match(p.$("metaBody").innerHTML, /<th>Data quality<\/th>/);
});

test("page: data prepared before the combined channel and the check still works", async (t) => {
  const t0 = load("barnard");
  const old = JSON.parse(JSON.stringify(t0));
  delete old.frames.all; delete old.channels.all; delete old.flag_legend; delete old.quality_rules; delete old.combined;
  for (const ch of Object.keys(old.frames)) for (const f of old.frames[ch]) { delete f.obs; delete f.quality; }
  for (const m of old.metadata) for (const k of ["flags_target_pixel", "saturated", "target_blank", "aperture_px", "bad_px_aperture", "flagged_px_aperture", "dqa", "quality", "quality_reason"]) delete m[k];
  const p = open("?target=barnard&ch=all", { files: { "data/barnard/target.json": old } });
  t.after(p.close);
  await p.settle(200);
  assert.deepEqual(p.errors, []);
  assert.equal(search(p).get("ch"), null);                               // no combined channel: back to 4.6 µm
  assert.match(p.$("fmVerdict").innerHTML, /Data quality: Not assessed/);
  assert.match(p.$("fmChips").innerHTML, /not recorded/);
  assert.equal(p.$("detModeAll").disabled, true);
  assert.equal(p.$("detModeInd").disabled, false);
  assert.match(p.$("metaBox").innerHTML, /What the flags mean/);
  assert.doesNotMatch(p.$("metaBox").innerHTML, /Verdicts:|saturated at the target pixel/);
});

test("page: a target without detector co-adds hides the switch", async (t) => {
  const t0 = JSON.parse(JSON.stringify(load("barnard")));
  for (const ch of ["d1", "d2", "d3", "d4", "d5", "d6", "all"]) delete t0.frames[ch];
  const p = open("?target=barnard", { files: { "data/barnard/target.json": t0 } });
  t.after(p.close);
  await p.settle(200);
  assert.deepEqual(p.errors, []);
  assert.equal(p.$("detSwitch").hidden, true);
  assert.equal(p.$("detNote").hidden, true);
});

test("page: stylesheet, frameinfo.js and app.js are cache-busted together, and the new colours exist in all three theme places", () => {
  const html = fs.readFileSync(path.join(ROOT, "app", "observatory.html"), "utf8");
  const v = (f) => (new RegExp(`${f.replace(".", "\\.")}\\?v=(\\w+)`).exec(html) || [])[1];
  assert.ok(v("style.css") && v("style.css") === v("frameinfo.js") && v("frameinfo.js") === v("app.js"));
  const css = fs.readFileSync(path.join(ROOT, "app", "style.css"), "utf8");
  const light = /:root \{ --qv-good-bg[^}]*\}/.exec(css), dark = /:root\[data-theme="dark"\] \{ --qv-good-bg[^}]*\}/.exec(css);
  const os = /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme\]\) \{ --qv-good-bg[^}]*\}/.exec(css);
  for (const name of ["--qv-good-bg", "--qv-caution-bg", "--qv-poor-bg", "--qv-unknown-bg"])
    for (const [where, m] of [["light", light], ["dark", dark], ["OS dark", os]]) assert.ok(m && m[0].includes(name), `${name} ${where}`);
  assert.match(html, /id="detMode" role="radiogroup" aria-labelledby="detSwitchLbl"/);
  assert.match(html, /role="radio" aria-checked="false" tabindex="0" data-mode="individual">Individual detectors</);
  assert.match(html, />Combined \(all 6\)</);
});
