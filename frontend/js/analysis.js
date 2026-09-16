/* Analysis panel: run the engine, show the three validation criteria, highlight the
 * seed-to-OT path on the canvas, list ranked high-impact cross-axis edges, central nodes,
 * and download the report. Every number here comes from the backend's AnalysisResult. */
window.Analysis = (() => {
  const { t } = window.I18N;
  const { escape } = window.Modals;
  const API = window.API;
  const Graph = window.Graph;
  const Schema = window.Schema;
  const $ = (id) => document.getElementById(id);

  let result = null;      // last AnalysisResult for the current project
  let highlighted = null; // "path" | "weighted" | null
  let options = { entry: "digital", weighted: true };
  try { options = { ...options, ...JSON.parse(localStorage.getItem("osintree.analysis") || "{}") }; } catch (_) { /* ignore */ }
  let reportPrefs = { format: "md", locale: "pt" };
  try { reportPrefs = { ...reportPrefs, ...JSON.parse(localStorage.getItem("osintree.report") || "{}") }; } catch (_) { /* ignore */ }

  const LEVEL_CLASS = (lvl) => (lvl ? `lvl lvl-${lvl}` : "lvl lvl-none");

  function remember() {
    try {
      localStorage.setItem("osintree.analysis", JSON.stringify(options));
      localStorage.setItem("osintree.report", JSON.stringify(reportPrefs));
    } catch (_) { /* ignore */ }
  }

  // ---- rendering --------------------------------------------------------------------
  function toolbar() {
    return `
      <div class="an-toolbar">
        <button class="btn-primary btn-sm" id="an-run">▶ ${t("analysis.run")}</button>
        <label class="an-opt" title="${t("analysis.entry_tip")}">${t("analysis.entry")}
          <select id="an-entry" class="select-compact">
            <option value="digital" ${options.entry === "digital" ? "selected" : ""}>${t("analysis.entry_digital")}</option>
            <option value="any" ${options.entry === "any" ? "selected" : ""}>${t("analysis.entry_any")}</option>
          </select>
        </label>
        <label class="an-opt" title="${t("analysis.weighted_tip")}">
          <input type="checkbox" id="an-weighted" ${options.weighted ? "checked" : ""}> ${t("analysis.weighted")}
        </label>
      </div>`;
  }

  function criteriaCards(r) {
    return `<div class="an-criteria">${r.criteria.map((c) => `
      <details class="an-crit ${c.passed ? "pass" : "fail"}">
        <summary>
          <span class="an-crit-badge">${c.passed ? t("analysis.pass") : t("analysis.fail")}</span>
          <span class="an-crit-title">${c.number}. ${t(`analysis.c${c.number}`)}</span>
          <span class="an-crit-value mono">${c.value} / ≥${c.threshold}</span>
        </summary>
        <ul class="an-evidence">${c.evidence.length ? c.evidence.map((e) => `<li>${escape(e)}</li>`).join("") : `<li class="muted">${t("analysis.no_evidence")}</li>`}</ul>
      </details>`).join("")}</div>`;
  }

  function pathCard(p, kind) {
    const title = kind === "path" ? t("analysis.path_hops") : t("analysis.path_weighted");
    if (!p) return "";
    if (!p.found) {
      return `<div class="an-path an-path-missing"><strong>${title}</strong><span class="muted small">${t(`analysis.reason.${p.reason}`)}</span></div>`;
    }
    const on = highlighted === kind;
    const chain = p.nodes.map((h, i) => `
      ${i ? '<span class="an-arrow">→</span>' : ""}
      <button class="an-chip" data-node="${h.node_id}" title="${escape(Schema.display(h.label))} · ${h.axis}${h.layer ? "/" + h.layer : ""}">
        <span class="dot" style="background:${Schema.axisColor(h.axis)}"></span>${escape(h.title)}</button>`).join("");
    return `
      <div class="an-path ${on ? "on" : ""}">
        <div class="an-path-head">
          <strong>${title}</strong>
          <span class="mono small">${p.hops} ${t("analysis.hops")}${p.cost != null ? ` · ${t("analysis.cost")} ${Number(p.cost).toLocaleString()}` : ""}</span>
          <button class="btn-sm an-highlight ${on ? "on" : ""}" data-kind="${kind}">${on ? t("analysis.unhighlight") : t("analysis.highlight")}</button>
        </div>
        <div class="an-chain">${chain}</div>
      </div>`;
  }

  function edgeRow(e) {
    return `
      <button class="an-edge" data-edge="${e.id}">
        <span class="an-edge-ends">
          <span class="dot" style="background:${Schema.axisColor(Schema.label(e.source_label).axis)}"></span>${escape(e.source_title)}
          <span class="rel mono">-[${escape(e.rel)}]→</span>
          <span class="dot" style="background:${Schema.axisColor(Schema.label(e.target_label).axis)}"></span>${escape(e.target_title)}
        </span>
        <span class="an-edge-badges">
          ${e.rule ? `<span class="badge badge-mini">${e.rule}</span>` : ""}
          <span class="badge badge-mini ${LEVEL_CLASS(e.impact)}" title="${t("edge.impact_short")}">${e.impact || "—"}${e.impact_manual ? "*" : ""}</span>
          <span class="badge badge-mini ${LEVEL_CLASS(e.probability)}" title="${t("edge.probability_short")}">${e.probability || "—"}${e.probability_manual ? "*" : ""}</span>
          <span class="badge badge-mini ${LEVEL_CLASS(e.risk_level)}" title="${t("edge.risk")}">${e.risk_level || "—"}</span>
        </span>
      </button>`;
  }

  function section(title, body, { open = true, count } = {}) {
    return `<details class="an-section" ${open ? "open" : ""}><summary>${title}${count != null ? ` <span class="mono muted">(${count})</span>` : ""}</summary>${body}</details>`;
  }

  function reportBar() {
    const fmts = ["md", "html", "json"].map((f) => `<option value="${f}" ${reportPrefs.format === f ? "selected" : ""}>${f.toUpperCase()}</option>`).join("");
    const locs = window.I18N.locales.map((l) => `<option value="${l}" ${reportPrefs.locale === l ? "selected" : ""}>${l === "pt" ? "Português" : "English"}</option>`).join("");
    return `
      <div class="an-report">
        <strong>${t("analysis.report")}</strong>
        <select id="an-fmt" class="select-compact">${fmts}</select>
        <select id="an-loc" class="select-compact">${locs}</select>
        <button class="btn-sm" id="an-download">↓ ${t("analysis.download")}</button>
        <button class="btn-sm" id="an-open" title="${t("analysis.open_tip")}">↗ ${t("analysis.open")}</button>
      </div>`;
  }

  function render() {
    const host = $("analysis-body");
    if (!host) return;
    if (!window.App.state.project) { host.innerHTML = `<p class="muted">${t("project.none")}</p>`; return; }
    let body = toolbar();
    if (!result) {
      body += `<p class="muted an-intro">${t("analysis.intro")}</p>`;
    } else {
      const r = result;
      const passed = r.criteria.filter((c) => c.passed).length;
      body += `
        <div class="an-verdict ${r.all_passed ? "pass" : "fail"}">
          ${r.all_passed ? t("analysis.verdict_pass") : t("analysis.verdict_fail", { n: passed })}
          <span class="muted small">· ${escape(r.computed_at)}${r.gds_available ? "" : " · " + t("analysis.no_gds")}</span>
        </div>
        ${criteriaCards(r)}
        ${section(t("analysis.path"), pathCard(r.path, "path") + pathCard(r.weighted_path, "weighted"))}
        ${section(t("analysis.high_impact"), r.high_impact_edges.length ? `<div class="an-edges">${r.high_impact_edges.map(edgeRow).join("")}</div>` : `<p class="muted small">${t("analysis.none")}</p>`, { count: r.high_impact_edges.length })}
        ${r.unclassified_cross_axis.length ? section(t("analysis.unclassified"), `<p class="muted small">${t("analysis.unclassified_note")}</p><div class="an-edges">${r.unclassified_cross_axis.map(edgeRow).join("")}</div>`, { open: false, count: r.unclassified_cross_axis.length }) : ""}
        ${r.centrality.length ? section(t("analysis.centrality"), `
          <table class="an-table"><thead><tr><th>${t("analysis.node")}</th><th>${t("analysis.degree")}</th>${r.centrality_method === "gds" ? `<th>${t("analysis.betweenness")}</th>` : ""}</tr></thead>
          <tbody>${r.centrality.map((c) => `<tr><td><button class="link an-chip" data-node="${c.node_id}"><span class="dot" style="background:${Schema.axisColor(c.axis)}"></span>${escape(c.title)}</button></td><td class="mono">${c.degree}</td>${r.centrality_method === "gds" ? `<td class="mono">${(c.betweenness ?? 0).toFixed(1)}</td>` : ""}</tr>`).join("")}</tbody></table>`, { open: false }) : ""}
        ${reportBar()}`;
    }
    host.innerHTML = body;
    wire(host);
  }

  function wire(host) {
    $("an-run").onclick = run;
    $("an-entry").onchange = (e) => { options.entry = e.target.value; remember(); };
    $("an-weighted").onchange = (e) => { options.weighted = e.target.checked; remember(); };
    host.querySelectorAll(".an-chip[data-node]").forEach((b) => { b.onclick = () => Graph.select(b.dataset.node); });
    host.querySelectorAll(".an-edge").forEach((b) => { b.onclick = () => Graph.selectEdge(b.dataset.edge); });
    host.querySelectorAll(".an-highlight").forEach((b) => { b.onclick = () => toggleHighlight(b.dataset.kind); });
    const fmt = $("an-fmt"), loc = $("an-loc");
    if (fmt) {
      fmt.onchange = () => { reportPrefs.format = fmt.value; remember(); };
      loc.onchange = () => { reportPrefs.locale = loc.value; remember(); };
      $("an-download").onclick = () => download(false);
      $("an-open").onclick = () => download(true);
    }
  }

  // ---- actions ----------------------------------------------------------------------
  async function run() {
    const proj = window.App.state.project;
    if (!proj) return window.App.openNewProject(true);
    window.Editor.flush();
    const btn = $("an-run");
    btn.disabled = true;
    btn.textContent = t("analysis.running");
    try {
      const q = `entry=${encodeURIComponent(options.entry)}&locale=${encodeURIComponent(window.I18N.locale)}`;
      result = await API.post(`/api/projects/${proj.id}/analysis?${q}`, { weighted: options.weighted, centrality: true, top_n: 8 });
      // The engine stamped impact/probability/risk on the edges: refresh them in place
      // (no relayout) so the canvas colours follow the classification.
      const edges = await API.get(`/api/projects/${proj.id}/edges`);
      edges.forEach((e) => Graph.upsertEdge(e));
      const sel = Graph.selection();
      if (sel.edges.length === 1 && !sel.nodes.length) window.Editor.showEdge(Graph.edge(sel.edges[0]));
      highlighted = null;
      Graph.clearHighlight();
      render();
      if (result.path.found) toggleHighlight("path");
      window.App.toast(result.all_passed ? t("analysis.verdict_pass") : t("analysis.verdict_fail", { n: result.criteria.filter((c) => c.passed).length }), result.all_passed ? "success" : "info");
    } catch (err) {
      window.App.toast(err.detail || err.message, "error");
      render();
    }
  }

  function toggleHighlight(kind) {
    const p = kind === "weighted" ? result && result.weighted_path : result && result.path;
    if (highlighted === kind || !p || !p.found) { highlighted = null; Graph.clearHighlight(); }
    else { highlighted = kind; Graph.highlightPath(p.nodes.map((h) => h.node_id), p.edges.map((s) => s.edge_id)); }
    render();
  }

  async function download(inline) {
    const proj = window.App.state.project;
    if (!proj) return;
    window.Editor.flush();
    const q = `format=${reportPrefs.format}&locale=${reportPrefs.locale}&entry=${encodeURIComponent(options.entry)}`;
    if (inline) { window.open(`/api/projects/${proj.id}/report?${q}&inline=true`, "_blank"); return; }
    try {
      const res = await fetch(`/api/projects/${proj.id}/report?${q}`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      const blob = await res.blob();
      const name = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name ? name[1] : `report.${reportPrefs.format}`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      window.App.toast(t("analysis.downloaded"), "success");
    } catch (err) { window.App.toast(err.detail || err.message, "error"); }
  }

  function clearHighlight() { highlighted = null; Graph.clearHighlight(); render(); }

  /* Called when the project changes: results belong to one project. */
  function reset() { result = null; highlighted = null; Graph.clearHighlight(); render(); }

  return { render, run, reset, download, toggleHighlight, clearHighlight, get result() { return result; } };
})();
