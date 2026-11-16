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
  if (m === "tour" || m === "quiz") { panel(`${closeBtn}<p class="small">Loading the sky…</p>`); await ready(); if (mode !== m) return; }
  ({ time: startTime, tour: startTour, quiz: startQuiz, infrared: startInfrared, class: startClass, log: startLog, near: startNear })[m]();
}
function close() {
  if (!mode) return;
  clearInterval(timer); timer = 0;
  if (mode === "time") endTime();
  if (mode === "infrared") endInfrared();
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
  panel(`${closeBtn}<div class="mission-tag">TIME MACHINE · HOW THE SKY CHANGES</div>
    <div class="learn-title" id="tmYear">${yearText(thisYear)}</div>
    <input type="range" id="tmSlider" min="-50000" max="50000" step="100" value="0" aria-label="Years from today">
    <div class="row-btns tm-presets">${[-50000, -14000, -5000, 0, 12000, 50000].map((y) => `<button class="btn ghost" data-y="${y}">${y ? (y > 0 ? "+" : "−") + Math.abs(y / 1000) + "k" : "Today"}</button>`).join("")}</div>
    <p class="small learn-aim" id="tmPole"></p>
    <p class="small">Two things change. Each star moves through space (Hipparcos motions), so near stars drift: the Big Dipper
      bends out of shape. And Earth's axis slowly circles (precession, one turn in about 25,800 years), so the pole star
      changes and different stars rise where you live.
      <span class="dim">Planets, the Moon and today's targets are hidden. Simple precession model: good to a few degrees.</span></p>
    <div class="row-btns"><button class="btn" id="tmDipper">Show me the Big Dipper</button></div>`);
  let dipper = false;
  const follow = () => { const p = dipper && RS.starPlace("Megrez"); if (p) pointTo({ name: "Big Dipper (Ursa Major)", ...p, kind: "constellation" }); };   // Megrez joins the bowl and the handle
  const pole = () => { const ps = RS.poleStar(); $("tmPole").textContent = ps ? (ps.deg < 5 ? `Pole star: ${ps.name}, ${ps.deg.toFixed(1)}° from the pole.` : `No bright pole star: the nearest, ${ps.name}, is ${ps.deg.toFixed(0)}° away.`) : ""; };
  const go = async (y) => { $("tmSlider").value = y; $("tmYear").textContent = yearText(thisYear + y); await RS.setYears(y); if (+$("tmSlider").value === y) { pole(); follow(); } };
  $("tmSlider").addEventListener("input", (e) => go(+e.target.value));
  $("learnPanel").querySelectorAll("[data-y]").forEach((b) => (b.onclick = () => go(+b.dataset.y)));
  $("tmDipper").onclick = () => { dipper = true; follow(); };
  pole();
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
  $("tourNext").onclick = () => { if (last) { flag("tour"); close(); } else { tour.i++; showStop(); } };
  tourTick();
}
function tourTick() {
  const o = tour && tour.stops[tour.i], el = $("tourAim"); if (!o || !el) return;
  const a = aimAt(o), on = a.sep <= o.tol;
  el.textContent = on ? `✓ You are looking at it.` : `Follow the arrow: ${a.turn}.`; el.classList.toggle("ok", on);
  if (on && !tour.on) log(o.name, o.kind);
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
  quiz.done = true; const pts = quiz.hint ? 5 : 10; quiz.score += pts; log(o.name, o.kind);
  if (navigator.vibrate) navigator.vibrate([40, 50, 40]);
  $("quizMsg").textContent = `✓ Found it! +${pts}. ${o.kind === "star" ? o.lines[1] || o.lines[0] : o.lines[0]}`;   // for a star: how far, not its magnitude $("quizMsg").classList.add("ok");
  setTimeout(nextRound, 2500);
}
function nextRound() {
  if (!quiz) return;
  if (++quiz.i < quiz.rounds.length) { showRound(); return; }
  const max = quiz.rounds.length * 10, best = Math.max(+(keep("wanderers.quizBest") || 0), quiz.score);
  keep("wanderers.quizBest", best); pointTo(null);
  if (quiz.score === max) flag("quiz");
  panel(`${closeBtn}<div class="mission-tag">FIND IT · DONE</div><div class="learn-title">${quiz.score} of ${max} points</div>
    <p class="small">Your best: ${best}. Each find is a real object in tonight's sky, from where you stand.</p>
    <div class="row-btns"><button class="btn ghost" data-close>Done</button><button class="btn primary" id="quizAgain">Play again</button></div>`);
  $("learnPanel").querySelectorAll("[data-close]").forEach((b) => (b.onclick = close));
  $("quizAgain").onclick = () => open("quiz");
}

// ---------- 4. why infrared? ----------
// Dust blocks visible light; infrared passes through it. Flip the Deep photographs between the two surveys over a dusty
// place that is up now, with the arrow to it.
const DUSTY = [
  { name: "Centre of the Milky Way", ra: 266.42, dec: -29.0, why: "Behind 25,000 light-years of dust: in visible light it is dark, in infrared the crowded centre shines." },
  { name: "Rho Ophiuchi cloud", ra: 246.8, dec: -24.4, why: "A dark cloud where new stars form: infrared shows the young stars inside it." },
  { name: "Orion Nebula", ra: 83.82, dec: -5.39, why: "A star nursery: infrared shows the stars still wrapped in their dust." },
  { name: "North America Nebula", ra: 312.9, dec: 44.3, why: "Dark dust lanes in Cygnus: infrared sees the stars behind them." },
  { name: "Taurus dark clouds", ra: 68.0, dec: 26.0, why: "Cold dust clouds, among the nearest star nurseries: almost empty in visible light." },
];
let irWas = null, irFlip = 0;
function startInfrared() {
  const RS = window.RealSky, now = C.nowDate(), L = C.loc();
  irWas = { sky: RS.R.sky, survey: RS.R.survey };
  RS.setSky("deep");
  const up = DUSTY.map((d) => ({ ...d, alt: Sky.observe(d, now, L.lat, L.lon).alt })).sort((a, b) => b.alt - a.alt), d = up[0];
  pointTo({ ...d, kind: "dusty cloud" });
  panel(`${closeBtn}<div class="mission-tag">WHY INFRARED? · SEEING THROUGH DUST</div>
    <div class="learn-title">${esc(d.name)}</div>
    <p class="small learn-aim">${d.alt > 0 ? "Follow the arrow, then flip." : "Below your horizon now: drag the sky there, or flip anywhere along the Milky Way."}</p>
    <p class="small">${esc(d.why)}</p>
    <p class="small">Dust blocks visible light, like fog. Infrared light has longer waves that slip past the dust, so hidden stars appear.
      That is why NASA's WISE and SPHEREx and the Webb telescope look in infrared.</p>
    <div class="row-btns"><button class="btn primary" id="irFlip">Flip: <span id="irNow"></span></button>
      <label class="check small"><input type="checkbox" id="irAuto"> Flip every 3 s</label></div>
    <p class="small dim" id="irName"></p>`);
  const show = () => { $("irNow").textContent = RS.R.survey === "infrared" ? "Infrared → Visible" : "Visible → Infrared"; $("irName").textContent = `Now: ${RS.surveyOf(RS.R.survey).name}.`; };
  const flip = async () => { await RS.setSurvey(RS.R.survey === "infrared" ? "visible" : "infrared"); show(); };
  $("irFlip").onclick = flip;
  $("irAuto").onchange = (e) => { clearInterval(irFlip); irFlip = e.target.checked ? setInterval(flip, 3000) : 0; };
  show();
}
function endInfrared() {
  clearInterval(irFlip); irFlip = 0;
  const RS = window.RealSky;
  if (irWas) { RS.setSurvey(irWas.survey); RS.setSky(irWas.sky); irWas = null; }
}

// ---------- 5. class link ----------
// One link that opens this sky for everyone: this place (rounded to about 10 km), this sky mode and target, and, if
// chosen, this moment frozen (?at=). It uses only settings the compass already reads from its link.
function classLink(freeze) {
  const u = new URL("compass.html", location.href), L = C.loc(), RS = window.RealSky, sel = C.S.sel;
  u.searchParams.set("lat", L.lat.toFixed(1)); u.searchParams.set("lon", L.lon.toFixed(1));
  u.searchParams.set("sky", RS.R.sky);
  if (freeze) u.searchParams.set("at", C.nowDate().toISOString().slice(0, 16) + "Z");
  if (sel && sel.id !== "learn") { u.searchParams.set("target", sel.id); if (sel.found) u.searchParams.set("star", sel.name); }
  return u.href;
}
function startClass() {
  panel(`${closeBtn}<div class="mission-tag">CLASS LINK · EVERYONE SEES THE SAME SKY</div>
    <p class="small">Share this link with a class. It opens this place, sky and target on every phone.</p>
    <label class="check small"><input type="checkbox" id="clFreeze" checked> Freeze this moment (the same sky for everyone, at any hour)</label>
    <div class="row-input"><input id="clUrl" readonly aria-label="Class link"><button class="btn" id="clCopy">Copy</button></div>
    <div class="row-btns"><button class="btn primary" id="clShare" hidden>Share…</button></div>
    <p class="small dim">The link holds your place rounded to about 10 km. Nothing is sent anywhere until you share it.</p>`);
  const fill = () => { $("clUrl").value = classLink($("clFreeze").checked); };
  $("clFreeze").onchange = fill; fill();
  $("clCopy").onclick = async () => {
    try { await navigator.clipboard.writeText($("clUrl").value); $("clCopy").textContent = "Copied"; }
    catch { $("clUrl").select(); $("clCopy").textContent = "Press Ctrl+C"; }
  };
  if (navigator.share) { $("clShare").hidden = false; $("clShare").onclick = () => navigator.share({ title: "WANDERERS Sky Compass", url: $("clUrl").value }).catch(() => {}); }
}

// ---------- 6. my sky log ----------
// Objects the user saw: logged by a tour stop, a quiz find, or "I saw it" on a card. Kept on this phone only.
const readLog = () => { try { return JSON.parse(keep("wanderers.skyLog") || "{}"); } catch { return {}; } };
function log(name, kind) {
  if (!name) return;
  const l = readLog(), now = new Date().toISOString().slice(0, 10);
  l[name] = { kind, first: (l[name] && l[name].first) || now, last: now, n: ((l[name] && l[name].n) || 0) + 1 };
  keep("wanderers.skyLog", JSON.stringify(l));
}
const flag = (k) => { const l = readLog(); l["#" + k] = { kind: "flag", first: new Date().toISOString().slice(0, 10), n: 1 }; keep("wanderers.skyLog", JSON.stringify(l)); };
const BADGES = [["First light", "your first object", (c) => c.all >= 1], ["Planet spotter", "3 planets", (c) => c.planet >= 3],
  ["Galaxy hunter", "3 galaxies", (c) => c.galaxy >= 3], ["Star collector", "20 stars", (c) => c.star >= 20],
  ["Pattern finder", "5 constellations", (c) => c.constellation >= 5], ["Tour guide", "a whole tour", (c) => c.tour],
  ["Sharp eye", "a perfect quiz", (c) => c.quiz]];
function startLog() {
  const l = readLog(), items = Object.entries(l).filter(([k]) => !k.startsWith("#")), c = { all: items.length, tour: !!l["#tour"], quiz: !!l["#quiz"] };
  for (const [, v] of items) c[v.kind] = (c[v.kind] || 0) + 1;
  const recent = items.sort((a, b) => (b[1].last || "").localeCompare(a[1].last || "")).slice(0, 30);
  panel(`${closeBtn}<div class="mission-tag">MY SKY LOG · ${items.length} OBJECT${items.length === 1 ? "" : "S"}</div>
    <div class="badges">${BADGES.map(([t, need, ok]) => `<span class="badge ${ok(c) ? "on" : ""}" title="${esc(need)}">${ok(c) ? "★" : "☆"} ${esc(t)}<small>${esc(need)}</small></span>`).join("")}</div>
    ${recent.length ? `<ul class="saved-list">${recent.map(([k, v]) => `<li><span><b>${esc(k)}</b> <span class="dim">${esc(v.kind)}</span></span><span class="dim">${esc(v.first)}${v.n > 1 ? ` · ${v.n}×` : ""}</span></li>`).join("")}</ul>`
      : '<p class="small">Nothing yet. Take the tour, play Find it, or tap a star and choose "I saw it".</p>'}
    <p class="small dim">Kept on this phone only.</p>`);
}

// ---------- 7. candidates near here ----------
// The Sky Survey's moving-object candidates (data/survey/leaderboard.json) nearest the crosshair, with a link to each.
let CANDS = null;
async function startNear() {
  panel(`${closeBtn}<p class="small">Loading the survey candidates…</p>`);
  if (!CANDS) CANDS = await fetch("data/survey/leaderboard.json").then((r) => r.json()).then((d) => d.candidates).catch(() => null);
  if (mode !== "near") return;
  if (!CANDS) { panel(`${closeBtn}<div class="learn-title">Candidates not available</div><p class="small">The survey list could not load. Check the connection and try again.</p>`); return; }
  const P = C.pose(), now = C.nowDate(), L = C.loc();
  const sepOf = (c) => { const s = Sky.observe(c, now, L.lat, L.lon); return Math.acos(Math.max(-1, Math.min(1, C.dot(C.vec(s.az, s.alt), P.forward)))) / D2R; };
  const near = CANDS.map((c) => ({ c, sep: sepOf(c) })).sort((a, b) => a.sep - b.sep).slice(0, 6);
  panel(`${closeBtn}<div class="mission-tag">CANDIDATES NEAR HERE · SKY SURVEY</div>
    <p class="small">Faint objects that move between infrared photographs taken years apart. Each one is a candidate, not a discovery: people check them.</p>
    <ul class="saved-list">${near.map(({ c, sep }) => `<li><span><b>${esc(c.id)}</b> <span class="dim">${Math.round(sep)}° from your crosshair · moves ${(c.pm / 1000).toFixed(2)}″/yr</span></span>
      <a class="btn" href="survey.html?id=${encodeURIComponent(c.id)}">Check it ↗</a></li>`).join("")}</ul>
    <div class="row-btns"><button class="btn ghost" id="nearShow">Show the nearest</button></div>`);
  $("nearShow").onclick = () => pointTo({ name: `Candidate ${near[0].c.id}`, ra: near[0].c.ra, dec: near[0].c.dec, kind: "candidate" });
}

// ---------- menu ----------
$("learnBtn").onclick = () => { const m = $("learnMenu"); m.hidden = !m.hidden; $("learnBtn").setAttribute("aria-expanded", !m.hidden); };
$("learnMenu").querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => open(b.dataset.mode)));
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && mode) close(); });
window.WanderersLearn = { open, close, objectsUp, log, readLog, classLink, get mode() { return mode; } };
