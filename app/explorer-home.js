/* WANDERERS homepage, adaptive layer (Kids and Student Explorer stories and mission; Research Mode data panel).
 * Reads the same app/data files as home.js and changes only how they are told: no numbers are typed in here.
 * The scientific homepage (General Explorer) is left exactly as it is; Kids and Students can open it with
 * "Show the scientist view". Story text is chosen by mode, facts are taken from each target's evidence card.
 *
 * Pure helpers are exported for Node tests (module.exports); the browser part runs when Explorer is present. */
(function (root) {
  "use strict";

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const checkText = (t, re) => ((t && t.evidence && t.evidence.checks) || []).find((c) => re.test(c.text))?.text || "";
  const numVal = (t, re) => ((t && t.evidence && t.evidence.numbers) || []).find((n) => re.test(n.label))?.value || "";
  const grab = (s, re) => { const m = re.exec(s || ""); return m ? m[1] : ""; };

  /** The facts a story may quote, all read from target.json (empty string when a target does not have one). */
  function facts(t) {
    if (!t) return {};
    const moved = checkText(t, /^Moved/), meth = checkText(t, /methane/i), bright = checkText(t, /^(Faded|Brightened)/);
    return {
      name: t.name || "",
      kind: t.kind || "",
      moved: grab(moved, /^Moved ([\d.]+″)/),
      span: grab(moved, /between (\d{4} and \d{4})/),
      measured: numVal(t, /^measured motion/),
      catalogue: numVal(t, /^catalogue motion/),
      distance: numVal(t, /^distance/),
      methane: grab(meth, /^([\d.]+×)/),
      brightness: bright ? bright.split(" (")[0] : "",
      brightnessLc: bright ? bright.split(" (")[0].replace(/^./, (c) => c.toLowerCase()) : "",
      classification: (t.evidence && t.evidence.classification) || "",
    };
  }

  /** Story text per mode. {placeholders} are filled from facts(); a story whose needed facts are missing is skipped. */
  const STORIES = [
    { id: "barnard", needs: ["moved"],
      kids: { title: "The speedy star", text: "In 16 years this star raced across the picture: about a tenth of the Moon’s width. It’s the fastest star in our sky!" },
      teens: { title: "The fastest star in the sky", text: "Barnard’s Star moved {moved} between {span}. We measured {measured}; ESA’s Gaia catalogue says {catalogue}." },
      chip: "{moved} in 16 years" },
    { id: "wise0855", needs: ["methane"],
      kids: { title: "A failed star, as cold as the North Pole", text: "WISE 0855 is a brown dwarf: too small to shine like the Sun. Its hidden infrared colours show methane gas." },
      teens: { title: "The coldest known brown dwarf", text: "It is {methane} brighter at 4–4.75 µm than in the 3.3 µm methane band. That dip is methane’s fingerprint." },
      chip: "Methane test: {methane}" },
    { id: "r_dra", needs: ["brightness"],
      kids: { title: "The breathing star", text: "This giant star swells and shrinks, getting brighter and dimmer. One ‘breath’ takes about 245 days!" },
      teens: { title: "A star that pulsates", text: "R Draconis is a Mira variable that brightens and fades over about 245 days. SPHEREx caught it: {brightnessLc}." },
      chip: "{brightness}" },
    { id: "eps_indi_b", needs: ["distance"],
      kids: { title: "Two brown dwarfs, side by side", text: "A pair of brown dwarfs travels around the star Epsilon Indi, {distance} away." },
      teens: { title: "A brown-dwarf pair next door", text: "Epsilon Indi B is a pair of brown dwarfs {distance} away. It moved {moved} between {span}." },
      chip: "{distance} away" },
  ];
  const fill = (s, f) => String(s).replace(/\{(\w+)\}/g, (_, k) => f[k] || "");
  /** The stories to show for a mode, built from loaded targets (id → target.json). */
  function buildStories(mode, targets) {
    const level = mode === "kids" ? "kids" : "teens";
    return STORIES.map((s) => {
      const t = targets[s.id], f = facts(t);
      if (!t || s.needs.some((k) => !f[k])) return null;
      return { id: s.id, name: f.name, title: fill(s[level].title, f), text: fill(s[level].text, f), chip: fill(s.chip, f) };
    }).filter(Boolean);
  }

  /** Mission scoring: how close a tap (0–1 frame units) is to the true earlier position (0–1). */
  function judgeTap(tap, truth, mode) {
    const d = Math.hypot(tap.x - truth.x, tap.y - truth.y);
    const r = mode === "kids" ? 0.2 : 0.12;
    return { found: d <= r, distance: d };
  }
  /** Track points of a target in frame units (0–1, origin top-left), as home.js draws them. */
  function trackUnits(t, ch) {
    const N = t.grid.npix;
    return (t.track || []).filter((p) => (p.ch || "w2") === ch).sort((a, b) => a.year - b.year)
      .map((p) => ({ year: p.year, mission: p.mission, x: (p.x + 0.5) / N, y: (N - 1 - p.y + 0.5) / N }));
  }

  const api = { facts, buildStories, judgeTap, trackUnits, STORIES };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.ExplorerHome = api;

  /* ------------------------------------------------------------------ browser ------------------------------------ */
  const doc = root.document, E = root.Explorer;
  if (!doc || !E) return;
  const $ = (id) => doc.getElementById(id);
  const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); });
  const html = doc.documentElement;
  let data = null;                    // { list, targets: {id: target.json} }

  async function load() {
    if (data) return data;
    const list = await getJSON("data/index.json");
    const ts = await Promise.all(list.map((e) => getJSON(`data/${e.id}/target.json`).catch(() => null)));
    const targets = {};
    list.forEach((e, k) => { if (ts[k]) targets[e.id] = ts[k]; });
    data = { list, targets };
    return data;
  }
  api.load = load;                    // shared with explorer-learn.js, stories.js (one fetch per page)
  if (!doc.getElementById("discover") && !doc.getElementById("research")) return;   // other pages use only the helpers and load()
  const lastFrame = (t) => { const fr = (t.frames && (t.frames.w2 || t.frames.w1)) || []; return fr[fr.length - 1]; };

  /* ---------------- stories (Kids, Students) ---------------- */
  let storyIdx = 0;
  function renderStories(mode) {
    const host = $("storyDeck");
    if (!host || !data) return;
    const st = buildStories(mode, data.targets);
    if (!st.length) { host.innerHTML = ""; return; }
    storyIdx = Math.min(storyIdx, st.length - 1);
    const s = st[storyIdx], t = data.targets[s.id], fr = lastFrame(t), trk = trackUnits(t, "w2");
    const then = trk[0], now = trk[trk.length - 1];
    // draw a path only for targets whose evidence card says they moved (a steady star's track is just noise)
    const marks = facts(t).moved && then && now && then !== now ? `<svg class="st-marks" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <line x1="${then.x * 100}" y1="${then.y * 100}" x2="${now.x * 100}" y2="${now.y * 100}"/>
        <circle class="then" cx="${then.x * 100}" cy="${then.y * 100}" r="5.5"/><circle class="now" cx="${now.x * 100}" cy="${now.y * 100}" r="5.5"/></svg>` : "";
    host.innerHTML = `
      <div class="st-bars" aria-hidden="true">${st.map((_, k) => `<span class="${k < storyIdx ? "done" : k === storyIdx ? "on" : ""}"></span>`).join("")}</div>
      <article class="st-card" aria-roledescription="story" aria-label="${esc(s.title)}, story ${storyIdx + 1} of ${st.length}">
        <div class="st-sky">
          ${fr ? `<img src="data/${esc(s.id)}/${esc(fr.png)}" alt="Real infrared image of ${esc(s.name)} (${esc(fr.label)})" width="150" height="150">` : ""}
          ${marks}
          <span class="st-stamp">${esc(fr ? fr.label : "")}</span>
        </div>
        <div class="st-copy">
          <p class="st-kicker">${esc(s.name)}</p>
          <h3 class="st-title">${esc(s.title)}</h3>
          <p class="st-text">${esc(s.text)}</p>
          ${s.chip ? `<p class="st-chip"><span class="tag-chip data">Real data</span> ${esc(s.chip)}</p>` : ""}
          <a class="st-more" href="observatory.html?target=${encodeURIComponent(s.id)}">${mode === "kids" ? "See it move" : "Open in the Observatory"} <span aria-hidden="true">→</span></a>
        </div>
      </article>
      <div class="st-nav">
        <button type="button" class="st-prev" ${storyIdx === 0 ? "disabled" : ""} aria-label="Previous story">←</button>
        <span class="st-count" aria-live="polite">${storyIdx + 1} / ${st.length}</span>
        <button type="button" class="st-next" ${storyIdx === st.length - 1 ? "disabled" : ""} aria-label="Next story">→</button>
      </div>`;
    const go = (d) => { const n = storyIdx + d; if (n >= 0 && n < st.length) { storyIdx = n; renderStories(mode); host.querySelector(d > 0 ? ".st-next" : ".st-prev")?.focus(); } };
    host.querySelector(".st-prev").onclick = () => go(-1);
    host.querySelector(".st-next").onclick = () => go(1);
    host.onkeydown = (e) => { if (e.key === "ArrowRight") go(1); if (e.key === "ArrowLeft") go(-1); };
    // tap the right or left side of the picture, like a story
    host.querySelector(".st-sky").onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); go(e.clientX - r.left > r.width / 2 ? 1 : -1); };
  }

  /* ---------------- mission: where was it before? ---------------- */
  const MISSION = {
    kids: { ask: "Look! This star seems to have moved. Can you find where it was before? Tap the spot.",
      yes: "You found it! In 2010 the star was right there. It has been travelling ever since.",
      near: "So close! The dashed ring shows where it was in 2010. Stars that are near us really do move." },
    teens: { ask: "This is Barnard’s Star in 2026. Where was it in 2010? Tap your best guess.",
      yes: "Nailed it. You just measured motion the way Clyde Tombaugh found Pluto: by comparing two pictures.",
      near: "Not quite: the dashed ring is the 2010 position the pipeline measured. The gap is 16 years of motion." },
  };
  function renderMission(mode) {
    const host = $("mission");
    const t = data && data.targets.barnard;
    if (!host || !t) { if (host) host.hidden = true; return; }
    const lvl = mode === "kids" ? "kids" : "teens", txt = MISSION[lvl];
    const fr = t.frames.w2, then = trackUnits(t, "w2")[0], now = trackUnits(t, "w2").slice(-1)[0];
    host.hidden = false;
    host.innerHTML = `
      <div class="ms-sky" role="button" tabindex="0" aria-label="Barnard’s Star in 2026. Tap where you think it was in 2010.">
        <img src="data/barnard/${esc(fr[fr.length - 1].png)}" alt="" width="150" height="150">
        <svg class="ms-marks" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg>
        <span class="st-stamp">${esc(fr[fr.length - 1].label)}</span>
      </div>
      <div class="ms-copy">
        <p class="eyebrow">Mission 1 · Where was it before?</p>
        <p class="ms-ask">${esc(txt.ask)}</p>
        <p class="ms-result" aria-live="polite"></p>
        <div class="ms-follow" hidden></div>
        <button type="button" class="btn btn-ghost tiny ms-again" hidden>Try again</button>
      </div>`;
    const sky = host.querySelector(".ms-sky"), marks = host.querySelector(".ms-marks"), out = host.querySelector(".ms-result");
    const follow = host.querySelector(".ms-follow"), again = host.querySelector(".ms-again");
    let done = false;
    function answer(tap) {
      if (done) return;
      done = true;
      const j = judgeTap(tap, then, mode);
      marks.innerHTML = `<circle class="tap" cx="${tap.x * 100}" cy="${tap.y * 100}" r="3"/>
        <line x1="${then.x * 100}" y1="${then.y * 100}" x2="${now.x * 100}" y2="${now.y * 100}"/>
        <circle class="then" cx="${then.x * 100}" cy="${then.y * 100}" r="6"/><circle class="now" cx="${now.x * 100}" cy="${now.y * 100}" r="6"/>`;
      out.textContent = j.found ? txt.yes : txt.near;
      out.className = "ms-result " + (j.found ? "yes" : "near");
      again.hidden = false;
      if (lvl === "teens") {
        follow.hidden = false;
        follow.innerHTML = `<p class="ms-q">Is the star actually moving, or is Earth’s movement changing our view?</p>
          <div class="ms-opts"><button type="button" class="btn btn-ghost tiny" data-a="star">The star is moving</button><button type="button" class="btn btn-ghost tiny" data-a="earth">Earth’s movement</button></div>
          <p class="ms-why" hidden>Both happen, but this jump is the star’s own motion: ${esc(facts(t).measured || "about 10″/yr")}. Earth’s yearly loop around the Sun shifts Barnard’s Star by only ±0.55″ (parallax), far smaller than what you just saw.</p>`;
        follow.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => { follow.querySelectorAll("[data-a]").forEach((x) => x.setAttribute("aria-pressed", x === b)); follow.querySelector(".ms-why").hidden = false; });
      }
      try { doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id: "mission-where-before", found: j.found } })); } catch { /* old browsers */ }
    }
    sky.onclick = (e) => { const r = sky.getBoundingClientRect(); answer({ x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }); };
    sky.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); answer({ x: 0.5, y: 0.5 }); } };   // keyboard: guess the centre
    again.onclick = () => renderMission(mode);
  }

  /* ---------------- research panel ---------------- */
  /* research table: filter, sort and export (Research.tableRows/filterRows/sortRows/rowsCSV) */
  const RS = { q: "", cls: "", key: "name", dir: 1 };
  const COLS = [["name", "Target"], ["ra", "RA (deg, ICRS)"], ["dec", "Dec (deg)"], ["epochs", "Epochs · 4.6 µm"], ["measured", "Measured motion (″/yr)"],
    ["catalogue", "Catalogue (″/yr)"], ["dmag", "Δm (mag, ±1σ)"], ["cls", "Classification · confidence"], [null, "Data"]];
  function renderResearch() {
    const host = $("researchRows"), R = root.Research;
    if (!host || !data || !R) return;
    const all = R.tableRows(data.list, data.targets);
    const sel = $("rpClass");
    if (sel && sel.options.length <= 1) [...new Set(all.map((r) => r.cls).filter(Boolean))].sort().forEach((c) => sel.add(new Option(c, c)));
    const rows = R.sortRows(R.filterRows(all, RS), RS.key, RS.dir);
    const f = (v, n) => (v == null ? "—" : v.toFixed(n));
    const head = host.closest("table").querySelector("thead tr");
    head.innerHTML = COLS.map(([k, label]) => k
      ? `<th scope="col" aria-sort="${RS.key === k ? (RS.dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="rp-sort" data-k="${k}">${label}<span aria-hidden="true">${RS.key === k ? (RS.dir > 0 ? " ▲" : " ▼") : ""}</span></button></th>`
      : `<th scope="col">${label}</th>`).join("");
    head.querySelectorAll(".rp-sort").forEach((b) => (b.onclick = () => { const k = b.dataset.k; RS.dir = RS.key === k ? -RS.dir : 1; RS.key = k; renderResearch(); head.querySelector(`[data-k="${k}"]`)?.focus(); }));
    host.innerHTML = rows.length ? rows.map((r) => `<tr>
        <th scope="row">${esc(r.name)}</th>
        <td class="mono">${f(r.ra, 5)}</td><td class="mono">${r.dec >= 0 ? "+" : ""}${f(r.dec, 5)}</td>
        <td class="mono">${r.epochs} <span class="dim">(${f(r.first, 2)}–${f(r.last, 2)})</span></td>
        <td class="mono">${f(r.measured, 3)}</td><td class="mono">${f(r.catalogue, 3)}</td>
        <td class="mono">${r.dmag == null ? "—" : `${r.dmag >= 0 ? "+" : ""}${r.dmag.toFixed(2)} ± ${r.dmagErr.toFixed(2)}`}</td>
        <td>${esc(r.cls || "—")} <span class="dim">· ${esc(r.confidence)}</span></td>
        <td><a href="data/${encodeURIComponent(r.id)}/target.json" download>target.json</a> · <a href="observatory.html?target=${encodeURIComponent(r.id)}&amp;mode=research">open</a></td>
      </tr>`).join("") : '<tr><td colspan="9">No targets match.</td></tr>';
    const n = $("rpCount"); if (n) n.textContent = `${rows.length} of ${all.length} targets`;
    const dl = $("rpCsv"); if (dl) dl.onclick = () => root.ShareKit.download("wanderers-targets.csv", R.rowsCSV(rows), "text/csv");
  }
  function wireResearch() {
    const q = $("rpSearch"), c = $("rpClass");
    if (q) q.oninput = () => { RS.q = q.value; renderResearch(); };
    if (c) c.onchange = () => { RS.cls = c.value; renderResearch(); };
  }
  wireResearch();

  /* ---------------- explanations by mode ---------------- */
  function renderExplain(mode) {
    // General Explorer keeps the page's own wording; the other modes swap in their layer of the same fact
    doc.querySelectorAll("[data-explain]").forEach((el) => {
      if (el.dataset.orig === undefined) el.dataset.orig = el.innerHTML;
      if (mode === "adults") { el.innerHTML = el.dataset.orig; return; }
      const s = E.explain(el.dataset.explain, mode);
      if (s) el.textContent = s;
    });
  }

  /* ---------------- scientist view toggle (Kids, Students) ---------------- */
  function wireScience() {
    const b = $("showScience");
    if (!b) return;
    const sync = () => { const on = html.classList.contains("show-science"); b.setAttribute("aria-expanded", on); b.textContent = on ? "Hide the scientist view" : "Show the scientist view"; };
    b.onclick = () => { html.classList.toggle("show-science"); sync(); if (html.classList.contains("show-science")) $("science")?.scrollIntoView({ behavior: "smooth" }); };
    // nav links to sections that are folded away open the scientist view first
    doc.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener("click", () => {
      const t = doc.querySelector(a.getAttribute("href"));
      if (t && t.closest(".sci") && E.isPlayful(E.current()) && !html.classList.contains("show-science")) { html.classList.add("show-science"); sync(); }
    }));
    sync();
  }

  async function render(mode) {
    renderExplain(mode);
    if (mode === "adults") return;                       // General Explorer: the scientific homepage, untouched
    try { await load(); } catch { const d = $("storyDeck"); if (d) d.textContent = "Could not load the sky data. Please reload the page."; return; }
    if (E.isPlayful(mode)) { storyIdx = 0; renderStories(mode); renderMission(mode); }
    if (mode === "research") renderResearch();
  }
  doc.addEventListener("explorermodechange", (e) => { if (!E.isPlayful(e.detail.mode)) html.classList.remove("show-science"); render(e.detail.mode); });
  wireScience();
  if (E.started) render(E.current());                     // else the first "explorermodechange" renders it
})(typeof window !== "undefined" ? window : globalThis);
