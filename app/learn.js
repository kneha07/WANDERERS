// WANDERERS Sky Compass: learning modes, opened from the 🎓 button.
//  - Time machine: a year slider; every star moves along its measured proper motion (RealSky.setYears).
//  - Tonight's tour: five stops chosen from what is above the horizon now, with an arrow to each.
//  - Find it: a quiz; the app names an object, the user points the crosshair at it.
// Uses what compass.js shares on window.WanderersCompass, and RealSky (realsky.js).
const C = window.WanderersCompass, $ = (id) => document.getElementById(id);
const D2R = Math.PI / 180;
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const keep = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } };

// ---------- what is above the horizon now ----------
// Each object: { kind, name, ra, dec, az, alt, tol (deg: how close the crosshair must come), lines (card text), clue }
const FAMOUS = ["Orion", "Ursa Major", "Cassiopeia", "Cygnus", "Scorpius", "Leo", "Crux", "Lyra", "Taurus", "Gemini",
  "Sagittarius", "Andromeda", "Perseus", "Pegasus", "Boötes", "Bootes", "Aquila", "Ursa Minor", "Canis Major", "Centaurus"];
const ascii = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "");
function objectsUp(minAlt = 12) {
  const now = C.nowDate(), L = C.loc(), RS = window.RealSky, EYE = RS.EYE, out = [];
  const place = (o) => { const s = Sky.observe(o, now, L.lat, L.lon); return { ...o, az: s.az, alt: s.alt }; };
  if (EYE.stars) {
    EYE.stars.forEach((r, i) => {
      if (!r[7] || r[2] > 2.2) return;                       // named and bright: easy to find by eye
      const card = SkyView.starCard(r, EYE.cons), con = EYE.cons[r[6]] || "";
      const first = !EYE.stars.slice(0, i).some((q) => q[6] === r[6]);   // the list is sorted by brightness
      out.push(place({ kind: "star", name: r[7], ra: r[0], dec: r[1], mag: r[2], con, tol: 3, lines: card.lines,
        clue: `${first ? "The brightest star" : "A bright star"}${con ? ` in ${con}` : ""}, magnitude ${r[2].toFixed(1)}.` }));
    });
  }
  for (const p of RS.planetsNow(now)) out.push(place({ kind: "planet", name: p.name, ra: p.ra, dec: p.dec, tol: 3,
    lines: ["A planet: it shines by reflected sunlight and moves against the stars from night to night.", ...StarSearch.distanceLines(p.au * 1.495979e8)],
    clue: "A planet: a steady point of light that does not twinkle." }));
  for (const g of RS.GALAXIES) out.push(place({ kind: "galaxy", name: g.name, ra: g.ra, dec: g.dec, tol: Math.max(3, g.a / 120 + 1),
    lines: RS.galaxyCard(g, now, L).lines, clue: RS.galaxyCard(g, now, L).lines[0] }));
  if (RS.CON.list && EYE.stars) for (const c of RS.CON.list) {
    const r = EYE.stars.find((q) => ascii(EYE.cons[q[6]] || "") === ascii(c.name));
    const lead = r && r[7] ? `Its brightest star is ${r[7]}.` : "";
    out.push(place({ kind: "constellation", name: c.name, ra: c.ra, dec: c.dec, tol: 12, famous: FAMOUS.includes(c.name),
      lines: ["A constellation: a pattern of stars that look close together but lie at very different distances.", lead].filter(Boolean),
      clue: lead || "A pattern of stars." }));
  }
  for (const t of C.S.targets) if (!t.found && t.id !== "learn") out.push(place({ kind: "target", name: t.name, ra: t.ra, dec: t.dec, tol: 3,
    lines: [`A WANDERERS target: ${t.teaser}.`, "Open the Observatory for its full analysis."], clue: `A WANDERERS target: ${t.teaser}.` }));
  return out.filter((o) => o.alt >= minAlt);
}
// angle between the crosshair and an object (deg), and which way to turn
function aimAt(o) {
  const P = C.pose(), s = Sky.observe(o, C.nowDate(), C.loc().lat, C.loc().lon);
  const sep = Math.acos(Math.max(-1, Math.min(1, C.dot(C.vec(s.az, s.alt), P.forward)))) / D2R;
  const dAz = ((s.az - P.az + 540) % 360) - 180, dAlt = s.alt - P.alt;
  const turn = [Math.abs(dAz) < 2 ? "" : `turn ${dAz > 0 ? "right" : "left"} ${Math.abs(Math.round(dAz))}°`,
    Math.abs(dAlt) < 2 ? "" : `tilt ${dAlt > 0 ? "up" : "down"} ${Math.abs(Math.round(dAlt))}°`].filter(Boolean).join(" · ");
  return { sep, turn: turn || "almost there" };
}
// the arrow and brackets of compass.js point at the "learn" target; one at a time
let before = null;
function pointTo(o) {
  if (before === null) before = C.S.sel;
  C.S.targets = C.S.targets.filter((t) => t.id !== "learn");
  if (o) { const t = { id: "learn", found: true, name: o.name, ra: o.ra, dec: o.dec, teaser: o.kind }; C.S.targets.push(t); C.S.sel = t; C.S.buzzed.learn = false; }
  else { C.S.sel = before && C.S.targets.includes(before) ? before : null; before = null; }
  C.renderTargets();
}

// the tour and the quiz need the star list and the constellation lines: start loading, wait up to 8 s
async function ready() {
  const RS = window.RealSky; RS.loadStars(); RS.loadLines();
  for (let i = 0; i < 80 && !(RS.EYE.stars && RS.CON.list); i++) await new Promise((r) => setTimeout(r, 100));
}

// ---------- the panel and the mode ----------
let mode = null, timer = 0;
async function open(m) {
  close();
  mode = m; document.body.classList.add("learning"); $("learnMenu").hidden = true; $("learnPanel").hidden = false;
  if (m !== "time") { panel(`${closeBtn}<p class="small">Loading the sky…</p>`); await ready(); if (mode !== m) return; }
  ({ time: startTime, tour: startTour, quiz: startQuiz })[m]();
}
function close() {
  if (!mode) return;
  clearInterval(timer); timer = 0;
  if (mode === "time") endTime();
  pointTo(null); mode = null;
  document.body.classList.remove("learning"); $("learnPanel").hidden = true; $("learnPanel").innerHTML = "";
}
const panel = (html) => { $("learnPanel").innerHTML = html; $("learnPanel").querySelector("[data-close]")?.addEventListener("click", close); };
const closeBtn = '<button class="sky-card-close" data-close aria-label="Close">×</button>';

// ---------- 1. time machine ----------
let timeWas = null;
const yearText = (y) => (y <= 0 ? `${(1 - y).toLocaleString("en-US")} BCE` : `${y.toLocaleString("en-US")} CE`);
function startTime() {
  const RS = window.RealSky;
  timeWas = { sky: RS.R.sky, lines: RS.R.lines };
  RS.R.lines = true; RS.setSky("eye");                     // the photographs cannot move; the drawn stars can
  const thisYear = C.nowDate().getUTCFullYear();
  panel(`${closeBtn}<div class="mission-tag">TIME MACHINE · HOW THE STARS MOVE</div>
    <div class="learn-title" id="tmYear">${yearText(thisYear)}</div>
    <input type="range" id="tmSlider" min="-50000" max="50000" step="100" value="0" aria-label="Years from today">
    <div class="row-btns tm-presets">${[-50000, -10000, 0, 10000, 50000].map((y) => `<button class="btn ghost" data-y="${y}">${y ? (y > 0 ? "+" : "−") + Math.abs(y / 1000) + "k" : "Today"}</button>`).join("")}</div>
    <p class="small">Each star moves along its measured motion today (Hipparcos), in a straight line. Near stars move most:
      the Big Dipper bends out of shape, while far stars such as those of Cygnus hardly move.
      <span class="dim">Straight-line motion only: Earth's slow wobble (precession) is not shown, and the nearest stars are approximate far from today.</span></p>
    <div class="row-btns"><button class="btn" id="tmDipper">Show me the Big Dipper</button></div>`);
  const go = (y) => { $("tmSlider").value = y; $("tmYear").textContent = yearText(thisYear + y); RS.setYears(y); };
  $("tmSlider").addEventListener("input", (e) => go(+e.target.value));
  $("learnPanel").querySelectorAll("[data-y]").forEach((b) => (b.onclick = () => go(+b.dataset.y)));
  $("tmDipper").onclick = () => { const c = RS.CON.list && RS.CON.list.find((x) => x.name === "Ursa Major"); if (c) pointTo({ name: "Big Dipper (Ursa Major)", ra: 165.5, dec: 56, kind: "constellation" }); };   // the Dipper's middle, not the constellation's
}
function endTime() {
  const RS = window.RealSky;
  RS.setYears(0);
  if (timeWas) { RS.R.lines = timeWas.lines; RS.setSky(timeWas.sky); timeWas = null; }
}

// ---------- 2. tonight's tour ----------
// Five stops of different kinds, in order around the horizon: a bright star, a constellation, a planet, a galaxy,
// a WANDERERS target. A kind with nothing up is left out; the brightest or highest of each kind is chosen.
let tour = null;
function startTour() {
  const up = objectsUp(), pick = (kind, by) => up.filter((o) => o.kind === kind).sort(by)[0];
  const stops = [pick("star", (a, b) => a.mag - b.mag), pick("constellation", (a, b) => (b.famous - a.famous) || (b.alt - a.alt)),
    pick("planet", (a, b) => b.alt - a.alt), pick("galaxy", (a, b) => b.alt - a.alt), pick("target", (a, b) => b.alt - a.alt)]
    .filter(Boolean).sort((a, b) => a.az - b.az);
  if (!stops.length) { panel(`${closeBtn}<div class="learn-title">Nothing high enough yet</div><p class="small">The star list is still loading, or the sky here is below the horizon. Try again in a moment.</p>`); return; }
  tour = { stops, i: 0, on: false };
  showStop();
  timer = setInterval(tourTick, 200);
}
function showStop() {
  const o = tour.stops[tour.i], last = tour.i === tour.stops.length - 1;
  tour.on = false; pointTo(o);
  panel(`${closeBtn}<div class="mission-tag">TONIGHT'S TOUR · STOP ${tour.i + 1} OF ${tour.stops.length} · ${o.kind.toUpperCase()}</div>
    <div class="learn-title">${esc(o.name)}</div><p class="small learn-aim" id="tourAim"></p>
    ${o.lines.map((l) => `<p class="small">${esc(l)}</p>`).join("")}
    <div class="row-btns"><button class="btn ghost" id="tourBack" ${tour.i ? "" : "disabled"}>Back</button>
      <button class="btn primary" id="tourNext">${last ? "Finish" : "Next stop →"}</button></div>`);
  $("tourBack").onclick = () => { tour.i--; showStop(); };
  $("tourNext").onclick = () => { if (last) close(); else { tour.i++; showStop(); } };
  tourTick();
}
function tourTick() {
  const o = tour && tour.stops[tour.i], el = $("tourAim"); if (!o || !el) return;
  const a = aimAt(o), on = a.sep <= o.tol;
  el.textContent = on ? `✓ You are looking at it.` : `Follow the arrow: ${a.turn}.`; el.classList.toggle("ok", on);
  tour.on = on;                                   // (compass.js buzzes once on the lock: the arrow points at this stop)
}

// ---------- 3. find it ----------
// Five rounds. A find is held for 0.6 s inside the object's reach: 10 points, or 5 after a hint (the arrow).
let quiz = null;
function startQuiz() {
  const up = objectsUp(15), byKind = {};
  for (const o of up) (byKind[o.kind] ||= []).push(o);
  for (const k in byKind) byKind[k].sort(() => Math.random() - 0.5);
  const kinds = Object.keys(byKind), rounds = [];
  for (let k = 0; rounds.length < 5 && kinds.some((x) => byKind[x].length); k++) {   // take kinds in turn, for variety
    const list = byKind[kinds[k % kinds.length]]; if (list.length) rounds.push(list.pop());
  }
  if (!rounds.length) { panel(`${closeBtn}<div class="learn-title">Nothing to find yet</div><p class="small">The star list is still loading. Try again in a moment.</p>`); return; }
  quiz = { rounds, i: 0, score: 0, hint: false, inSince: 0, done: false };
  showRound();
  timer = setInterval(quizTick, 100);
}
function showRound() {
  const o = quiz.rounds[quiz.i];
  quiz.hint = false; quiz.inSince = 0; quiz.done = false; pointTo(null);
  panel(`${closeBtn}<div class="mission-tag">FIND IT · ROUND ${quiz.i + 1} OF ${quiz.rounds.length} · SCORE ${quiz.score}</div>
    <div class="learn-title">Find ${o.kind === "galaxy" ? "the " : ""}${esc(o.name)}</div>
    <p class="small">${esc(o.clue)}</p><p class="small learn-aim" id="quizMsg">Point the crosshair at it.</p>
    <div class="row-btns"><button class="btn ghost" id="quizHint">Hint (−5)</button><button class="btn ghost" id="quizSkip">Skip</button></div>`);
  $("quizHint").onclick = () => { quiz.hint = true; pointTo(o); $("quizHint").disabled = true; $("quizMsg").textContent = "Follow the arrow."; };
  $("quizSkip").onclick = nextRound;
}
function quizTick() {
  if (!quiz || quiz.done) return;
  const o = quiz.rounds[quiz.i], a = aimAt(o), now = performance.now();
  if (a.sep > o.tol) { quiz.inSince = 0; return; }
  if (!quiz.inSince) { quiz.inSince = now; return; }
  if (now - quiz.inSince < 600) return;
  quiz.done = true; const pts = quiz.hint ? 5 : 10; quiz.score += pts;
  if (navigator.vibrate) navigator.vibrate([40, 50, 40]);
  $("quizMsg").textContent = `✓ Found it! +${pts}. ${o.kind === "star" ? o.lines[1] || o.lines[0] : o.lines[0]}`;   // for a star: how far, not its magnitude $("quizMsg").classList.add("ok");
  setTimeout(nextRound, 2500);
}
function nextRound() {
  if (!quiz) return;
  if (++quiz.i < quiz.rounds.length) { showRound(); return; }
  const max = quiz.rounds.length * 10, best = Math.max(+(keep("wanderers.quizBest") || 0), quiz.score);
  keep("wanderers.quizBest", best); pointTo(null);
  panel(`${closeBtn}<div class="mission-tag">FIND IT · DONE</div><div class="learn-title">${quiz.score} of ${max} points</div>
    <p class="small">Your best: ${best}. Each find is a real object in tonight's sky, from where you stand.</p>
    <div class="row-btns"><button class="btn ghost" data-close>Done</button><button class="btn primary" id="quizAgain">Play again</button></div>`);
  $("learnPanel").querySelectorAll("[data-close]").forEach((b) => (b.onclick = close));
  $("quizAgain").onclick = () => open("quiz");
}

// ---------- menu ----------
$("learnBtn").onclick = () => { const m = $("learnMenu"); m.hidden = !m.hidden; $("learnBtn").setAttribute("aria-expanded", !m.hidden); };
$("learnMenu").querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => open(b.dataset.mode)));
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && mode) close(); });
window.WanderersLearn = { open, close, objectsUp, get mode() { return mode; } };
