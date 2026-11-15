// Tests for app/frameinfo.js (frame details and data-flag summary).
// Run from the repository root:  node --test test/frameinfo.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const FI = require("../app/frameinfo.js");

const dataDir = path.join(__dirname, "..", "app", "data");
const load = (id) => JSON.parse(fs.readFileSync(path.join(dataDir, id, "target.json"), "utf8"));
const haveData = fs.existsSync(path.join(dataDir, "wise0855", "target.json"));
const real = { skip: !haveData && "data not present" };

test("signal formatting", () => {
  assert.equal(FI.fmtSnr(8.24), "8.2σ");
  assert.equal(FI.fmtSnr(99.94), "99.9σ");
  assert.equal(FI.fmtSnr(323.9), "324σ");
});

test("a frame row: WISE vs SPHEREx, seen vs not detected vs not measured", () => {
  const wise = FI.frameRow({ label: "WISE 2010", year: 2010.5, mission: "WISE", detected: true, snr: 25 });
  assert.deepEqual([wise.source, wise.images, wise.seen, wise.tone, wise.signal, wise.epoch], ["AllWISE atlas", null, "seen", "ok", "25.0σ", "2010.5"]);
  const faint = FI.frameRow({ label: "SPHEREx May 2025", year: 2025.34, mission: "SPHEREx", n_images: 1, detected: false, snr: 2.8 });
  assert.deepEqual([faint.source, faint.images, faint.seen, faint.tone, faint.signal], ["SPHEREx", 1, "not detected", "warn", "2.8σ"]);
  const none = FI.frameRow({ label: "SPHEREx Mar 2026", year: 2026.2, mission: "SPHEREx", n_images: 1 });
  assert.deepEqual([none.seen, none.tone, none.signal], ["not measured", "mute", ""]);
});

test("a frame with odd values does not break", () => {
  const r = FI.frameRow({ label: "x", mission: "SPHEREx", year: NaN, n_images: "many", snr: NaN });
  assert.equal(r.epoch, ""); assert.equal(r.images, null); assert.equal(r.signal, "");
});

test("quality levels and wording", () => {
  assert.equal(FI.quality({ spectrum_points: 100, flagged_points: 10 }).level, "ok");
  assert.equal(FI.quality({ spectrum_points: 100, flagged_points: 25 }).level, "warn");
  assert.equal(FI.quality({ spectrum_points: 100, flagged_points: 60 }).level, "warn");
  assert.equal(FI.quality({ spectrum_points: 100, flagged_points: 61 }).level, "bad");
  const all = FI.quality({ spectrum_points: 5, flagged_points: 5 });
  assert.match(all.text, /None were usable/);
  assert.match(all.text, /saturate/);
  assert.doesNotMatch(FI.quality({ spectrum_points: 100, flagged_points: 10 }).text, /saturate|None were usable/);
});

test("no spectrum measurements, missing fields and empty targets are handled", () => {
  const q = FI.quality({});
  assert.deepEqual([q.level, q.pct, q.total], ["none", null, 0]);
  const d = FI.describe({}, "w2");
  assert.deepEqual([d.rows.length, d.visits.length, d.visitImages], [0, 0, 0]);
  assert.doesNotThrow(() => FI.describe(null, "w1"));
  assert.ok(FI.describe({}, "w2").flagKinds.length >= 10);
});

test("visits are numbered and their images added up", () => {
  const d = FI.describe({ spherex_visits: [{ year: 2025.3436, n_images: 18 }, { year: 2025.8636, n_images: 74 }] }, "w2");
  assert.deepEqual(d.visits, [{ n: 1, epoch: "2025.34", images: 18 }, { n: 2, epoch: "2025.86", images: 74 }]);
  assert.equal(d.visitImages, 92);
});

test("real data: WISE 0855 (faint, partly flagged)", real, () => {
  const d = FI.describe(load("wise0855"), "w2");
  assert.equal(d.rows.length, 32);                        // WISE 2010 + 21 NEOWISE visits (2014-2024) + 10 SPHEREx frames
  assert.equal(d.rows[0].source, "AllWISE atlas");
  const neo = d.rows.slice(1, 22);
  assert.ok(neo.every((r) => r.source === "NEOWISE single exposures" && r.seen === "seen"), "every NEOWISE visit sees it");
  assert.equal(d.rows[22].source, "SPHEREx");
  assert.equal(d.rows[22].seen, "not detected");          // May 2025, two images
  assert.equal(d.rows[22].images, 2);
  assert.ok(d.rows.slice(23).every((r) => r.seen === "seen"));
  assert.deepEqual([d.quality.flagged, d.quality.total, d.quality.pct, d.quality.level], [41, 160, 26, "warn"]);
  assert.equal(d.visits.length, 3);
});

test("real data: Barnard's Star (too bright: every measurement flagged, no detection data)", real, () => {
  const d = FI.describe(load("barnard"), "w2");
  assert.equal(d.rows.length, 34);                        // WISE 2010 + 21 NEOWISE visits + 12 SPHEREx frames (DR1 and QR3), each with its own detection check
  assert.equal(d.rows.filter((r) => r.source === "NEOWISE single exposures").length, 21);
  assert.deepEqual([d.quality.flagged, d.quality.total, d.quality.level], [242, 242, "bad"]);
  assert.match(d.quality.text, /None were usable/);
});

test("real data: every committed target describes both channels without error", real, () => {
  const ids = JSON.parse(fs.readFileSync(path.join(dataDir, "index.json"), "utf8")).map((e) => e.id);
  assert.ok(ids.length >= 5);
  for (const id of ids) for (const ch of ["w1", "w2"]) {
    const t = load(id), d = FI.describe(t, ch);
    assert.equal(d.rows.length, (t.frames[ch] || []).length, `${id} ${ch}`);
    assert.ok(d.quality.flagged <= d.quality.total, id);
    assert.equal(d.visitImages, t.spherex_visits.reduce((s, v) => s + v.n_images, 0), id);
  }
});
