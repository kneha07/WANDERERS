/* English / 中文 switch. The pages are written in English; in Chinese mode this file loads the
 * dictionary (i18n-zh.js, built from artifacts/i18n/zh-*.json) and swaps every text node and the
 * placeholder / title / aria-label / alt attributes whose English text is a key, now and as scripts add more.
 * Choice: ?lang=zh|en, then the saved choice, then the browser language. Switching back reloads the page.
 * ponytail: whole-string match only; text built with numbers inside (e.g. "34 epochs") stays English. */
(() => {
  const KEY = "wanderers-lang", ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const get = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const set = (v) => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
  const q = new URLSearchParams(location.search).get("lang");
  if (q === "zh" || q === "en") set(q);
  const lang = q || get() || (/^zh/i.test(navigator.language) ? "zh" : "en");

  document.querySelectorAll(".theme-toggle").forEach((t) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "lang-toggle"; b.lang = lang === "zh" ? "en" : "zh-CN";
    b.textContent = lang === "zh" ? "EN" : "中文";
    b.setAttribute("aria-label", lang === "zh" ? "Switch to English" : "切换到中文");
    b.addEventListener("click", () => { set(lang === "zh" ? "en" : "zh"); const u = new URL(location.href); u.searchParams.delete("lang"); location.replace(u); });
    t.before(b);
  });
  if (lang !== "zh") return;
  document.documentElement.lang = "zh-CN";

  const s = document.createElement("script");
  s.src = "i18n-zh.js?v=20261115a";
  s.onload = () => {
    const D = window.I18N_ZH || {};
    const tr = (v) => { const k = v.trim().replace(/\s+/g, " "); return Object.hasOwn(D, k) ? v.replace(v.trim(), D[k]) : null; };
    const text = (n) => { const p = n.parentElement; if (!p || p.closest("script,style,svg")) return; const t = tr(n.nodeValue); if (t !== null && t !== n.nodeValue) n.nodeValue = t; };
    const attrs = (e) => ATTRS.forEach((a) => { const v = e.getAttribute(a); if (v) { const t = tr(v); if (t !== null && t !== v) e.setAttribute(a, t); } });
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
  document.head.append(s);
})();
