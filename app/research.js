/* WANDERERS research exports: reproducible summaries, CSV tables and the research table's filter/sort.
 * Everything is read from a target's target.json (pipeline output) and labelled as Measured, Catalogue or
 * Interpretation. Nothing is computed that the pipeline did not already measure, except unit conversions.
 * Browser (window.Research) and Node (module.exports). */
(function (root) {
  "use strict";
  const fx = (v, n) => (typeof v === "number" && isFinite(v) ? v.toFixed(n) : "");
  const signed = (v, n) => (typeof v === "number" && isFinite(v) ? (v >= 0 ? "+" : "") + v.toFixed(n) : "");
  const csvCell = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const toCSV = (header, rows) => [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\n") + "\n";

  /** Per-epoch measured positions as CSV (all channels). */
  function trackCSV(t) {
    const rows = (t.track || []).slice().sort((a, b) => (a.ch || "").localeCompare(b.ch || "") || a.year - b.year)
      .map((p) => [fx(p.year, 4), p.mission, p.ch || "w2", fx(p.ra, 6), fx(p.dec, 6), fx(p.x, 2), fx(p.y, 2), fx(p.pred_x, 2), fx(p.pred_y, 2), fx(p.offset_arcsec, 3)]);
    return toCSV(["epoch_yr", "mission", "channel", "ra_deg", "dec_deg", "x_px", "y_px", "pred_x_px", "pred_y_px", "offset_from_prediction_arcsec"], rows);
  }
  /** Spectrum points as CSV. */
  function spectrumCSV(t) {
    return toCSV(["wavelength_um", "flux_mJy", "n_images"], (t.spectrum || []).map((p) => [fx(p.lam, 4), p.flux_mjy, p.n]));
  }

  /** A reproducible Markdown summary of one target. opts: { url, release, generated (ISO date) } */
  function summary(t, opts = {}) {
    const m = t.motion || {}, r = t.reference || {}, v = t.variability, ev = t.evidence || {}, g = t.grid || {};
    const fr = (t.frames && (t.frames.w2 || t.frames.w1)) || [];
    const icon = { ok: "✓", no: "–", warn: "!" };
    const L = [];
    L.push(`# ${t.name} · WANDERERS observation summary`, "");
    if (t.kind) L.push(`_${t.kind}_`, "");
    L.push("## Field", `- Centre (ICRS): RA ${fx(g.centre_ra, 6)}°, Dec ${signed(g.centre_dec, 6)}°`,
      `- Field: ${g.npix && g.arcsec_per_pix ? `${g.npix * g.arcsec_per_pix}″ × ${g.npix * g.arcsec_per_pix}″, ${g.arcsec_per_pix}″ per display pixel` : "n/a"}`,
      `- Epochs at 4.6 µm: ${fr.length}${fr.length ? ` (${fx(fr[0].year, 3)} to ${fx(fr[fr.length - 1].year, 3)})` : ""}`, "");
    L.push("## Motion", "_Measured_ from the WISE and SPHEREx frames by `pipeline/analyze.py`; _Catalogue_ from the cited source.");
    if (m.measured_arcsec_per_yr != null) {
      L.push(`- Measured: ${fx(m.measured_arcsec_per_yr, 3)}″/yr (μα* ${fx(m.measured_pmra, 1)}, μδ ${fx(m.measured_pmdec, 1)} mas/yr); shift ${fx(m.shift_arcsec, 2)}″ from ${fx(m.from_year, 2)} to ${fx(m.to_year, 2)}`);
      L.push(`- Catalogue (${r.source || "n/a"}, epoch ${r.epoch ?? "n/a"}): ${fx(m.expected_arcsec_per_yr, 3)}″/yr (μα* ${fx(r.pmra, 1)}, μδ ${fx(r.pmdec, 1)} mas/yr)${r.parallax != null ? `; parallax ${fx(r.parallax, 3)} mas` : ""}`);
      const noMove = (ev.checks || []).find((c) => /No measurable motion/i.test(c.text));
      if (noMove) L.push(`- Evidence rule: ${noMove.text}. The measured value above is not a significant detection (see Evidence).`);
    } else L.push("- No motion measurement for this target.");
    const off = (t.track || []).filter((p) => typeof p.offset_arcsec === "number").map((p) => p.offset_arcsec);
    if (off.length) L.push(`- Residual vs predicted position: rms ${fx(Math.sqrt(off.reduce((s, x) => s + x * x, 0) / off.length), 3)}″ over ${off.length} measured positions (max ${fx(Math.max(...off), 3)}″)`);
    L.push("");
    L.push("## Brightness change");
    if (v) L.push(`- Measured: Δm = ${signed(v.delta_mag, 3)} ± ${fx(v.uncertainty_mag, 3)} mag (1σ; positive = fainter), ${v.from} → ${v.to}, ${v.n_wavelength_bins} wavelength bins, ${v.method}`);
    else L.push("- Not measured for this target.");
    L.push("", "## Spectrum", `- SPHEREx measurements: ${t.spectrum_points ?? "n/a"} (${t.flagged_points ?? "n/a"} left out for flagged pixels); aperture photometry, 0.75–5 µm`, "");
    L.push("## Evidence (_Interpretation_, stated rules in `pipeline/evidence.py`)", `- Classification: ${ev.classification || "n/a"} · status ${ev.status || "n/a"} · confidence ${ev.confidence || "n/a"}${ev.confidence_note ? ` (${ev.confidence_note})` : ""}`);
    for (const c of ev.checks || []) L.push(`  - ${icon[c.state] || "·"} ${c.text}`);
    L.push("", "## Data and sources", `- Target file: \`app/data/${t.id}/target.json\``,
      "- SPHEREx DR1 and Quick Releases; AllWISE and NEOWISE (NASA/IPAC IRSA); Gaia DR3 (ESA)" + (/Luhman/.test(r.source || "") ? "; Luhman & Esplin 2016, AJ 152, 78" : ""));
    if (opts.release) L.push(`- SPHEREx release at IRSA when generated: ${opts.release}`);
    if (opts.url) L.push(`- View: ${opts.url}`);
    L.push("", `_Generated ${opts.generated || new Date().toISOString().slice(0, 10)} by WANDERERS from pipeline output. Candidates are never discoveries; confirmation needs follow-up by astronomers._`);
    return L.join("\n") + "\n";
  }

  /** A short, factual plain-text summary for General Explorer sharing. */
  function shortSummary(t, url) {
    const m = t.motion || {}, ev = t.evidence || {};
    const bits = [`${t.name}: ${ev.classification || t.kind || "observed with WANDERERS"}.`];
    const moved = (ev.checks || []).find((c) => /^Moved /.test(c.text));
    if (moved) bits.push(`${moved.text.split(" (")[0]}; measured ${fx(m.measured_arcsec_per_yr, 2)}″/yr vs catalogue ${fx(m.expected_arcsec_per_yr, 2)}″/yr.`);
    const br = (ev.checks || []).find((c) => /^(Faded|Brightened) /.test(c.text));
    if (br) bits.push(br.text.split(" (")[0] + ".");
    bits.push("Data: NASA SPHEREx and WISE, ESA Gaia.");
    if (url) bits.push(url);
    return bits.join(" ");
  }

  /* ---------- research table ---------- */
  function tableRows(list, targets) {
    return list.map((e) => {
      const t = targets[e.id];
      if (!t) return null;
      const fr = (t.frames && t.frames.w2) || [], ev = t.evidence || {}, m = t.motion || {}, v = t.variability;
      return { id: e.id, name: t.name, ra: e.ra, dec: e.dec, epochs: fr.length, first: fr[0] ? fr[0].year : null, last: fr.length ? fr[fr.length - 1].year : null,
        measured: m.measured_arcsec_per_yr ?? null, catalogue: m.expected_arcsec_per_yr ?? null,
        dmag: v ? v.delta_mag : null, dmagErr: v ? v.uncertainty_mag : null,
        cls: ev.classification || "", status: ev.status || "", confidence: ev.confidence || "" };
    }).filter(Boolean);
  }
  function filterRows(rows, { q = "", cls = "" } = {}) {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => (!needle || `${r.name} ${r.id} ${r.cls}`.toLowerCase().includes(needle)) && (!cls || r.cls === cls));
  }
  function sortRows(rows, key, dir = 1) {
    return rows.slice().sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
    });
  }
  function rowsCSV(rows) {
    return toCSV(["id", "name", "ra_deg", "dec_deg", "epochs_4p6um", "first_epoch_yr", "last_epoch_yr", "measured_motion_arcsec_per_yr", "catalogue_motion_arcsec_per_yr", "delta_mag", "delta_mag_err_1sigma", "classification", "status", "confidence"],
      rows.map((r) => [r.id, r.name, fx(r.ra, 6), fx(r.dec, 6), r.epochs, fx(r.first, 3), fx(r.last, 3), fx(r.measured, 4), fx(r.catalogue, 4), fx(r.dmag, 3), fx(r.dmagErr, 3), r.cls, r.status, r.confidence]));
  }

  const api = { trackCSV, spectrumCSV, summary, shortSummary, tableRows, filterRows, sortRows, rowsCSV, toCSV };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Research = api;
})(typeof window !== "undefined" ? window : globalThis);
