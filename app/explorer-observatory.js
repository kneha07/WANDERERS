/* WANDERERS Observatory, adaptive layer. app.js is not changed: this file watches which target is showing (the
 * ?target= in the URL and the #tName heading) and reads the same data/<id>/target.json.
 *
 * Kids and Student Explorer: a guide panel (what am I looking at, in their words), a before/after comparison slider
 * of the first and last real frames, a "spot the change" question answered from the evidence card, short intros to
 * Through Webb and Starquakes, and a simpler tool set ("Show all tools" brings everything back). Community
 * classification (public GitHub issue form) and the free-text Ask box are not shown to Kids; classification is not
 * shown to Students either.
 * General Explorer: the original Observatory, plus "Share a factual summary".
 * Research Mode: the original Observatory, plus a per-epoch measurement table and reproducible exports. */
(function (root) {
  "use strict";
  const doc = root.document, E = root.Explorer, H = root.ExplorerHome, Rs = root.Research, S = root.ShareKit;
  if (!doc || !E || !H || !Rs || !S || !doc.getElementById("flipView")) return;
  const $ = (id) => doc.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const html = doc.documentElement;
  const cache = new Map();
  // insert only with what the browser (or a test's stand-in DOM) supports; otherwise the layer simply stays out
  const put = (ref, how, node) => { if (ref && typeof ref[how] === "function") { ref[how](node); return true; } return false; };
  const onClick = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  const getTarget = (id) => {
    if (!cache.has(id)) cache.set(id, fetch(`data/${encodeURIComponent(id)}/target.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
    return cache.get(id);
  };
  const currentId = () => new URLSearchParams(root.location.search).get("target");
  const level = () => (E.current() === "kids" ? "kids" : "teens");

  /* ---------- containers (added once, after the sky panel's heading) ---------- */
  const skyPanel = doc.querySelector(".panel.sky"), skyHead = skyPanel && skyPanel.querySelector(".sky-head");
  // no place to mount (a stripped-down or test DOM): leave the Observatory exactly as it is
  if (!skyHead || typeof skyHead.after !== "function" || typeof skyPanel.appendChild !== "function") return;
  const guide = doc.createElement("section");
  guide.className = "obs-guide playful-only"; guide.id = "obsGuide"; guide.setAttribute("aria-label", "Guide to this target");
  put(skyHead, "after", guide);
  const tools = doc.createElement("div");
  tools.className = "obs-tools-toggle playful-only";
  tools.innerHTML = '<button type="button" class="btn btn-ghost tiny" id="showTools" aria-expanded="false">Show all tools</button>';
  put(skyPanel, "appendChild", tools);
  const research = doc.createElement("section");
  research.className = "obs-research"; research.id = "obsResearch"; research.setAttribute("aria-label", "Measurements and exports");
  put(skyPanel, "appendChild", research);
  const evIntro = doc.createElement("div");
  evIntro.className = "ev-simple playful-only"; evIntro.id = "evSimple";
  const verdict = $("verdict");
  put(verdict, "before", evIntro);
  const webbIntro = doc.createElement("p"), quakeIntro = doc.createElement("p");
  webbIntro.className = quakeIntro.className = "obs-intro playful-only";
  webbIntro.dataset.explain = "webb"; quakeIntro.dataset.explain = "starquake";
  put($("webbView"), "prepend", webbIntro);
  put($("targetQuake"), "before", quakeIntro);

  const showTools = $("showTools");
  if (showTools) showTools.onclick = () => { const on = html.classList.toggle("show-tools"); showTools.setAttribute("aria-expanded", on); showTools.textContent = on ? "Show fewer tools" : "Show all tools"; };
  $("play")?.addEventListener("click", () => { if (E.isPlayful(E.current())) doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id: "blink" } })); });

  /* ---------- guide (Kids, Students) ---------- */
  function frameList(t) { const f = t.frames || {}; return f.w2 && f.w2.length ? f.w2 : f.w1 && f.w1.length ? f.w1 : []; }
  function changeAnswer(t, lv) {
    const checks = (t.evidence && t.evidence.checks) || [];
    const moved = checks.find((c) => c.state === "ok" && /^Moved /.test(c.text)), bright = checks.find((c) => c.state === "ok" && /^(Faded|Brightened) /.test(c.text));
    if (lv === "kids") {
      if (moved) return "Yes! It moved. Look how far it travelled between the two pictures.";
      if (bright) return "It didn’t move, but its brightness changed between visits.";
      return "Nothing big changed here, and that’s a real result too! Scientists check steady stars as carefully as moving ones.";
    }
    return [moved, bright].filter(Boolean).map((c) => c.text.split(" (")[0]).join(" · ") || "No measurable motion or brightness change in these frames. A steady result is still a result.";
  }
  function renderGuide(t) {
    const lv = level(), fr = frameList(t), f = H.facts(t);
    const story = (H.buildStories(lv, { [t.id]: t })[0]) || null;
    const first = fr[0], last = fr[fr.length - 1];
    guide.innerHTML = `
      <div class="og-copy">
        <p class="eyebrow">${lv === "kids" ? "What am I looking at?" : "Field guide"}</p>
        <h3 class="og-title">${esc(story ? story.title : t.name)}</h3>
        <p class="og-text">${esc(story ? story.text : (t.kind || f.classification))}</p>
      </div>
      ${first && last && first !== last ? `
      <figure class="og-compare">
        <div class="og-stage" style="--cut:50%">
          <img class="og-after" src="data/${encodeURIComponent(t.id)}/${encodeURIComponent(last.png)}" alt="${esc(last.label)}" width="150" height="150">
          <img class="og-before" src="data/${encodeURIComponent(t.id)}/${encodeURIComponent(first.png)}" alt="${esc(first.label)}" width="150" height="150">
          <span class="og-line" aria-hidden="true"></span>
          <span class="st-stamp og-l">${esc(first.label)}</span><span class="st-stamp og-r">${esc(last.label)}</span>
        </div>
        <label class="og-range"><span>${lv === "kids" ? "Slide to compare" : "Before ↔ after"}</span>
          <input type="range" min="0" max="100" value="50" aria-label="Compare ${esc(first.label)} with ${esc(last.label)}"></label>
        <figcaption class="small-note">Real images, same patch of sky, same infrared colour. ${lv === "kids" ? "" : "Left: earliest frame; right: latest."}</figcaption>
      </figure>` : ""}
      <div class="og-ask">
        <p class="og-q">${lv === "kids" ? "Did anything move or change?" : "What changed between the epochs?"}</p>
        <button type="button" class="btn btn-ghost tiny" id="ogReveal" aria-expanded="false">${lv === "kids" ? "Show me" : "Check the evidence"}</button>
        <p class="og-a" id="ogAnswer" hidden></p>
      </div>`;
    const stage = guide.querySelector(".og-stage"), range = guide.querySelector(".og-range input");
    if (stage && range) {
      let told = false;
      range.oninput = () => { stage.style.setProperty("--cut", range.value + "%"); if (!told) { told = true; doc.dispatchEvent(new root.CustomEvent("explorerdiscovery", { detail: { id: "compare-epochs" } })); } };
    }
    onClick("ogReveal", () => { const a = $("ogAnswer"); if (!a) return; a.hidden = !a.hidden; a.textContent = changeAnswer(t, lv); $("ogReveal").setAttribute("aria-expanded", !a.hidden); });
    const ev = t.evidence || {};
    evIntro.innerHTML = `<p class="ev-s-score">${ev.checks_passed ?? "–"} of ${ev.checks_needed || (ev.checks || []).length || "–"} ${lv === "kids" ? "clues agree" : "key checks support it"}</p><p class="ev-s-text">${esc(E.explain("evidence", E.current()))}</p>`;
  }

  /* ---------- research panel (Research Mode) and summary sharing (General Explorer) ---------- */
  function renderResearch(t) {
    const mode = E.current();
    const pageUrl = `${root.location.origin}${root.location.pathname}?target=${encodeURIComponent(t.id)}`;
    if (mode === "adults") {
      research.innerHTML = `<div class="or-share"><button type="button" class="btn btn-ghost tiny" id="orShare">Share a factual summary</button><span class="small-note" id="orShareOut" aria-live="polite"></span></div>`;
      onClick("orShare", async () => { const r = await S.share({ title: `${t.name} · WANDERERS`, text: Rs.shortSummary(t), url: pageUrl }); const o = $("orShareOut"); if (o) o.textContent = r === "copied" ? "Summary copied." : r === "shared" ? "Shared." : r === "cancelled" ? "" : "Could not share."; });
      return;
    }
    if (mode !== "research") { research.innerHTML = ""; return; }
    const trk = (t.track || []).slice().sort((a, b) => (a.ch || "").localeCompare(b.ch || "") || a.year - b.year);
    const md = Rs.summary(t, { url: pageUrl, release: doc.getElementById("spherexStatus")?.textContent?.trim() || "" });
    research.innerHTML = `
      <div class="panel-row"><p class="panel-k mono">Research · measurements</p><span class="tag-chip data">Measured</span></div>
      <div class="or-table" role="region" aria-label="Measured positions per epoch" tabindex="0"><table>
        <thead><tr><th scope="col">Epoch (yr)</th><th scope="col">Mission</th><th scope="col">Channel</th><th scope="col">RA (deg)</th><th scope="col">Dec (deg)</th><th scope="col">Offset from prediction (″)</th></tr></thead>
        <tbody>${trk.length ? trk.map((p) => `<tr><td class="mono">${p.year.toFixed(3)}</td><td>${esc(p.mission)}</td><td class="mono">${esc(p.ch || "w2")}</td><td class="mono">${p.ra != null ? p.ra.toFixed(6) : "—"}</td><td class="mono">${p.dec != null ? p.dec.toFixed(6) : "—"}</td><td class="mono">${p.offset_arcsec != null ? p.offset_arcsec.toFixed(3) : "—"}</td></tr>`).join("") : '<tr><td colspan="6">No measured positions.</td></tr>'}</tbody>
      </table></div>
      <p class="small-note">Offset: measured position minus the predicted position (catalogue proper motion and parallax) at each epoch. It is a residual, not a formal uncertainty; 1 SPHEREx pixel is 6.15″.</p>
      <div class="or-actions">
        <button type="button" class="btn btn-ghost tiny" id="orCopy">Copy summary (Markdown)</button>
        <button type="button" class="btn btn-ghost tiny" id="orMd">Download summary .md</button>
        <button type="button" class="btn btn-ghost tiny" id="orTrack">Positions · CSV</button>
        ${(t.spectrum || []).length ? '<button type="button" class="btn btn-ghost tiny" id="orSpec">Spectrum · CSV</button>' : ""}
        <a class="btn btn-ghost tiny" href="data/${encodeURIComponent(t.id)}/target.json" download>target.json</a>
        <span class="small-note" id="orOut" aria-live="polite"></span>
      </div>
      <details class="or-preview"><summary>Preview the summary</summary><pre>${esc(md)}</pre></details>`;
    const base = S.safeName(`wanderers-${t.id}`, "x").replace(/\.x$/, "");
    onClick("orCopy", async () => { const o = $("orOut"); const ok = await S.copy(md); if (o) o.textContent = ok ? "Copied." : "Copy failed; use Download."; });
    onClick("orMd", () => S.download(`${base}-summary.md`, md, "text/markdown"));
    onClick("orTrack", () => S.download(`${base}-positions.csv`, Rs.trackCSV(t), "text/csv"));
    onClick("orSpec", () => S.download(`${base}-spectrum.csv`, Rs.spectrumCSV(t), "text/csv"));
  }

  /* ---------- explanation layers on this page ---------- */
  function renderExplain(mode) {
    doc.querySelectorAll(".obs-intro[data-explain]").forEach((el) => { el.textContent = E.explain(el.dataset.explain, mode); });
  }

  let shownId = null;
  async function refresh(force) {
    const id = currentId();
    if (!id) return;
    if (id === shownId && !force) return;
    shownId = id;
    const t = await getTarget(id);
    if (!t || id !== currentId()) return;
    if (E.isPlayful(E.current())) renderGuide(t); else { guide.innerHTML = ""; evIntro.innerHTML = ""; }
    renderResearch(t);
  }
  const title = $("tName");
  if (title && typeof root.MutationObserver === "function") new root.MutationObserver(() => refresh(false)).observe(title, { childList: true, characterData: true, subtree: true });
  doc.addEventListener("explorermodechange", (e) => { renderExplain(e.detail.mode); if (!E.isPlayful(e.detail.mode)) html.classList.remove("show-tools"); refresh(true); });
  if (E.started) { renderExplain(E.current()); refresh(true); }
})(typeof window !== "undefined" ? window : globalThis);
