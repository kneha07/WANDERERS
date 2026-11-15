// Missions, quizzes and the local discovery collection (app/discoveries.js).
// node --test test/discoveries.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const D = require("../app/discoveries.js");
const H = require("../app/explorer-home.js");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
const target = (id) => JSON.parse(read(`app/data/${id}/target.json`));
const store = () => { const m = new Map(); return { m, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };

test("every mission has Kids and Students wording and a place to do it", () => {
  assert.equal(new Set(D.IDS).size, D.IDS.length);
  for (const m of D.MISSIONS) {
    for (const lv of ["kids", "teens"]) assert.ok(m[lv].title && m[lv].how, `${m.id}/${lv}`);
    assert.ok(["home", "observatory", "stories"].includes(m.where), m.id);
  }
});

test("collection: records a known mission once, with the day only", () => {
  const s = store();
  assert.equal(D.record(s, "blink", "2026-11-15T21:04:00Z"), true);
  assert.equal(D.record(s, "blink", "2026-11-16T00:00:00Z"), false, "second time is not new");
  assert.equal(D.record(s, "unknown-id"), false);
  assert.deepEqual(D.read(s), { blink: "2026-11-15" });
  const raw = s.getItem(D.KEY);
  assert.doesNotMatch(raw, /T\d\d:|lat|lon|name|photo/i, "no time of day, place, name or photo");
  assert.deepEqual(D.progress(s).done, 1);
  D.reset(s);
  assert.deepEqual(D.read(s), {});
});

test("collection: ignores junk in storage and survives blocked storage", () => {
  const s = store();
  s.setItem(D.KEY, JSON.stringify({ blink: "2026-11-15", evil: "x", "story-made": "<img onerror=1>" }));
  assert.deepEqual(D.read(s), { blink: "2026-11-15" });
  s.setItem(D.KEY, "not json");
  assert.deepEqual(D.read(s), {});
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
  assert.deepEqual(D.read(blocked), {});
  assert.equal(D.record(blocked, "blink"), false);
  assert.doesNotThrow(() => D.reset(blocked));
});

test("no streaks, timers or points: progress is only what was discovered", () => {
  const src = read("app/discoveries.js").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.doesNotMatch(src, /streak|points|score|setInterval|leaderboard/i);
});

test("quizzes: numbers come from the evidence cards; every quiz is a real mission", () => {
  for (const q of D.QUIZZES) assert.ok(D.isMission(q.id), q.id);
  const facts = (id) => H.facts(target(id));
  const t = D.quiz("quiz-why-move", "teens", facts("barnard"));
  assert.match(t.q, /163″ between 2010 and 2026/);
  assert.match(t.why, /10\.40″\/yr.*10\.39″\/yr/);
  assert.match(t.deeper, /±0\.55″/);
  assert.equal(t.options[t.answer], "Its own motion through space (proper motion)");
  const m = D.quiz("quiz-fingerprint", "kids", facts("wise0855"));
  assert.match(m.deeper, /5\.1× brighter/);
  const b = D.quiz("quiz-breathing", "teens", facts("r_dra"));
  assert.match(b.q, /Faded by 0\.34 ± 0\.06 mag/);
  assert.match(b.deeper, /2,607 ly/);
  for (const q of [t, m, b]) assert.doesNotMatch(JSON.stringify(q), /\{\w+\}|undefined/);
});

test("a quiz whose fact is missing is not shown (never a blank number)", () => {
  assert.equal(D.quiz("quiz-why-move", "teens", {}), null);
  assert.equal(D.quiz("nope", "kids", {}), null);
});

test("every mission can actually be earned somewhere in the app", () => {
  const src = ["app/explorer-home.js", "app/explorer-learn.js", "app/explorer-observatory.js", "app/stories.js"].map(read).join("\n");
  for (const id of D.IDS) {
    const viaQuiz = D.QUIZZES.some((q) => q.id === id) && /explorerdiscovery", \{ detail: \{ id: q\.id/.test(src);
    assert.ok(viaQuiz || src.includes(`"${id}"`), `${id} is dispatched by some page`);
  }
});
