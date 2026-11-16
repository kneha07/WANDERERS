/* Language menu (English / 中文 / हिन्दी / Tiếng Việt / 한국어). The pages are written in English; in another
 * language this file loads that dictionary (i18n-<lang>.js, built by scripts/build_i18n.py from
 * artifacts/i18n/<lang>-*.json) and swaps every text node and the placeholder / title / aria-label / alt
 * attributes whose English text is a key, now and as scripts add more.
 * Choice: ?lang=<code>, then the saved choice, then the browser language. Changing it reloads the page.
 * Lookup: exact text, then the number template ("{0} epochs"). Strings that no probe saw stay English (issue #94). */
(() => {
  // Short labels: a closed <select> is as wide as its longest option, and the phone header has little room.
  const LANGS = { en: ["EN", "en"], zh: ["中文", "zh-CN"], hi: ["हिन्दी", "hi"], vi: ["Việt", "vi"], ko: ["한국어", "ko"] };
  const KEY = "wanderers-lang", ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const get = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const set = (v) => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
  const ok = (l) => (Object.hasOwn(LANGS, l) ? l : null);
  const q = ok(new URLSearchParams(location.search).get("lang"));
  if (q) set(q);
  const lang = q || ok(get()) || ok(String(navigator.language || "").slice(0, 2).toLowerCase()) || "en";

  document.querySelectorAll(".theme-toggle").forEach((t) => {
    const s = document.createElement("select");
    s.className = "lang-toggle"; s.setAttribute("aria-label", "Language");
    for (const [code, [label, tag]] of Object.entries(LANGS)) {
      const o = new Option(label, code, false, code === lang);
      o.lang = tag; s.add(o);
    }
    s.addEventListener("change", () => { set(s.value); const u = new URL(location.href); u.searchParams.delete("lang"); location.replace(u); });
    t.before(s);
  });
  if (lang === "en") return;
  document.documentElement.lang = LANGS[lang][1];

  const sc = document.createElement("script");
  sc.src = `i18n-${lang}.js?v=20261116c`;
  sc.onload = () => {
    const D = window.I18N_DICT || {};
    // Exact text first. Then the number template: scripts paste numbers into English sentences, so
    // "4.2 light-years away" is looked up as "{0} light-years away" and the numbers go back in, in any order.
    const NUM = /\d+(?:[.,]\d+)*/g;
    const look = (k) => {
      if (Object.hasOwn(D, k)) return D[k];
      const nums = k.match(NUM); if (!nums) return null;
      let i = 0; const shape = k.replace(NUM, () => `{${i++}}`);
      return Object.hasOwn(D, shape) ? D[shape].replace(/\{(\d+)\}/g, (_, j) => nums[j]) : null;
    };
    const tr = (v) => { const k = v.trim().replace(/\s+/g, " "); const t = k && look(k); return t ? v.replace(v.trim(), t) : null; };
    const text = (n) => { const p = n.parentElement; if (!p || p.closest("script,style,svg,select.lang-toggle")) return; const t = tr(n.nodeValue); if (t !== null && t !== n.nodeValue) n.nodeValue = t; };
    const attrs = (e) => { if (e.classList?.contains("lang-toggle")) return; ATTRS.forEach((a) => { const v = e.getAttribute(a); if (v) { const t = tr(v); if (t !== null && t !== v) e.setAttribute(a, t); } }); };
    const walk = (root) => {
      if (root.nodeType === 3) return text(root);
      if (root.nodeType !== 1) return;
      attrs(root); root.querySelectorAll("*").forEach(attrs);
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n;
      while ((n = w.nextNode())) text(n);
    };
    const title = tr(document.title); if (title) document.title = title;
    walk(document.body);
    new MutationObserver((ms) => ms.forEach((m) => {
      if (m.type === "characterData") text(m.target);
      else if (m.type === "attributes") attrs(m.target);
      else m.addedNodes.forEach(walk);
    })).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  document.head.append(sc);
})();
