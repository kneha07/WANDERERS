/* WANDERERS missions, quizzes and the personal discovery collection (Kids and Student Explorer).
 *
 * Local-first and private: the collection is a list of mission ids and the day each was done, kept in this browser
 * (localStorage "wanderers-discoveries"). No photos, places, names or ages. No streaks, timers or points: a badge
 * rewards trying something, never time spent. Any page can report progress with
 *   document.dispatchEvent(new CustomEvent("explorerdiscovery", { detail: { id: "<mission id>" } }))
 * and this file records it (only known mission ids are kept).
 *
 * Quiz facts that are numbers are read from the target's evidence card when the quiz is shown (see quizFacts).
 * Works in the browser (window.Discoveries) and in Node (module.exports) for the tests. */
(function (root) {
  "use strict";

  const KEY = "wanderers-discoveries";

  /* Missions. `how` says where it happens; the badge is earned by doing it, not by reading about it. */
  const MISSIONS = [
    { id: "mission-where-before", icon: "rings", where: "home",
      kids: { title: "Where was it before?", how: "Find where a moving star was 16 years ago." },
      teens: { title: "Measure a moving star", how: "Guess the 2010 position of Barnard’s Star, then see the measurement." } },
    { id: "compare-epochs", icon: "slider", where: "observatory",
      kids: { title: "Before and after", how: "Slide between two sky pictures in the Observatory." },
      teens: { title: "Compare two epochs", how: "Use the before/after slider on any Observatory target." } },
    { id: "blink", icon: "blink", where: "observatory",
      kids: { title: "Blink like an astronomer", how: "Press Blink in the Observatory and watch for a jump." },
      teens: { title: "Run a blink comparison", how: "Play the time-lapse in the Observatory, the way Pluto was found." } },
    { id: "quiz-why-move", icon: "question", where: "home",
      kids: { title: "Why do stars move?", how: "Answer the moving-star question." },
      teens: { title: "Motion or perspective?", how: "Answer the proper-motion vs parallax question." } },
    { id: "quiz-fingerprint", icon: "spectrum", where: "home",
      kids: { title: "Read a star’s colours", how: "Answer the hidden-colours question." },
      teens: { title: "Read a spectrum", how: "Answer the methane fingerprint question." } },
    { id: "quiz-breathing", icon: "pulse", where: "home",
      kids: { title: "Catch a breathing star", how: "Answer the brighter-and-dimmer question." },
      teens: { title: "Spot a variable star", how: "Answer the brightness-change question." } },
    { id: "constellations-3", icon: "constellation", where: "home",
      kids: { title: "Three constellations", how: "Open three constellation cards." },
      teens: { title: "Map three constellations", how: "Explore three constellation cards drawn from real star positions." } },
    { id: "camera-photo", icon: "camera", where: "stories",
      kids: { title: "Photograph the sky", how: "Take or add a photo in Space Camera." },
      teens: { title: "Capture the sky", how: "Take or add a photo in Space Camera." } },
    { id: "story-made", icon: "story", where: "stories",
      kids: { title: "Make a space story", how: "Save or share a story card." },
      teens: { title: "Publish a sky story", how: "Download, share or save a story card (it stays private unless you share it)." } },
  ];
  const IDS = MISSIONS.map((m) => m.id);
  const isMission = (id) => IDS.includes(id);

  /* ---------- collection (pure helpers take a storage object so tests can pass a fake) ---------- */
  function read(storage) {
    try {
      const raw = storage && storage.getItem(KEY);
      const v = raw ? JSON.parse(raw) : {};
      const out = {};
      for (const [k, d] of Object.entries(v && typeof v === "object" ? v : {})) if (isMission(k) && /^\d{4}-\d{2}-\d{2}$/.test(d)) out[k] = d;
      return out;
    } catch { return {}; }
  }
  /** Record a mission once; returns true when it is new. Stores only the id and the day. */
  function record(storage, id, today) {
    if (!isMission(id)) return false;
    const have = read(storage);
    if (have[id]) return false;
    have[id] = (today || new Date().toISOString()).slice(0, 10);
    try { storage && storage.setItem(KEY, JSON.stringify(have)); } catch { return false; }
    return true;
  }
  function reset(storage) { try { storage && storage.removeItem(KEY); } catch { /* blocked storage */ } }
  function progress(storage) { const have = read(storage); return { done: Object.keys(have).length, total: IDS.length, have }; }

  /* ---------- quizzes ---------- */
  // {fact} placeholders are filled from quizFacts(); options are short; `answer` is the index of the right one.
  const QUIZZES = [
    { id: "quiz-why-move", target: "barnard",
      kids: { q: "Barnard’s Star moved across our pictures. Why?", options: ["It is really travelling through space", "The camera wobbled", "It was a different star"], answer: 0,
        why: "It really is travelling! It’s one of our closest stars, so its trip shows up in just a few years.",
        deeper: "We measured {measured}. The European Gaia satellite says {catalogue}. Two different measurements agree." },
      teens: { q: "Barnard’s Star shifted {moved} between {span}. What causes most of that shift?", options: ["Its own motion through space (proper motion)", "Earth’s yearly orbit (parallax)", "The telescope pointing differently"], answer: 0,
        why: "Proper motion. We measured {measured}, matching Gaia’s {catalogue}.",
        deeper: "Parallax is real too, but it only moves Barnard’s Star ±0.55″ over a year: a small loop on top of a long straight walk. Each frame is placed on the sky with its own coordinates (WCS), so pointing differences cancel out." } },
    { id: "quiz-fingerprint", target: "wise0855",
      kids: { q: "WISE 0855 is a brown dwarf. What do its hidden infrared colours show?", options: ["Methane gas", "Ocean water you could swim in", "It is made of ice cream"], answer: 0,
        why: "Methane! The gas swallows one colour of infrared light, so that colour looks dim.",
        deeper: "It is {methane} brighter just next to the methane colour. A normal star wouldn’t have that dip." },
      teens: { q: "WISE 0855 is {methane} brighter at 4–4.75 µm than in the 3.3 µm band. What does that dip tell us?", options: ["Methane in its atmosphere absorbs at 3.3 µm", "It is a very hot star", "Dust is blocking all its light"], answer: 0,
        why: "Methane absorbs strongly around 3.3 µm. A deep dip there is the signature of a cold, methane-rich brown dwarf.",
        deeper: "WANDERERS builds this spectrum from every SPHEREx image of the target, placing each measurement at the wavelength that image recorded there. A normal star would come out below 1× on this test." } },
    { id: "quiz-breathing", target: "r_dra",
      kids: { q: "R Draconis gets brighter and dimmer. What is it doing?", options: ["Swelling and shrinking like breathing", "Turning its lights off", "Hiding behind the Moon"], answer: 0,
        why: "It’s a giant star that swells and shrinks. One ‘breath’ takes about 245 days.",
        deeper: "SPHEREx caught it changing: {brightness}." },
      teens: { q: "SPHEREx measured R Draconis: {brightness}. What kind of star is it?", options: ["A pulsating red giant (Mira variable)", "A brown dwarf", "A star that is moving fast"], answer: 0,
        why: "A Mira variable: a red giant that pulsates over about 245 days.",
        deeper: "Its core is too bright for SPHEREx, so WANDERERS measures the light in the wings of its image. The ± is the 1σ uncertainty. It shows no measurable motion: it is {distance} away." } },
  ];
  const fill = (s, f) => String(s).replace(/\{(\w+)\}/g, (_, k) => (f && f[k]) || "");
  /** A quiz at a level, with its numbers filled in; null when a fact it needs is missing. */
  function quiz(id, level, facts) {
    const q = QUIZZES.find((x) => x.id === id);
    if (!q) return null;
    const L = q[level === "kids" ? "kids" : "teens"];
    const text = [L.q, L.why, L.deeper, ...L.options].join(" ");
    const needs = [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
    if (needs.some((k) => !(facts && facts[k]))) return null;
    return { id, target: q.target, q: fill(L.q, facts), options: L.options.map((o) => fill(o, facts)), answer: L.answer, why: fill(L.why, facts), deeper: fill(L.deeper, facts) };
  }

  const api = { KEY, MISSIONS, IDS, QUIZZES, isMission, read, record, reset, progress, quiz };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.Discoveries = api;

  /* ---------- browser: listen for progress from any page ---------- */
  const doc = root.document;
  if (!doc) return;
  const storage = (() => { try { return root.localStorage; } catch { return undefined; } })();
  api.recordHere = (id) => {
    const isNew = record(storage, id);
    if (isNew) doc.dispatchEvent(new root.CustomEvent("explorercollection", { detail: { id, ...progress(storage) } }));
    return isNew;
  };
  api.progressHere = () => progress(storage);
  api.resetHere = () => { reset(storage); doc.dispatchEvent(new root.CustomEvent("explorercollection", { detail: { reset: true, ...progress(storage) } })); };
  doc.addEventListener("explorerdiscovery", (e) => {
    const d = e.detail || {};
    if (d.id === "mission-where-before" && d.found === false) return api.recordHere(d.id);   // trying counts, not winning
    api.recordHere(d.id);
  });
})(typeof window !== "undefined" ? window : globalThis);
