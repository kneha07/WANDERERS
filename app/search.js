/* Star search shared by the console and the Sky Compass.
 * Data: app/data/stars.json, built from the HYG database v4.0 (Hipparcos + Yale Bright Star + Gliese, CC BY-SA 4.0):
 * every naked-eye star, every star with an IAU name, every star within ~33 light-years, plus the WANDERERS targets.
 * Typing shows names that START with what you typed first, then names with a word starting with it, brightest first. */
(function (root) {
  let STARS = null, loading = null;
  const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/['’]/g, "");

  function load(base = "data/") {
    if (STARS) return Promise.resolve(STARS);
    if (!loading) loading = fetch(base + "stars.json").then((r) => r.json()).then((rows) => {
      STARS = rows.map((r, i) => {
        const alt = r[1] ? r[1].split("|") : [];
        const w = (r[8] || "").match(/W:(\w+)/);
        return { id: w ? w[1] : `star${i}`, name: r[0], alt, ra: r[2], dec: r[3], mag: r[4], spect: r[5], dist: r[6], con: r[7],
          variable: (r[8] || "").includes("V"), near: (r[8] || "").includes("N"), wanderers: w ? w[1] : null,
          pmra: r[9] ?? null, pmdec: r[10] ?? null, rv: r[11] ?? null, key: r[12] || null,   // motion for the path model (link_paths.py)
          _keys: [r[0], ...alt].map(norm) };
      });
      return STARS;
    });
    return loading;
  }

  function search(q, limit = 12) {
    if (!STARS) return [];
    q = norm(q.trim());
    if (!q) return [];
    const main = [], other = [], words = [];          // main name starts with it > another name does > a word does
    for (const s of STARS) {
      if (s._keys[0].startsWith(q)) { main.push(s); continue; }
      let best = 0;
      for (const k of s._keys) {
        if (k.startsWith(q)) { best = 2; break; }
        if (best < 1 && (k.includes(" " + q) || k.includes("-" + q))) best = 1;
      }
      if (best === 2) other.push(s); else if (best === 1) words.push(s);
    }
    const rank = (a, b) => (b.wanderers ? 1 : 0) - (a.wanderers ? 1 : 0) || (a.mag ?? 50) - (b.mag ?? 50);
    return [...main.sort(rank), ...other.sort(rank), ...words.sort(rank)].slice(0, limit);
  }

  // which of a star's names matched the query (to show "Sirius · Alpha Canis Majoris")
  function matchedName(s, q) {
    q = norm(q.trim());
    const all = [s.name, ...s.alt];
    return all.find((n) => norm(n).startsWith(q)) || all.find((n) => norm(n).includes(" " + q)) || s.name;
  }

  // plain-language facts from the spectral type, brightness and distance
  // How far something is, three ways a person can feel it: in km, as light's travel time, and as a trip on Voyager 1.
  const KM_LY = 9.4607e12, C_KMS = 299792.458, VOYAGER_KMS = 17;
  function bigNumber(n) {   // 384,400 / 225 million / 237 trillion / 2.4 x 10^19
    if (n < 1e6) return Math.round(n).toLocaleString("en-US");
    for (const [v, w] of [[1e15, "quadrillion"], [1e12, "trillion"], [1e9, "billion"], [1e6, "million"]]) {
      if (n >= v && n < v * 1000) { const k = n / v; return `${k < 10 ? k.toFixed(1) : Math.round(k).toLocaleString("en-US")} ${w}`; }
    }
    const e = Math.floor(Math.log10(n)); return `${(n / 10 ** e).toFixed(1)} × 10^${e}`;
  }
  function span(sec) {      // 1.3 seconds / 8.3 minutes / 4.2 years / 2.5 million years
    const yr = sec / 31557600;
    if (sec < 90) return `${sec.toFixed(1)} seconds`;
    if (sec < 5400) return `${(sec / 60).toFixed(1)} minutes`;
    if (sec < 172800) return `${(sec / 3600).toFixed(1)} hours`;
    if (yr < 1) return `${Math.round(sec / 86400)} days`;
    return `${yr < 10 ? yr.toFixed(1) : bigNumber(yr)} years`;
  }
  function distanceLines(km) {
    return [`${bigNumber(km)} km from you.`,
      `At the speed of light you would arrive in ${span(km / C_KMS)}.`,
      `Voyager 1, our fastest probe leaving the Solar System (17 km/s), would need ${span(km / VOYAGER_KMS)}.`];
  }

  // Look-back: light from far away left long ago. For scale, the event in history (or Earth's history) nearest in time,
  // on a log scale, with its own date, so the sentence stays true even when the two dates differ.
  const EVENTS = [[123, "the Wright brothers made the first powered flight (1903)"], [339, "Isaac Newton published his laws of motion and gravity (1687)"],
    [416, "Galileo first turned a telescope to the sky (1610)"], [534, "Columbus crossed the Atlantic (1492)"],
    [1026, "Vikings reached North America (about 1000 CE)"], [2026, "the Common Era began (year 1)"],
    [4590, "the Great Pyramid of Giza was built (about 2560 BCE)"], [5300, "people in Mesopotamia invented writing (about 3200 BCE)"],
    [11600, "the last ice age ended and farming began (about 11,600 years ago)"], [17000, "people painted the caves of Lascaux (about 17,000 years ago)"],
    [40000, "people made the first known cave art (about 40,000 years ago)"], [300000, "the first Homo sapiens lived in Africa (about 300,000 years ago)"],
    [2.6e6, "early humans made the first stone tools (about 2.6 million years ago)"], [66e6, "an asteroid ended the age of the dinosaurs (66 million years ago)"],
    [230e6, "the first dinosaurs appeared (about 230 million years ago)"], [538e6, "the first animals with eyes and shells filled the seas (538 million years ago)"],
    [4.54e9, "the Earth formed (4.54 billion years ago)"]];
  function lookBack(ly) {
    if (!(ly >= 100)) return "";
    const [, what] = EVENTS.reduce((a, e) => (Math.abs(Math.log(e[0] / ly)) < Math.abs(Math.log(a[0] / ly)) ? e : a));
    return `For scale: ${what}.`;
  }

  function describe(s) {
    const out = [];
    const sp = (s.spect || "").trim(), cls = sp.replace(/^(sd|d|g|c)/, "")[0];
    const COLOUR = { O: ["blue", "over 30,000 K"], B: ["blue-white", "10,000–30,000 K"], A: ["white", "7,500–10,000 K"],
      F: ["yellow-white", "6,000–7,500 K"], G: ["yellow, like the Sun", "5,200–6,000 K"], K: ["orange", "3,700–5,200 K"],
      M: ["red", "2,400–3,700 K"], L: ["dark red (brown dwarf)", "1,300–2,400 K"], T: ["methane brown dwarf", "500–1,300 K"],
      Y: ["the coldest brown dwarfs", "below 500 K"] };
    let kind = "";
    if (/^sd/.test(sp)) kind = "subdwarf (old, metal-poor star)";
    else if (/^D/.test(sp)) kind = "white dwarf (the leftover core of a dead star)";
    else if (/(?<![IV])(Ia|Iab|Ib|I)(?![IV])/.test(sp.replace(/^[OBAFGKMLTY][0-9.]*/, ""))) kind = "supergiant";   // a lone I, not part of II/III/IV
    else if (/III/.test(sp)) kind = "giant";
    else if (/II/.test(sp)) kind = "bright giant";
    else if (/IV/.test(sp)) kind = "subgiant";
    else if (/V/.test(sp)) kind = "main-sequence star (burning hydrogen, like the Sun)";
    if (COLOUR[cls]) out.push(`Colour ${COLOUR[cls][0]}, surface about ${COLOUR[cls][1]}${kind ? `: a ${kind}` : ""} (spectral type ${sp}).`);
    else if (sp) out.push(`Spectral type ${sp}${kind ? `: a ${kind}` : ""}.`);
    if (s.mag != null) out.push(s.mag <= 1 ? `One of the brightest stars in the sky (magnitude ${s.mag}).`
      : s.mag <= 6 ? `Visible to the naked eye (magnitude ${s.mag}).` : `Too faint for the naked eye (magnitude ${s.mag}); binoculars or a telescope needed.`);
    if (s.dist) {
      const yr = new Date().getFullYear() - Math.round(s.dist);
      out.push(`${s.dist < 100 ? s.dist.toFixed(1) : Math.round(s.dist).toLocaleString()} light-years away: the light you see left it ${s.dist < 1000 ? `around ${yr}` : `about ${Math.round(s.dist).toLocaleString()} years ago`}.`);
      out.push(...distanceLines(s.dist * KM_LY));
      if (lookBack(s.dist)) out.push(lookBack(s.dist));
    }
    if (s.near) out.push("One of the Sun's close neighbours (within about 33 light-years).");
    if (s.variable) out.push("A variable star: its brightness changes.");
    if (s.con) out.push(`In the constellation ${s.con}.`);
    return out;
  }

  // rounded before splitting, so 59.96 s becomes the next minute instead of "60.0s"
  const hms = (deg) => { const c = Math.round((((deg % 360) + 360) % 360) / 15 * 36000) % 864000;   // tenths of a second of time
    return `${String(Math.floor(c / 36000)).padStart(2, "0")}h${String(Math.floor(c / 600) % 60).padStart(2, "0")}m${((c % 600) / 10).toFixed(1).padStart(4, "0")}s`; };
  const dms = (deg) => { const c = Math.round(Math.abs(deg) * 3600);   // whole arcseconds
    return `${deg < 0 ? "-" : "+"}${String(Math.floor(c / 3600)).padStart(2, "0")}d${String(Math.floor(c / 60) % 60).padStart(2, "0")}m${String(c % 60).padStart(2, "0")}s`; };

  // wire an <input> to a suggestion list; onPick(star) is called with the chosen star
  function attach(input, list, onPick) {
    let items = [], active = -1;
    const esc = (t) => t.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    const render = () => {
      if (!items.length) { list.hidden = !input.value.trim(); list.innerHTML = input.value.trim() ? "<li class='none'>No star by that name in our list</li>" : ""; return; }
      list.hidden = false;
      list.innerHTML = items.map((s, i) => {
        const m = matchedName(s, input.value), sub = [m !== s.name ? m : s.alt[0], s.con, s.mag != null ? `mag ${s.mag}` : ""].filter(Boolean).join(" · ");
        return `<li role="option" data-i="${i}" class="${i === active ? "on" : ""}"><b>${esc(s.name)}</b>${s.wanderers ? ' <em>WANDERERS analysis</em>' : ""}<span>${esc(sub)}</span></li>`;
      }).join("");
    };
    const pick = (i) => { const s = items[i]; if (!s) return; input.value = s.name; list.hidden = true; onPick(s); };
    input.addEventListener("input", async () => { await load(); items = search(input.value); active = -1; render(); });
    input.addEventListener("focus", () => load());
    input.addEventListener("keydown", (e) => {
      if (list.hidden || !items.length) return;
      if (e.key === "ArrowDown") { active = (active + 1) % items.length; render(); e.preventDefault(); }
      if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
      if (e.key === "Enter") { pick(active < 0 ? 0 : active); e.preventDefault(); }
      if (e.key === "Escape") list.hidden = true;
    });
    list.addEventListener("pointerdown", (e) => { const li = e.target.closest("li[data-i]"); if (li) { e.preventDefault(); pick(+li.dataset.i); } });
    document.addEventListener("pointerdown", (e) => { if (e.target !== input && !list.contains(e.target)) list.hidden = true; });
  }

  root.StarSearch = { load, search, describe, attach, distanceLines, lookBack, KM_LY, hms, dms, matchedName };
})(window);
