/* Review queue: the human-in-the-loop gate. Candidates are shown with their source,
 * evidence and payload; the analyst edits, approves (merge into the graph) or rejects. */
window.Review = (() => {
  const { t } = window.I18N;
  const { escape } = window.Modals;
  const API = window.API;
  const Schema = window.Schema;
  let status = "pending";
  let items = [];

  const KIND = { node: "review.kind_node", node_update: "review.kind_update", edge: "review.kind_edge" };

  async function fetchItems() {
    const proj = window.App.state.project;
    items = proj ? await API.get(`/api/projects/${proj.id}/candidates?status=${status}`) : [];
  }

  function nodeTitle(id) { const n = window.Graph.node(id); return n ? n.title : id; }
  function edgeSummary(c) {
    if (!c.edges.length) return "";
    return c.edges.map((e) => e.direction === "out"
      ? `<span class="mono">${escape(e.rel)}</span> → ${escape(nodeTitle(e.other_id))}`
      : `${escape(nodeTitle(e.other_id))} → <span class="mono">${escape(e.rel)}</span>`).join(" · ");
  }
  function attrsSummary(c) {
    const skip = new Set(["name", "address", "cve_id"]);
    return Object.entries(c.attrs).filter(([k, v]) => !skip.has(k) && v !== "" && v !== null).map(([k, v]) => `<span class="kv-inline"><span class="k">${escape(k)}</span>${escape(v)}</span>`).join("");
  }

  function row(c) {
    const label = c.label ? Schema.display(c.label) : "";
    const color = c.label ? Schema.axisColor(Schema.label(c.label).axis) : "var(--fg-3)";
    const target = c.target_id ? `<span class="muted small">${t("review.target")}: ${escape(nodeTitle(c.target_id))}</span>` : "";
    return `
      <div class="cand" data-id="${c.id}" data-status="${c.status}">
        <label class="cand-check"><input type="checkbox" class="cand-cb" data-id="${c.id}" ${status === "pending" ? "" : "disabled"}></label>
        <div class="cand-main">
          <div class="cand-head">
            <span class="badge badge-mini" style="border-color:${color};color:${color}">${escape(label)}</span>
            <span class="badge badge-mini">${t(KIND[c.kind])}</span>
            <strong class="cand-title">${escape(c.title)}</strong>
            <span class="badge badge-mini mono" title="${escape(c.source_family)}">${escape(c.collector)}</span>
            <span class="muted small mono">${escape(c.collected_at)}</span>
          </div>
          <div class="cand-evidence">${escape(c.evidence)}</div>
          <div class="cand-meta small">${attrsSummary(c)} ${target} ${edgeSummary(c) ? `<span class="muted">${edgeSummary(c)}</span>` : ""}</div>
          ${c.warnings && c.warnings.length ? `<div class="cand-warn small">${c.warnings.map(escape).join("<br>")}</div>` : ""}
          <div class="cand-edit" hidden></div>
        </div>
        <div class="cand-actions">
          ${status === "pending" ? `
            <button class="btn-sm" data-act="edit">${t("common.edit")}</button>
            <button class="btn-sm btn-approve" data-act="approve">✓ ${t("review.approve")}</button>
            <button class="btn-sm btn-danger" data-act="reject">✕ ${t("review.reject")}</button>` : `
            <span class="muted small">${t("review.status_" + c.status)}${c.merged_node_id ? ` · <button class="link" data-act="goto">${t("review.show_node")}</button>` : ""}</span>`}
        </div>
      </div>`;
  }

  function render() {
    const box = document.getElementById("modal");
    const pendingOnly = status === "pending";
    box.innerHTML = `
      <div class="review-head">
        <h3>${t("review.title")}</h3>
        <div class="seg" id="rv-tabs">
          ${["pending", "approved", "rejected"].map((s) => `<button data-s="${s}" class="${s === status ? "on" : ""}">${t("review.tab_" + s)}</button>`).join("")}
        </div>
        <span style="flex:1"></span>
        ${pendingOnly ? `
          <label class="small"><input type="checkbox" id="rv-all"> ${t("review.select_all")}</label>
          <button class="btn-sm btn-approve" id="rv-approve-sel">✓ ${t("review.approve_selected")}</button>
          <button class="btn-sm btn-danger" id="rv-reject-sel">✕ ${t("review.reject_selected")}</button>` : `
          <button class="btn-sm" id="rv-purge">${t("review.purge", { status: t("review.tab_" + status) })}</button>`}
        <button class="btn-sm btn-secondary" id="rv-close">${t("common.close")}</button>
      </div>
      <div class="cand-list">
        ${items.length ? items.map(row).join("") : `<p class="muted review-empty">${t("review.empty_" + status)}</p>`}
      </div>`;
    box.querySelectorAll("#rv-tabs button").forEach((b) => { b.onclick = async () => { status = b.dataset.s; await fetchItems(); render(); }; });
    box.querySelector("#rv-close").onclick = () => window.Modals.close();
    const all = box.querySelector("#rv-all");
    if (all) all.onchange = () => box.querySelectorAll(".cand-cb").forEach((cb) => { cb.checked = all.checked; });
    const apr = box.querySelector("#rv-approve-sel");
    if (apr) apr.onclick = () => decide(selectedIds(), "approve");
    const rej = box.querySelector("#rv-reject-sel");
    if (rej) rej.onclick = () => decide(selectedIds(), "reject");
    const purge = box.querySelector("#rv-purge");
    if (purge) purge.onclick = async () => {
      const proj = window.App.state.project;
      try { const r = await API.del(`/api/projects/${proj.id}/candidates?status=${status}`); window.App.toast(t("review.purged", { n: r.deleted }), "success"); await fetchItems(); render(); } catch (err) { window.App.toast(err.detail || err.message, "error"); }
    };
    box.querySelectorAll(".cand [data-act]").forEach((b) => {
      const id = b.closest(".cand").dataset.id;
      b.onclick = () => {
        if (b.dataset.act === "edit") toggleEdit(id);
        else if (b.dataset.act === "goto") { const c = items.find((x) => x.id === id); window.Modals.close(); window.Graph.select(c.merged_node_id); }
        else decide([id], b.dataset.act);
      };
    });
  }

  function selectedIds() { return [...document.querySelectorAll(".cand-cb:checked")].map((cb) => cb.dataset.id); }

  async function decide(ids, action) {
    if (!ids.length) return window.App.toast(t("review.none_selected"), "error");
    const proj = window.App.state.project;
    try {
      const res = await API.post(`/api/projects/${proj.id}/candidates/${action}`, { ids });
      const warned = res.filter((c) => c.warnings && c.warnings.length);
      window.App.toast(t(action === "approve" ? "review.approved_n" : "review.rejected_n", { n: res.length }), "success");
      if (warned.length) window.App.toast(warned.map((c) => c.warnings.join("; ")).join(" · "), "error");
      if (action === "approve") {
        const graph = await API.get(`/api/projects/${proj.id}/graph`);
        window.Graph.load(graph);
      }
      await window.Collectors.refreshCount();
      await fetchItems();
      render();
    } catch (err) { window.App.toast(err.detail || err.message, "error"); }
  }

  function toggleEdit(id) {
    const c = items.find((x) => x.id === id);
    const host = document.querySelector(`.cand[data-id="${id}"] .cand-edit`);
    if (!host.hidden) { host.hidden = true; host.innerHTML = ""; return; }
    const spec = c.label && c.kind === "node" ? Schema.label(c.label) : null;
    host.hidden = false;
    host.innerHTML = `
      <form class="cand-form">
        <div class="field-row"><label>${t("node.title")}</label><input type="text" name="title" value="${escape(c.title)}" maxlength="300"></div>
        ${spec ? spec.fields.map((f) => `<div class="field-row"><label>${escape(f.name)}${f.required ? " *" : ""}</label>${window.Modals.fieldInput(f, c.attrs[f.name])}</div>`).join("") : ""}
        <div class="field-row"><label>${t("editor.notes")}</label><textarea name="notes" rows="3">${escape(c.notes)}</textarea></div>
        <div class="modal-actions">
          <button type="submit" class="btn-sm btn-primary">${t("common.save")}</button>
          <button type="button" class="btn-sm btn-secondary" data-cancel>${t("common.cancel")}</button>
        </div>
      </form>`;
    host.querySelector("[data-cancel]").onclick = () => { host.hidden = true; host.innerHTML = ""; };
    host.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      const body = { title: e.target.title.value, notes: e.target.notes.value };
      if (spec) body.attrs = window.Modals.readFields(e.target, spec.fields);
      try {
        const saved = await API.patch(`/api/candidates/${id}`, body);
        Object.assign(c, saved);
        window.App.toast(t("editor.saved"), "success");
        render();
      } catch (err) { window.App.toast(err.detail || err.message, "error"); }
    };
  }

  async function open() {
    if (!window.App.state.project) return window.App.openNewProject(true);
    status = "pending";
    await fetchItems();
    window.Modals.open("");
    document.getElementById("modal").classList.add("modal-wide");
    render();
  }

  return { open };
})();
