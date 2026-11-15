/* WANDERERS homepage learning layer (Kids and Student Explorer): missions board and discovery collection, quick
 * questions with an optional deeper explanation, and constellation cards drawn from real star positions.
 * Uses Discoveries (missions, quizzes, collection), ExplorerHome (shared facts from app/data) and StoryRender
 * (sky drawing). No network beyond app/data; nothing personal is stored. */
(function (root) {
  "use strict";
  const doc = root.document, E = root.Explorer, D = root.Discoveries, H = root.ExplorerHome, R = root.StoryRender;
  if (!doc || !E || !D || !H || !R) return;
  const $ = (id) => doc.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); });
  const level = () => (E.current() === "kids" ? "kids" : "teens");

  const ICON = {
    rings: '<circle cx="12" cy="16" r="4" stroke-dasharray="2 2"/><circle cx="12" cy="7" r="3.5"/><path d="M12 12.5V10.6" stroke-dasharray="1.5 1.5"/>',
    slider: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M12 5v14"/><circle cx="12" cy="12" r="2.2"/>',
    blink: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/>',
    question: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.6M12 16.8v.2"/>',
    spectrum: '<path d="M3 17c3-1 4-9 6-9s2 6 4 6 2-8 4-8 2 5 4 5"/>',
    pulse: '<circle cx="12" cy="12" r="3.5"/><circle cx="12" cy="12" r="7" stroke-dasharray="2 2.5"/>',
    constellation: '<path d="M4 18l5-7 5 3 6-9"/><circle cx="4" cy="18" r="1.4"/><circle cx="9" cy="11" r="1.4"/><circle cx="14" cy="14" r="1.4"/><circle cx="20" cy="5" r="1.4"/>',
    camera: '<rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="3.4"/><path d="M8 7l1.6-2.4h4.8L16 7"/>',
    story: '<rect x="6" y="2.5" width="12" height="19" rx="2.4"/><path d="M9 15l2-2.5 2 1.6 2-2.6"/><circle cx="14.5" cy="7.5" r="1.2"/>',
  };
  const icon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k] || ICON.question}</svg>`;

  /* ---------------- missions board + collection ---------------- */
  const WHERE = { home: "", observatory: "observatory.html", stories: "stories.html" };
  function renderMissions() {
    const host = $("missionBoard");
    if (!host) return;
    const lv = level(), pr = D.progressHere();
    host.innerHTML = `
      <div class="mb-head">
        <div><p class="eyebrow">${lv === "kids" ? "Your space missions" : "Discovery challenges"}</p>
          <h2 class="mb-title">${lv === "kids" ? "Collect a badge for every discovery" : "Learn how astronomers find things"}</h2></div>
        <p class="mb-count" aria-live="polite"><b>${pr.done}</b> of ${pr.total} discovered</p>
      </div>
      <ol class="mb-grid">${D.MISSIONS.map((m) => {
        const done = pr.have[m.id], t = m[lv], href = WHERE[m.where];
        const go = done ? "" : href ? `<a class="mb-go" href="${href}">Go <span aria-hidden="true">→</span></a>` : `<a class="mb-go" href="#${m.where === "home" && m.id.startsWith("quiz") ? "quizzes" : m.id === "constellations-3" ? "constellationCards" : "mission"}">Start <span aria-hidden="true">→</span></a>`;
        return `<li class="mb-card${done ? " done" : ""}">
          <span class="mb-badge">${icon(m.icon)}</span>
          <span class="mb-text"><b>${esc(t.title)}</b><span>${esc(t.how)}</span></span>
          ${done ? `<span class="mb-done"><span class="visually-hidden">Discovered on </span>${esc(done)}</span>` : go}
        </li>`;
      }).join("")}</ol>
      <div class="mb-foot">
        <p class="small-note">Your badges are saved only in this browser. No account, no scores, no timers.</p>
        ${pr.done ? '<button type="button" class="btn btn-ghost tiny" id="mbReset">Clear my badges</button>' : ""}
      </div>`;
    const reset = $("mbReset");
    if (reset) reset.onclick = () => { if (root.confirm("Clear all your discovery badges in this browser?")) D.resetHere(); };
  }

  /* ---------------- quizzes ---------------- */
  let quizIdx = 0;
  async function renderQuiz() {
    const host = $("quizzes");
    if (!host) return;
    const data = await H.load().catch(() => null);
    if (!data) { host.hidden = true; return; }
    const lv = level();
    const qs = D.QUIZZES.map((q) => D.quiz(q.id, lv, H.facts(data.targets[q.target]))).filter(Boolean);
    if (!qs.length) { host.hidden = true; return; }
    host.hidden = false;
    quizIdx = Math.min(quizIdx, qs.length - 1);
    const q = qs[quizIdx], done = D.progressHere().have[q.id];
    host.innerHTML = `
      <div class="qz-head"><p class="eyebrow">${lv === "kids" ? "Quick question" : "Think like an astronomer"} · ${quizIdx + 1} of ${qs.length}</p>
        <div class="qz-nav"><button type="button" class="btn btn-ghost tiny" data-d="-1" ${quizIdx ? "" : "disabled"} aria-label="Previous question">←</button><button type="button" class="btn btn-ghost tiny" data-d="1" ${quizIdx < qs.length - 1 ? "" : "disabled"} aria-label="Next question">→</button></div></div>
      <fieldset class="qz-card">
        <legend class="qz-q">${esc(q.q)}</legend>
        <div class="qz-opts">${q.options.map((o, k) => `<button type="button" class="qz-opt" data-k="${k}">${esc(o)}</button>`).join("")}</div>
        <div class="qz-out" aria-live="polite"></div>
        ${done ? '<p class="qz-badge">✓ Badge collected</p>' : ""}
      </fieldset>`;
    host.querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => { quizIdx += +b.dataset.d; renderQuiz(); }));
    const out = host.querySelector(".qz-out");
    host.querySelectorAll(".qz-opt").forEach((b) => (b.onclick = () => {
      const k = +b.dataset.k, right = k === q.answer;
      host.querySelectorAll(".qz-opt").forEach((x) => { x.classList.toggle("right", +x.dataset.k === q.answer); x.classList.toggle("wrong", x === b && !right); x.setAttribute("aria-pressed", x === b); });
      out.innerHTML = `<p class="qz-verdict ${right ? "yes" : "no"}">${right ? (lv === "kids" ? "Yes! " : "Correct. ") : (lv === "kids" ? "Good try! " : "Not quite. ")}${esc(q.why)}</p>
        <details class="qz-deeper"><summary>${lv === "kids" ? "Tell me more" : "Go deeper"}</summary><p>${esc(q.deeper)}</p></details>`;
      doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id: q.id } }));
    }));
  }

  /* ---------------- constellation cards ---------------- */
  const PICK = ["Ori", "UMa", "Cas", "Cyg", "Sco", "Leo", "Cru", "Lyr"];
  let sky = null, opened = new Set();
  async function loadSky() {
    if (sky) return sky;
    const c = await getJSON("data/constellations.json");
    sky = { list: PICK.map((id) => c.list.find((x) => x.id === id)).filter(Boolean), stars: null };
    return sky;
  }
  async function brightest(name) {
    if (!sky.stars) { const s = await getJSON("data/skystars.json").catch(() => null); sky.stars = s; }
    const s = sky.stars;
    if (!s) return null;
    const ci = s.meta.cons.indexOf(name);
    let best = null;
    for (const st of s.stars) if (st[6] === ci && st[7] && (!best || st[2] < best[2])) best = st;
    return best ? { name: best[7], mag: best[2], ly: best[5] } : null;
  }
  async function renderConstellations() {
    const host = $("constellationCards");
    if (!host) return;
    const s = await loadSky().catch(() => null);
    if (!s) { host.hidden = true; return; }
    const lv = level();
    host.innerHTML = `
      <div class="cc-head"><p class="eyebrow">${lv === "kids" ? "Star pictures" : "Constellations"}</p>
        <h2 class="mb-title">${lv === "kids" ? "Tap a star picture to learn its brightest star" : "Real star positions, joined into the classic figures"}</h2></div>
      <div class="cc-grid">${s.list.map((c) => {
        const f = R.constellationFigure(c, 120, 0.12);
        return `<button type="button" class="cc-card" data-id="${c.id}" aria-expanded="false">
          <svg viewBox="0 0 120 120" aria-hidden="true">${f.paths.map((p) => `<polyline points="${p.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ")}"/>`).join("")}${f.points.map((q) => `<circle cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}" r="2.2"/>`).join("")}</svg>
          <span class="cc-name">${esc(c.name)}</span><span class="cc-more" aria-live="polite"></span></button>`;
      }).join("")}</div>
      <p class="small-note">Figure lines: d3-celestial (BSD). Stars: HYG Database v4.1 (CC BY-SA 4.0). East is to the left, as the sky looks from the ground.</p>`;
    host.querySelectorAll(".cc-card").forEach((b) => (b.onclick = async () => {
      const c = s.list.find((x) => x.id === b.dataset.id), more = b.querySelector(".cc-more");
      b.setAttribute("aria-expanded", "true");
      more.textContent = "…";
      const st = await brightest(c.name);
      more.textContent = st ? (lv === "kids"
        ? `Brightest star: ${st.name}${st.ly ? `, ${Math.round(st.ly).toLocaleString("en")} light-years away` : ""}`
        : `Brightest: ${st.name} · V ${st.mag.toFixed(2)}${st.ly ? ` · ${Math.round(st.ly).toLocaleString("en")} ly` : ""}`) : "Star data not available";
      opened.add(c.id);
      if (opened.size >= 3) doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id: "constellations-3" } }));
    }));
  }

  function render(mode) {
    if (!E.isPlayful(mode)) return;
    renderMissions(); renderQuiz(); renderConstellations();
  }
  doc.addEventListener("explorermodechange", (e) => render(e.detail.mode));
  // a new badge updates the board only, so an answer that was just shown stays on screen
  doc.addEventListener("explorercollection", () => { if (E.isPlayful(E.current())) renderMissions(); });
  if (E.started) render(E.current());
})(typeof window !== "undefined" ? window : globalThis);
