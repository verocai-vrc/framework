/* Entity editor (right panel): title, typed attributes, layer, description, Markdown notes
 * with preview, free-form metadata, neighbours, provenance. Autosaves with a debounce and
 * reports save state. Also the edge editor (notes, impact override, weight) and re-typing. */
window.Editor = (() => {
  const { t } = window.I18N;
  const { escape } = window.Modals;
  const API = window.API;
  const Schema = window.Schema;
  const Graph = window.Graph;
  const $ = (id) => document.getElementById(id);

  let current = null; // { kind: "node"|"edge", id }
  let timer = null;
  let pending = {};
  let notesMode = "write";

  // ---- save pipeline ---------------------------------------------------------------
  function setStatus(state, message) {
    const el = $("save-status");
    if (!el) return;
    el.dataset.state = state;
    el.textContent = message || { idle: "", dirty: t("editor.unsaved"), saving: t("editor.saving"), saved: t("editor.saved"), error: t("editor.save_error") }[state];
  }
  function queue(patch) {
    Object.assign(pending, patch);
    setStatus("dirty");
    clearTimeout(timer);
    timer = setTimeout(flush, 700);
  }
  async function flush() {
    clearTimeout(timer);
    if (!current || Object.keys(pending).length === 0) return;
    const body = pending, target = current;
    pending = {};
    setStatus("saving");
    try {
      const path = target.kind === "node" ? `/api/nodes/${target.id}` : `/api/edges/${target.id}`;
      const saved = await API.patch(path, body);
      if (target.kind === "node") { Graph.upsertNode(saved); if (current && current.id === saved.id) syncHeader(saved); }
      else { Graph.upsertEdge(saved); if (current && current.id === saved.id && ("impact" in body || "impact_manual" in body || "probability" in body || "probability_manual" in body)) showEdge(saved); }
      setStatus("saved");
    } catch (err) {
      setStatus("error", `${t("editor.save_error")}: ${err.detail || err.message}`);
    }
  }
  window.addEventListener("beforeunload", () => { if (Object.keys(pending).length) flush(); });

  // ---- node editor -----------------------------------------------------------------
  function attrRows(spec, attrs) {
    return spec.fields.map((f) => `
      <div class="field-row">
        <label for="f-${f.name}">${escape(f.name)}${f.required ? " *" : ""}</label>
        ${window.Modals.fieldInput(f, attrs[f.name])}
      </div>`).join("");
  }
  function metaRows(metadata) {
    return Object.entries(metadata).map(([k, v]) => `
      <div class="meta-row">
        <input type="text" class="meta-k" value="${escape(k)}" placeholder="key">
        <input type="text" class="meta-v" value="${escape(v)}" placeholder="value">
        <button class="btn-sm btn-icon meta-del" title="${t("common.remove")}">✕</button>
      </div>`).join("");
  }
  function neighbourRows(node) {
    const rows = [];
    for (const e of Graph.allEdges()) {
      if (e.source_id === node.id) { const m = Graph.node(e.target_id); if (m) rows.push({ dir: "→", rel: e.rel, m }); }
      else if (e.target_id === node.id) { const m = Graph.node(e.source_id); if (m) rows.push({ dir: "←", rel: e.rel, m }); }
    }
    if (!rows.length) return `<span class="muted small">${t("editor.no_neighbours")}</span>`;
    return rows.map((r) => `
      <button class="neighbour" data-id="${r.m.id}">
        <span class="dir">${r.dir}</span><span class="rel mono">${escape(r.rel)}</span>
        <span class="dot" style="background:${Schema.axisColor(r.m.axis)}"></span><span class="ttl">${escape(r.m.title)}</span>
      </button>`).join("");
  }

  function syncHeader(n) {
    const badge = $("ed-label-badge");
    if (badge) { badge.textContent = Schema.display(n.label); badge.style.borderColor = Schema.axisColor(n.axis); badge.style.color = Schema.axisColor(n.axis); }
    const axis = $("ed-axis-badge");
    if (axis) axis.textContent = `${n.axis}${n.layer ? " / " + n.layer : ""}`;
    const ttl = $("ed-title");
    if (ttl && document.activeElement !== ttl) ttl.value = n.title;
    const nb = $("ed-neighbours");
    if (nb) nb.innerHTML = neighbourRows(n);
  }

  function showNode(n) {
    if (!n) return;
    flush();
    current = { kind: "node", id: n.id };
    pending = {};
    const spec = Schema.label(n.label);
    $("editor-placeholder").hidden = true;
    const c = $("editor-content");
    c.hidden = false;
    c.innerHTML = `
      <div class="node-header">
        <input type="text" id="ed-title" class="title-input" value="${escape(n.title)}" maxlength="300" placeholder="${t("node.title_ph")}">
        <div class="node-badges">
          <button class="badge badge-btn" id="ed-label-badge" title="${t("editor.retype_hint")}"></button>
          <span class="badge" id="ed-axis-badge"></span>
          <span class="save-status" id="save-status" data-state="idle"></span>
        </div>
      </div>

      <span class="section-label">${t("editor.attributes")}</span>
      <div id="ed-attrs">${attrRows(spec, n.attrs)}</div>
      ${spec.layers.length > 1 ? `<div class="field-row"><label>${t("node.layer")}</label>
        <select id="ed-layer">${spec.layers.map((l) => `<option value="${l}" ${l === n.layer ? "selected" : ""}>${l}</option>`).join("")}</select></div>` : ""}

      <span class="section-label">${t("editor.description")}</span>
      <textarea id="ed-description" rows="3" placeholder="${t("editor.description_ph")}">${escape(n.description)}</textarea>

      <div class="section-row">
        <span class="section-label">${t("editor.notes")}</span>
        <div class="seg" id="ed-notes-mode">
          <button data-mode="write" class="${notesMode === "write" ? "on" : ""}">${t("editor.write")}</button>
          <button data-mode="preview" class="${notesMode === "preview" ? "on" : ""}">${t("editor.preview")}</button>
        </div>
      </div>
      <textarea id="ed-notes" rows="8" placeholder="${t("editor.notes_ph")}" ${notesMode === "preview" ? "hidden" : ""}>${escape(n.notes)}</textarea>
      <div id="ed-notes-preview" class="md" ${notesMode === "write" ? "hidden" : ""}></div>

      <span class="section-label">${t("editor.metadata")}</span>
      <div id="ed-meta">${metaRows(n.metadata)}</div>
      <button class="btn-sm" id="ed-meta-add">＋ ${t("editor.metadata_add")}</button>

      <span class="section-label">${t("editor.neighbours")}</span>
      <div id="ed-neighbours" class="neighbours"></div>

      <span class="section-label">${t("editor.provenance")}</span>
      <div class="kv-list">
        <div class="kv"><span class="k">source</span><span class="v">${escape(n.source)}</span></div>
        <div class="kv"><span class="k">collected_at</span><span class="v">${escape(n.collected_at)}</span></div>
        <div class="kv"><span class="k">reviewed</span><span class="v">${n.reviewed ? "✓" : "✗"}</span></div>
        <div class="kv"><span class="k">id</span><span class="v mono small">${escape(n.id)}</span></div>
      </div>

      <div class="editor-actions">
        <button class="btn-danger" id="ed-delete">🗑 ${t("common.delete")}</button>
      </div>`;
    syncHeader(n);
    renderPreview();

    // wiring
    $("ed-title").oninput = (e) => queue({ title: e.target.value });
    $("ed-description").oninput = (e) => queue({ description: e.target.value });
    $("ed-notes").oninput = (e) => { queue({ notes: e.target.value }); renderPreview(); };
    const layer = $("ed-layer");
    if (layer) layer.onchange = (e) => queue({ layer: e.target.value });
    $("ed-attrs").querySelectorAll("[name]").forEach((el) => {
      el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => queue({ attrs: window.Modals.readFields($("ed-attrs"), spec.fields) }));
    });
    $("ed-notes-mode").querySelectorAll("button").forEach((b) => { b.onclick = () => setNotesMode(b.dataset.mode); });
    $("ed-meta-add").onclick = () => { $("ed-meta").insertAdjacentHTML("beforeend", metaRows({ "": "" })); wireMeta(); $("ed-meta").lastElementChild.querySelector(".meta-k").focus(); };
    wireMeta();
    $("ed-neighbours").onclick = (e) => { const b = e.target.closest(".neighbour"); if (b) Graph.select(b.dataset.id); };
    $("ed-label-badge").onclick = () => openRetype(Graph.node(n.id));
    $("ed-delete").onclick = () => window.App.deleteSelection();
    $("btn-delete").disabled = false;
  }

  function wireMeta() {
    const host = $("ed-meta");
    const read = () => {
      const out = {};
      host.querySelectorAll(".meta-row").forEach((r) => { const k = r.querySelector(".meta-k").value.trim(); if (k) out[k] = r.querySelector(".meta-v").value; });
      queue({ metadata: out });
    };
    host.querySelectorAll(".meta-row").forEach((r) => {
      r.querySelector(".meta-k").oninput = read;
      r.querySelector(".meta-v").oninput = read;
      r.querySelector(".meta-del").onclick = () => { r.remove(); read(); };
    });
  }

  function setNotesMode(mode) {
    notesMode = mode;
    $("ed-notes").hidden = mode === "preview";
    $("ed-notes-preview").hidden = mode === "write";
    $("ed-notes-mode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    renderPreview();
  }
  function renderPreview() {
    const el = $("ed-notes-preview");
    if (!el || el.hidden) return;
    const src = $("ed-notes").value;
    el.innerHTML = src.trim() ? window.marked.parse(src) : `<span class="muted small">${t("editor.notes_empty")}</span>`;
  }

  // ---- re-type ---------------------------------------------------------------------
  function openRetype(n) {
    const options = Schema.labels().map((l) => `<option value="${l.label}" ${l.label === n.label ? "selected" : ""}>${escape(Schema.display(l.label))} · ${l.axis}</option>`).join("");
    const box = window.Modals.open(`
      <h3>${t("editor.retype_title")}</h3>
      <p class="modal-note">${t("editor.retype_note")}</p>
      <form id="form-retype">
        <label>${t("node.label")}</label><select id="rt-label">${options}</select>
        <div id="rt-fields"></div>
        <p class="modal-note note-error" id="rt-error"></p>
        <div class="modal-actions">
          <button type="submit" class="btn-primary">${t("common.apply")}</button>
          <button type="button" class="btn-secondary" id="m-cancel">${t("common.cancel")}</button>
        </div>
      </form>`);
    const sel = box.querySelector("#rt-label");
    const render = () => {
      const spec = Schema.label(sel.value);
      // Prefill fields sharing a name with the current attributes, else from the title.
      const seed = { ...n.attrs };
      const first = spec.fields.find((f) => f.required);
      if (first && seed[first.name] === undefined) seed[first.name] = n.title;
      box.querySelector("#rt-fields").innerHTML = attrRows(spec, seed);
    };
    sel.onchange = render;
    render();
    box.querySelector("#m-cancel").onclick = () => window.Modals.close();
    box.querySelector("#form-retype").onsubmit = async (e) => {
      e.preventDefault();
      const spec = Schema.label(sel.value);
      const attrs = window.Modals.readFields(box.querySelector("#rt-fields"), spec.fields);
      try {
        const saved = await API.patch(`/api/nodes/${n.id}`, { label: sel.value, attrs });
        window.Modals.close();
        Graph.upsertNode(saved);
        showNode(saved);
        window.App.toast(t("editor.retyped", { label: Schema.display(saved.label) }), "success");
      } catch (err) {
        const broken = err.detail && Array.isArray(err.broken) ? err.broken : null;
        box.querySelector("#rt-error").textContent = (err.detail || err.message) + (broken ? " — " + broken.join("; ") : "");
      }
    };
  }

  // ---- edge editor -----------------------------------------------------------------
  function showEdge(e) {
    if (!e) return;
    flush();
    current = { kind: "edge", id: e.id };
    pending = {};
    const a = Graph.node(e.source_id), b = Graph.node(e.target_id);
    const impacts = ["", ...Schema.info.impacts];
    const probabilities = ["", ...(Schema.info.probabilities || [])];
    const lvl = (v) => (v ? `lvl lvl-${v}` : "");
    $("editor-placeholder").hidden = true;
    const c = $("editor-content");
    c.hidden = false;
    c.innerHTML = `
      <div class="node-header">
        <h3 class="node-title mono">${escape(e.rel)}${Schema.isExtension(e.rel) ? ` <span class="badge">${t("edge.ext_mark")}</span>` : ""}</h3>
        <div class="node-badges">
          ${e.cross_axis ? `<span class="badge badge-warn">${t("edge.cross_axis")}</span>` : ""}
          <span class="save-status" id="save-status" data-state="idle"></span>
        </div>
      </div>
      <div class="kv-list">
        <div class="kv"><span class="k">${t("edge.from")}</span><span class="v"><button class="link neighbour-link" data-id="${e.source_id}">${escape(a ? a.title : e.source_id)}</button></span></div>
        <div class="kv"><span class="k">${t("edge.to")}</span><span class="v"><button class="link neighbour-link" data-id="${e.target_id}">${escape(b ? b.title : e.target_id)}</button></span></div>
      </div>
      <span class="section-label">${t("edge.risk_section")}</span>
      <div class="risk-grid">
        <div class="field-row"><label>${t("edge.impact")}${e.impact_manual ? ` <span class="badge badge-mini">${t("edge.manual")}</span>` : ""}</label>
          <select id="ed-impact" class="${lvl(e.impact)}">${impacts.map((i) => `<option value="${i}" ${(e.impact_manual ? e.impact : "") === i ? "selected" : ""}>${i || (e.impact ? `${t("edge.auto")} · ${e.impact}` : t("edge.auto"))}</option>`).join("")}</select></div>
        <div class="field-row"><label>${t("edge.probability")}${e.probability_manual ? ` <span class="badge badge-mini">${t("edge.manual")}</span>` : ""}</label>
          <select id="ed-probability" class="${lvl(e.probability)}">${probabilities.map((i) => `<option value="${i}" ${(e.probability_manual ? e.probability : "") === i ? "selected" : ""}>${i || (e.probability ? `${t("edge.auto")} · ${e.probability}` : t("edge.auto"))}</option>`).join("")}</select></div>
        <div class="field-row"><label>${t("edge.risk")}</label>
          <span class="badge ${lvl(e.risk_level)}" id="ed-risk">${e.risk_level || t("edge.risk_pending")}</span></div>
      </div>
      <p class="modal-note">${t("edge.risk_note")}</p>
      <div class="field-row"><label>${t("edge.weight")}</label>
        <input type="number" id="ed-weight" step="any" min="0.01" value="${e.weight ?? ""}" placeholder="1"></div>
      <span class="section-label">${t("editor.notes")}</span>
      <textarea id="ed-edge-notes" rows="5" placeholder="${t("editor.notes_ph")}">${escape(e.notes)}</textarea>
      <span class="section-label">${t("editor.provenance")}</span>
      <div class="kv-list">
        <div class="kv"><span class="k">source</span><span class="v">${escape(e.source)}</span></div>
        <div class="kv"><span class="k">collected_at</span><span class="v">${escape(e.collected_at)}</span></div>
        <div class="kv"><span class="k">reviewed</span><span class="v">${e.reviewed ? "✓" : "✗"}</span></div>
      </div>
      <div class="editor-actions">
        <button class="btn-danger" id="ed-delete">🗑 ${t("common.delete")}</button>
      </div>`;
    // Picking a level is an analyst override; picking "auto" hands the field back to the engine.
    $("ed-impact").onchange = (ev) => queue(ev.target.value ? { impact: ev.target.value } : { impact_manual: false });
    $("ed-probability").onchange = (ev) => queue(ev.target.value ? { probability: ev.target.value } : { probability_manual: false });
    $("ed-weight").oninput = (ev) => { const v = parseFloat(ev.target.value); if (v > 0) queue({ weight: v }); };
    $("ed-edge-notes").oninput = (ev) => queue({ notes: ev.target.value });
    c.querySelectorAll(".neighbour-link").forEach((btn) => { btn.onclick = () => Graph.select(btn.dataset.id); });
    $("ed-delete").onclick = () => window.App.deleteSelection();
    $("btn-delete").disabled = false;
  }

  function clear() {
    flush();
    current = null;
    pending = {};
    $("editor-placeholder").hidden = false;
    $("editor-content").hidden = true;
    $("editor-content").innerHTML = "";
    $("btn-delete").disabled = true;
  }

  return { showNode, showEdge, clear, flush, openRetype };
})();
