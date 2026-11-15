/* Download, copy and native sharing for WANDERERS (stories, summaries, tables). Nothing is uploaded: sharing hands the
 * file to the device's own share sheet (Web Share API) only after the person taps Share; otherwise it downloads.
 * Browser: window.ShareKit. Node: module.exports (only the pure helpers are meaningful there). */
(function (root) {
  "use strict";
  /** File name safe on every OS: letters, digits, dash; keeps the extension. */
  function safeName(base, ext) {
    const b = String(base || "wanderers").normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-").toLowerCase().slice(0, 60) || "wanderers";
    return `${b}.${ext}`;
  }
  const api = { safeName };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  const doc = root.document;
  api.download = (name, data, type = "text/plain") => {
    const blob = data instanceof Blob ? data : new Blob([data], { type });
    const url = URL.createObjectURL(blob), a = doc.createElement("a");
    a.href = url; a.download = name; a.rel = "noopener";
    doc.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    return "downloaded";
  };
  api.copy = async (text) => {
    try { await root.navigator.clipboard.writeText(text); return true; }
    catch {
      const ta = doc.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      doc.body.appendChild(ta); ta.select(); let ok = false; try { ok = doc.execCommand("copy"); } catch { ok = false; } ta.remove(); return ok;
    }
  };
  api.canShareFile = (file) => { try { return !!(root.navigator.canShare && root.navigator.canShare({ files: [file] })); } catch { return false; } };
  api.canShareText = () => typeof root.navigator.share === "function";
  /** Share a file (or text) with the device share sheet; falls back to downloading the file. */
  api.share = async ({ title, text, url, file }) => {
    try {
      if (file && api.canShareFile(file)) { await root.navigator.share({ title, text, files: [file] }); return "shared"; }
      if (!file && api.canShareText()) { await root.navigator.share({ title, text, url }); return "shared"; }
    } catch (e) { if (e && e.name === "AbortError") return "cancelled"; }
    if (file) return api.download(file.name, file);
    return (await api.copy([text, url].filter(Boolean).join("\n"))) ? "copied" : "failed";
  };
  root.ShareKit = api;
})(typeof window !== "undefined" ? window : globalThis);
