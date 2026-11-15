/* WANDERERS explorer modes: "One universe, four ways to explore".
 *
 * A mode is an experience preference, not an age check. Nothing here asks for or stores an age, a birth date or any
 * personal information: only the chosen mode id, in this browser (localStorage key "wanderers-mode"). Research Mode is
 * open to everyone. Every mode reads the same data in app/data; modes change how it is explained and laid out, never
 * the measurements.
 *
 * Browser: sets <html data-mode="…"> as early as possible, adds a mode switcher to the page header, shows the
 * first-visit chooser and fires a "explorermodechange" event on document. Node: module.exports for the tests.
 * A link can preselect a mode for one visit with ?mode=kids|teens|adults|research (it is not saved until chosen).
 */
(function (root) {
  "use strict";

  const KEY = "wanderers-mode";
  const DEFAULT = "adults";
  const MODES = [
    { id: "kids", title: "Kids Explorer", tag: "Ages 6–12", playful: true,
      blurb: "Tap stars, solve sky puzzles and collect discoveries.",
      preview: ["Big pictures", "Mini missions", "Short facts"] },
    { id: "teens", title: "Student Explorer", tag: "Ages 13–17", playful: true,
      blurb: "Swipe through sky stories and test how astronomers think.",
      preview: ["Sky stories", "Challenges", "Real science, step by step"] },
    { id: "adults", title: "General Explorer", tag: "Adults", playful: false,
      blurb: "The full WANDERERS observatory, explained clearly.",
      preview: ["Time-lapse viewer", "Evidence cards", "Sky Compass"] },
    { id: "research", title: "Research Mode", tag: "Advanced users", playful: false,
      blurb: "Coordinates, epochs, uncertainties, provenance and data files.",
      preview: ["Data access", "Measured vs derived", "Citations"] },
  ];
  const IDS = MODES.map((m) => m.id);

  const isMode = (m) => IDS.includes(m);
  const byId = (id) => MODES.find((m) => m.id === id) || MODES.find((m) => m.id === DEFAULT);
  const isPlayful = (id) => byId(id).playful;

  /** ?mode= wins for this visit, then the saved choice; null means "not chosen yet" (show the chooser). */
  function resolve(saved, search) {
    let q = null;
    try { q = new URLSearchParams(search || "").get("mode"); } catch { q = null; }
    if (isMode(q)) return { mode: q, fromLink: true };
    if (isMode(saved)) return { mode: saved, fromLink: false };
    return { mode: null, fromLink: false };
  }
  function readSaved(storage) { try { return storage ? storage.getItem(KEY) : null; } catch { return null; } }
  function save(storage, id) { if (!isMode(id)) return false; try { storage && storage.setItem(KEY, id); return true; } catch { return false; } }

  /* Explanation layers. Same fact, told four ways: simpler words for younger explorers, never different science. */
  const EXPLAIN = {
    motion: {
      kids: "Stars look still, but some are moving. Over many years, a close star creeps across the sky.",
      teens: "Nearby stars drift across the sky. It is too slow to see in a night, but over a decade it adds up. Astronomers call it proper motion.",
      adults: "Nearby stars travel across the sky by a few arcseconds a year (proper motion). Comparing images years apart reveals it.",
      research: "Proper motion from multi-epoch astrometry (WISE 2010.5 to SPHEREx 2025–26), compared with Gaia DR3 propagated to each epoch.",
    },
    brightness: {
      kids: "Some stars get brighter and dimmer, like they are breathing.",
      teens: "Some stars change brightness: they pulsate, or dust passes in front of them. Comparing two sky surveys shows the change.",
      adults: "Comparing the two SPHEREx sky surveys, wavelength by wavelength, shows whether an object brightened or faded.",
      research: "Brightness change between SPHEREx surveys from PSF-wing or aperture photometry, in magnitudes with 1σ uncertainty.",
    },
    fingerprint: {
      kids: "Light has hidden colours our eyes can’t see. Those colours tell us what a star is made of.",
      teens: "SPHEREx splits infrared light into 102 colours. Gases like methane absorb certain colours, leaving a fingerprint.",
      adults: "SPHEREx measures a 0.75–5 µm spectrum; absorption bands of water, methane and CO/CO₂ reveal what an object is.",
      research: "Spectrum from aperture photometry of every SPHEREx image at the target, placed at each pixel’s WCS-WAVE wavelength; flagged pixels excluded.",
    },
    evidence: {
      kids: "We only say what the pictures show. If we’re not sure, we say so!",
      teens: "Every answer has to pass checks you can read. Anything unexplained stays a “candidate”, never a discovery.",
      adults: "Stated rules turn measurements into a classification and a confidence. Unmatched objects are candidates, never discoveries.",
      research: "Rule-based classification (see pipeline/evidence.py); measured values, derived quantities and AI-written interpretation are labelled separately.",
    },
  };
  /** The explanation of a concept at a mode's level (falls back to the General Explorer text). */
  function explain(concept, mode) {
    const c = EXPLAIN[concept];
    if (!c) return "";
    return c[isMode(mode) ? mode : DEFAULT] || c[DEFAULT];
  }

  const api = { KEY, DEFAULT, MODES, IDS, isMode, byId, isPlayful, resolve, readSaved, save, explain, EXPLAIN };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.Explorer = api;

  /* ------------------------------------------------------------------ browser ------------------------------------ */
  const doc = root.document;
  if (!doc) return;
  const html = doc.documentElement;
  const storage = (() => { try { return root.localStorage; } catch { return undefined; } })();
  const reduced = () => root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const first = resolve(readSaved(storage), root.location.search);
  let current = first.mode || DEFAULT;
  html.dataset.mode = current;

  // small original line icons, one per mode (no emoji, so they follow the theme colours)
  const ICONS = {
    kids: '<svg viewBox="0 0 48 48" aria-hidden="true"><path class="ic-a" d="M24 7l4.6 10.4 11.3 1.1-8.5 7.5 2.5 11.1L24 31.4l-9.9 5.7 2.5-11.1-8.5-7.5 11.3-1.1z"/><circle class="ic-b" cx="38.5" cy="8.5" r="2.2"/><circle class="ic-b" cx="9" cy="38" r="1.6"/></svg>',
    teens: '<svg viewBox="0 0 48 48" aria-hidden="true"><rect class="ic-l" x="7" y="9" width="18" height="30" rx="3"/><rect class="ic-a" x="15" y="6" width="22" height="36" rx="4"/><path class="ic-s" d="M20 28l5-6 4 4 3-3 3 5"/><circle class="ic-b" cx="31" cy="15" r="2.2"/></svg>',
    adults: '<svg viewBox="0 0 48 48" aria-hidden="true"><path class="ic-l" d="M39.8 21.4A16 16 0 1 1 35 12.3"/><ellipse class="ic-s" cx="24" cy="24" rx="13.5" ry="6.4" transform="rotate(-28 24 24)"/><circle class="ic-b" cx="25.6" cy="16.2" r="3"/></svg>',
    research: '<svg viewBox="0 0 48 48" aria-hidden="true"><path class="ic-l" d="M8 8v32h32"/><path class="ic-s" d="M12 33l7-9 6 4 6-11 7-6"/><circle class="ic-b" cx="19" cy="24" r="2.2"/><circle class="ic-b" cx="31" cy="17" r="2.2"/><path class="ic-l" d="M30 13v8M27 17h8"/></svg>',
  };

  function setMode(id, { persist = true, announce = true } = {}) {
    if (!isMode(id)) return;
    const changed = id !== current;
    current = id;
    if (persist) save(storage, id);
    if (!reduced()) { html.classList.add("mode-anim"); root.setTimeout(() => html.classList.remove("mode-anim"), 360); }
    html.dataset.mode = id;
    renderSwitcher();
    if (announce) doc.dispatchEvent(new root.CustomEvent("explorermodechange", { detail: { mode: id, changed } }));
  }
  api.current = () => current;
  api.setMode = setMode;

  /* ---- header switcher ---- */
  let switcher = null;
  function renderSwitcher() {
    if (!switcher) return;
    const m = byId(current);
    switcher.innerHTML = `<span class="ms-icon">${ICONS[m.id]}</span><span class="ms-label">${m.title}</span>`;
    switcher.setAttribute("aria-label", `Explorer mode: ${m.title}. Change mode`);
  }
  function mountSwitcher() {
    const tools = doc.querySelector(".site-head .head-tools");
    if (!tools || tools.querySelector(".mode-switch")) return;
    switcher = doc.createElement("button");
    switcher.type = "button";
    switcher.className = "mode-switch";
    switcher.addEventListener("click", () => openChooser(false));
    tools.insertBefore(switcher, tools.firstChild);
    renderSwitcher();
  }

  /* ---- chooser (first visit, and from the switcher) ---- */
  let dialog = null, picked = current, lastFocus = null;
  function buildChooser() {
    dialog = doc.createElement("dialog");
    dialog.className = "chooser";
    dialog.setAttribute("aria-labelledby", "chooserTitle");
    dialog.setAttribute("aria-describedby", "chooserSub");
    dialog.innerHTML = `
      <form method="dialog" class="ch-inner">
        <div class="ch-brand" aria-hidden="true">${doc.querySelector(".site-head .logo svg")?.outerHTML || ""}<span class="wordmark">WANDERERS</span></div>
        <h2 id="chooserTitle" class="ch-title">How would you like to explore the universe?</h2>
        <p id="chooserSub" class="ch-sub">Choose your experience. You can change it anytime.</p>
        <div class="ch-grid" role="radiogroup" aria-labelledby="chooserTitle">
          ${MODES.map((m) => `
          <button type="button" class="ch-card" role="radio" aria-checked="false" data-mode="${m.id}">
            <span class="ch-icon">${ICONS[m.id]}</span>
            <span class="ch-name">${m.title}</span>
            <span class="ch-tag">${m.tag}</span>
            <span class="ch-blurb">${m.blurb}</span>
            <span class="ch-preview">${m.preview.map((p) => `<span>${p}</span>`).join("")}</span>
            <svg class="ch-check" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.5"/><path d="M6 10.4l2.6 2.6L14.2 7.4"/></svg>
          </button>`).join("")}
        </div>
        <button type="submit" class="ch-go" value="go">Start Exploring <span aria-hidden="true">→</span></button>
        <p class="ch-note">No account or personal information required. Modes are a preference, not an age check: anyone can use Research Mode.</p>
      </form>`;
    doc.body.appendChild(dialog);
    const cards = [...dialog.querySelectorAll(".ch-card")];
    const mark = () => cards.forEach((c) => { const on = c.dataset.mode === picked; c.setAttribute("aria-checked", on); c.tabIndex = on ? 0 : -1; });
    cards.forEach((c, k) => {
      c.addEventListener("click", () => { picked = c.dataset.mode; mark(); });
      c.addEventListener("dblclick", () => { picked = c.dataset.mode; dialog.close("go"); });
      c.addEventListener("keydown", (e) => {                      // radio-group arrow keys
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!step) return;
        e.preventDefault();
        const n = cards[(k + step + cards.length) % cards.length];
        picked = n.dataset.mode; mark(); n.focus();
      });
    });
    dialog.addEventListener("close", () => {
      if (dialog.returnValue === "go") setMode(picked);
      else if (!readSaved(storage)) setMode(current);                // Esc on the first visit: keep the current mode
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    });
    dialog._mark = mark;
  }
  function openChooser(firstVisit) {
    if (!dialog) buildChooser();
    picked = current;
    dialog.returnValue = "";
    dialog.classList.toggle("is-first", !!firstVisit);
    dialog._mark();
    lastFocus = doc.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    const on = dialog.querySelector('.ch-card[aria-checked="true"]');
    if (on) on.focus();
  }
  api.openChooser = openChooser;

  function start() {
    api.started = true;
    mountSwitcher();
    if (!first.mode) openChooser(true);                              // first visit on a page that loads this file
    doc.dispatchEvent(new root.CustomEvent("explorermodechange", { detail: { mode: current, changed: false, initial: true } }));
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start); else start();
})(typeof window !== "undefined" ? window : globalThis);
