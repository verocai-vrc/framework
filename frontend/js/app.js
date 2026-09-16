/* Application glue: projects, toolbar, node/edge dialogs, selection → editor card. */
(() => {
  const { t, apply } = window.I18N;
  const { escape } = window.Modals;
  const API = window.API;
  const Schema = window.Schema;
  const Graph = window.Graph;

  const state = { projects: [], project: null };
  const $ = (id) => document.getElementById(id);

  // ---- toasts ---------------------------------------------------------------------
  function toast(message, kind = "info") {
    const host = $("toast-host");
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 6000 : 3500);
  }
  window.toast = toast;
  const showError = (err) => toast(err.detail || err.message || t("error.generic"), "error");

  // ---- health ---------------------------------------------------------------------
  async function refreshHealth() {
    const badge = $("badge-health"), text = $("badge-health-text"), guard = $("badge-passive");
    try {
      const h = await API.health();
      const ok = h.neo4j === "connected";
      badge.dataset.state = ok ? "ok" : "degraded";
      text.textContent = ok ? t("health.ok") : t("health.degraded");
      guard.dataset.state = h.passive_only ? "passive" : "active";
      guard.firstElementChild.textContent = h.passive_only ? t("guard.passive") : t("guard.active");
      document.title = `${h.app} — Attack Surface Mapper`;
    } catch (_) {
      badge.dataset.state = "offline";
      text.textContent = t("health.offline");
    }
  }

  // ---- projects -------------------------------------------------------------------
  function rememberProject(id) { try { localStorage.setItem("osintree.project", id); } catch (_) { /* ignore */ } }
  function rememberedProject() { try { return localStorage.getItem("osintree.project"); } catch (_) { return null; } }

  async function loadProjects() {
    state.projects = await API.get("/api/projects");
    const sel = $("project-select");
    sel.innerHTML = state.projects.map((p) => `<option value="${p.id}">${escape(p.name)}</option>`).join("");
    if (state.projects.length === 0) {
      state.project = null;
      Graph.load({ nodes: [], edges: [] });
      $("graph-empty").firstElementChild.textContent = t("project.none");
      openNewProject(true);
      return;
    }
    const wanted = rememberedProject();
    const pick = state.projects.find((p) => p.id === wanted) || state.projects[0];
    await switchProject(pick.id);
  }

  async function switchProject(id) {
    window.Editor.flush();
    state.project = state.projects.find((p) => p.id === id) || null;
    $("project-select").value = id;
    rememberProject(id);
    clearEditor();
    const graph = await API.get(`/api/projects/${id}/graph`);
    $("graph-empty").firstElementChild.textContent = t("graph.empty");
    Graph.load(graph);
    window.Collectors.render();
    window.Analysis.reset();
    await window.Collectors.refreshCount();
  }

  // ---- tools panel tabs -----------------------------------------------------------
  function showTab(name) {
    $("tools-body").hidden = name !== "collectors";
    $("analysis-body").hidden = name !== "analysis";
    $("tools-tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    try { localStorage.setItem("osintree.tab", name); } catch (_) { /* ignore */ }
    if (name === "analysis") window.Analysis.render();
  }

  function openNewProject(required = false) {
    const box = window.Modals.open(`
      <h3>${t("project.new_title")}</h3>
      <form id="form-project">
        <label>${t("project.name")}</label><input type="text" name="name" required maxlength="120" placeholder="${t("project.name_ph")}">
        <label>${t("project.org_name")}</label><input type="text" name="org_name" maxlength="200" placeholder="${t("project.org_name_ph")}">
        <label>${t("project.seed_domain")}</label><input type="text" name="seed_domain" maxlength="253" placeholder="example.org">
        <p class="modal-note">${t("project.note")}</p>
        <div class="modal-actions">
          <button type="submit" class="btn-primary">${t("common.create")}</button>
          ${required ? "" : `<button type="button" class="btn-secondary" id="m-cancel">${t("common.cancel")}</button>`}
        </div>
      </form>`);
    const cancel = box.querySelector("#m-cancel");
    if (cancel) cancel.onclick = () => window.Modals.close();
    box.querySelector("#form-project").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = { name: f.get("name").trim() };
      if (f.get("org_name").trim()) body.org_name = f.get("org_name").trim();
      if (f.get("seed_domain").trim()) body.seed_domain = f.get("seed_domain").trim();
      try {
        const p = await API.post("/api/projects", body);
        window.Modals.close();
        state.projects.push(p);
        $("project-select").insertAdjacentHTML("beforeend", `<option value="${p.id}">${escape(p.name)}</option>`);
        await switchProject(p.id);
        toast(t("project.created", { name: p.name }), "success");
      } catch (err) { showError(err); }
    };
  }

  // ---- node dialog ----------------------------------------------------------------
  function attrsForm(label, values = {}) {
    const spec = Schema.label(label);
    return spec.fields.map((f) => `
      <label for="f-${f.name}">${escape(f.name)}${f.required ? " *" : ""}</label>
      ${window.Modals.fieldInput(f, values[f.name])}`).join("");
  }

  function openAddNode() {
    if (!state.project) return openNewProject(true);
    const options = Schema.labels().map((l) =>
      `<option value="${l.label}" data-axis="${l.axis}">${escape(Schema.display(l.label))} · ${l.axis}${l.default_layer ? "/" + l.default_layer : ""}</option>`).join("");
    const box = window.Modals.open(`
      <h3>${t("node.add_title")}</h3>
      <form id="form-node">
        <label>${t("node.label")}</label>
        <select name="label" id="node-label">${options}</select>
        <div id="node-fields"></div>
        <label>${t("node.title")}</label><input type="text" name="title" maxlength="300" placeholder="${t("node.title_ph")}">
        <div id="node-layer-row" hidden>
          <label>${t("node.layer")}</label><select name="layer" id="node-layer"></select>
        </div>
        <div class="modal-actions">
          <button type="submit" class="btn-primary">${t("common.add")}</button>
          <button type="button" class="btn-secondary" id="m-cancel">${t("common.cancel")}</button>
        </div>
      </form>`);
    const labelSel = box.querySelector("#node-label");
    const render = () => {
      const label = labelSel.value;
      box.querySelector("#node-fields").innerHTML = attrsForm(label);
      const spec = Schema.label(label);
      const row = box.querySelector("#node-layer-row");
      row.hidden = spec.layers.length < 2;
      box.querySelector("#node-layer").innerHTML = spec.layers.map((l) => `<option value="${l}" ${l === spec.default_layer ? "selected" : ""}>${l}</option>`).join("");
      labelSel.style.borderColor = Schema.axisColor(spec.axis);
    };
    labelSel.onchange = render;
    render();
    box.querySelector("#m-cancel").onclick = () => window.Modals.close();
    box.querySelector("#form-node").onsubmit = async (e) => {
      e.preventDefault();
      const label = labelSel.value;
      const spec = Schema.label(label);
      const body = { label, attrs: window.Modals.readFields(e.target, spec.fields) };
      const title = e.target.querySelector('[name="title"]').value.trim();
      if (title) body.title = title;
      if (spec.layers.length > 1) body.layer = e.target.querySelector("#node-layer").value;
      try {
        const n = await API.post(`/api/projects/${state.project.id}/nodes`, body);
        window.Modals.close();
        Graph.upsertNode(n);
        Graph.select(n.id);
        toast(t("node.created", { title: n.title }), "success");
      } catch (err) { showError(err); }
    };
  }

  // ---- edge dialog ----------------------------------------------------------------
  function nodeOption(n, selected) {
    return `<option value="${n.id}" ${selected ? "selected" : ""}>${escape(n.title)} · ${escape(Schema.display(n.label))}</option>`;
  }

  function openAddEdge(fromId, toId) {
    if (!state.project) return openNewProject(true);
    const all = Graph.allNodes();
    if (all.length < 2) return toast(t("edge.need_two"), "error");
    const box = window.Modals.open(`
      <h3>${t("edge.add_title")}</h3>
      <form id="form-edge">
        <label>${t("edge.from")}</label><select name="from" id="edge-from">${all.map((n) => nodeOption(n, n.id === fromId)).join("")}</select>
        <label>${t("edge.to")}</label><select name="to" id="edge-to">${all.map((n) => nodeOption(n, n.id === toId)).join("")}</select>
        <label>${t("edge.rel")}</label><select name="rel" id="edge-rel"></select>
        <p class="modal-note" id="edge-hint"></p>
        <div class="modal-actions">
          <button type="submit" class="btn-primary" id="edge-submit">${t("common.add")}</button>
          <button type="button" class="btn-secondary" id="m-cancel">${t("common.cancel")}</button>
        </div>
      </form>`);
    const fromSel = box.querySelector("#edge-from"), toSel = box.querySelector("#edge-to");
    const relSel = box.querySelector("#edge-rel"), hint = box.querySelector("#edge-hint"), submit = box.querySelector("#edge-submit");
    const render = () => {
      const a = Graph.node(fromSel.value), b = Graph.node(toSel.value);
      const rels = a && b && a.id !== b.id ? Schema.allowedRels(a.label, b.label) : [];
      relSel.innerHTML = rels.map((r) => `<option value="${r}">${r}${Schema.isExtension(r) ? " " + t("edge.ext_mark") : ""}</option>`).join("");
      relSel.disabled = rels.length === 0;
      submit.disabled = rels.length === 0;
      if (rels.length > 0) { hint.textContent = ""; hint.classList.remove("note-error"); return; }
      const reverse = a && b ? Schema.allowedRels(b.label, a.label) : [];
      hint.classList.add("note-error");
      if (a && b && a.id === b.id) hint.textContent = t("edge.self");
      else if (reverse.length) hint.textContent = t("edge.reverse_hint", { rels: reverse.join(", ") });
      else hint.textContent = t("edge.none_hint", { a: Schema.display(a.label), b: Schema.display(b.label) });
    };
    fromSel.onchange = render; toSel.onchange = render;
    render();
    box.querySelector("#m-cancel").onclick = () => window.Modals.close();
    box.querySelector("#form-edge").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const edge = await API.post(`/api/projects/${state.project.id}/edges`, { source_id: fromSel.value, target_id: toSel.value, rel: relSel.value });
        window.Modals.close();
        Graph.upsertEdge(edge);
        toast(t("edge.created", { rel: edge.rel }), "success");
      } catch (err) { showError(err); }
    };
  }

  // ---- deletion -------------------------------------------------------------------
  async function deleteSelection() {
    const sel = Graph.selection();
    if (sel.nodes.length) {
      const n = Graph.node(sel.nodes[0]);
      if (!(await window.Modals.confirm(t("node.delete_confirm", { title: n.title }), { danger: true, okLabel: t("common.delete") }))) return;
      try { await API.del(`/api/nodes/${n.id}`); Graph.removeNode(n.id); clearEditor(); toast(t("node.deleted"), "success"); } catch (err) { showError(err); }
    } else if (sel.edges.length) {
      const e = Graph.edge(sel.edges[0]);
      if (!(await window.Modals.confirm(t("edge.delete_confirm", { rel: e.rel }), { danger: true, okLabel: t("common.delete") }))) return;
      try { await API.del(`/api/edges/${e.id}`); Graph.removeEdge(e.id); clearEditor(); toast(t("edge.deleted"), "success"); } catch (err) { showError(err); }
    }
  }

  // ---- editor (js/editor.js) ------------------------------------------------------
  const clearEditor = () => { window.Editor.clear(); window.Collectors.setSelected(null); };
  const showNode = (n) => { window.Editor.showNode(n); window.Collectors.setSelected(n); };
  const showEdge = (e) => { window.Editor.showEdge(e); window.Collectors.setSelected(null); };

  // ---- project settings -----------------------------------------------------------
  function openProjectSettings() {
    const p = state.project;
    if (!p) return openNewProject(true);
    const box = window.Modals.open(`
      <h3>${t("project.settings")}</h3>
      <form id="form-settings">
        <label>${t("project.name")}</label><input type="text" name="name" required maxlength="120" value="${escape(p.name)}">
        <label>${t("project.description")}</label><textarea name="description" rows="2" maxlength="2000">${escape(p.description)}</textarea>
        <label>${t("project.org_name_short")}</label><input type="text" name="org_name" maxlength="200" value="${escape(p.org_name || "")}">
        <label>${t("project.seed_domain")}</label><input type="text" name="seed_domain" maxlength="253" value="${escape(p.seed_domain || "")}">
        <div class="kv-list" style="margin-top:10px">
          <div class="kv"><span class="k">nodes</span><span class="v">${p.node_count}</span></div>
          <div class="kv"><span class="k">edges</span><span class="v">${p.edge_count}</span></div>
          <div class="kv"><span class="k">created</span><span class="v">${escape(p.created_at)}</span></div>
          <div class="kv"><span class="k">id</span><span class="v mono small">${escape(p.id)}</span></div>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn-danger" id="m-delete">🗑 ${t("project.delete")}</button>
          <span style="flex:1"></span>
          <button type="submit" class="btn-primary">${t("common.save")}</button>
          <button type="button" class="btn-secondary" id="m-cancel">${t("common.cancel")}</button>
        </div>
      </form>`);
    box.querySelector("#m-cancel").onclick = () => window.Modals.close();
    box.querySelector("#m-delete").onclick = async () => {
      window.Modals.close();
      if (!(await window.Modals.confirm(t("project.delete_confirm", { name: p.name }), { danger: true, okLabel: t("common.delete") }))) return;
      try {
        await API.del(`/api/projects/${p.id}`);
        toast(t("project.deleted"), "success");
        await loadProjects();
      } catch (err) { showError(err); }
    };
    box.querySelector("#form-settings").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = { name: f.get("name").trim(), description: f.get("description") };
      if (f.get("org_name").trim()) body.org_name = f.get("org_name").trim();
      if (f.get("seed_domain").trim()) body.seed_domain = f.get("seed_domain").trim();
      try {
        const updated = await API.patch(`/api/projects/${p.id}`, body);
        window.Modals.close();
        Object.assign(p, updated);
        $("project-select").querySelector(`option[value="${p.id}"]`).textContent = p.name;
        toast(t("project.saved"), "success");
      } catch (err) { showError(err); }
    };
  }

  // ---- import / export ------------------------------------------------------------
  async function exportProject() {
    if (!state.project) return;
    window.Editor.flush();
    try {
      const res = await fetch(`/api/projects/${state.project.id}/export`);
      if (!res.ok) throw new Error(res.statusText);
      const blob = await res.blob();
      const name = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name ? name[1] : "project.osintree.json";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      toast(t("io.exported"), "success");
    } catch (err) { showError(err); }
  }

  async function importFile(file) {
    let payload;
    try { payload = JSON.parse(await file.text()); } catch (_) { return toast(t("io.not_json"), "error"); }
    const name = file.name.replace(/\.osintree\.json$|\.json$/i, "");
    try {
      // Typed exports and legacy files carrying meta.entidade name themselves; else use the file name.
      const named = payload.format || (payload.meta && payload.meta.entidade);
      const report = await API.post(`/api/projects/import${named ? "" : `?name=${encodeURIComponent(name)}`}`, payload);
      await loadProjects();
      await switchProject(report.project.id);
      const warn = report.warnings.length
        ? `<span class="section-label">${t("io.warnings")} (${report.warnings.length})</span><ul class="warn-list">${report.warnings.map((w) => `<li>${escape(w)}</li>`).join("")}</ul>`
        : `<p class="muted">${t("io.no_warnings")}</p>`;
      const box = window.Modals.open(`
        <h3>${t("io.report_title")}</h3>
        <div class="kv-list">
          <div class="kv"><span class="k">${t("io.format")}</span><span class="v">${escape(report.format)}</span></div>
          <div class="kv"><span class="k">${t("project.label")}</span><span class="v">${escape(report.project.name)}</span></div>
          <div class="kv"><span class="k">nodes</span><span class="v">${report.nodes_created}</span></div>
          <div class="kv"><span class="k">edges</span><span class="v">${report.edges_created}</span></div>
        </div>
        ${warn}
        <div class="modal-actions"><button class="btn-primary" id="m-ok">${t("common.ok")}</button></div>`);
      box.querySelector("#m-ok").onclick = () => window.Modals.close();
    } catch (err) { showError(err); }
  }

  // ---- boot -----------------------------------------------------------------------
  async function boot() {
    apply();
    refreshHealth();
    setInterval(refreshHealth, 15000);
    Graph.init($("network"), {
      onSelectNode: showNode,
      onSelectEdge: showEdge,
      onDeselect: clearEditor,
      onConnect: (from, to) => openAddEdge(from, to),
    });
    $("btn-add-node").onclick = openAddNode;
    $("btn-add-edge").onclick = () => { if (!state.project) return openNewProject(true); Graph.enterAddEdgeMode(); };
    $("btn-delete").onclick = deleteSelection;
    $("btn-layout").onclick = () => Graph.relayout();
    $("btn-new-project").onclick = () => openNewProject(false);
    $("btn-project-settings").onclick = openProjectSettings;
    $("btn-export").onclick = exportProject;
    $("btn-review").onclick = () => window.Review.open();
    $("btn-import").onclick = () => $("input-import").click();
    $("input-import").onchange = (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) importFile(f); };
    $("project-select").onchange = (e) => switchProject(e.target.value).catch(showError);
    $("tools-tabs").querySelectorAll("button").forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
    let tab = "collectors";
    try { tab = localStorage.getItem("osintree.tab") || "collectors"; } catch (_) { /* ignore */ }
    showTab(tab);
    document.addEventListener("keydown", (e) => {
      if (window.Modals.isOpen() || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
      if (e.key === "Delete" || e.key === "Backspace") deleteSelection();
      if (e.key === "Escape") { Graph.exitMode(); if (Graph.isHighlighted()) window.Analysis.clearHighlight(); }
    });
    try {
      await Schema.load();
      await window.Collectors.load();
      await loadProjects();
    } catch (err) { showError(err); }
  }

  // Public surface for keyboard shortcuts, other modules and UI automation.
  window.App = { state, openAddNode, openAddEdge, openNewProject, openProjectSettings, deleteSelection, switchProject, loadProjects, exportProject, importFile, showNode, showEdge, clearEditor, showTab, toast };

  document.addEventListener("DOMContentLoaded", boot);
})();
