/* Minimal modal system: open(html) returns handles; form helpers build inputs from the
 * schema field descriptions. Native alert/confirm are avoided (not reliable in a WebView). */
window.Modals = (() => {
  const overlay = () => document.getElementById("modal-overlay");
  const box = () => document.getElementById("modal");
  let onClose = null;

  function open(html, { onclose } = {}) {
    box().innerHTML = html;
    overlay().hidden = false;
    onClose = onclose || null;
    const first = box().querySelector("input, select, textarea, button");
    if (first) first.focus();
    return box();
  }
  function close() {
    overlay().hidden = true;
    box().innerHTML = "";
    if (onClose) { const fn = onClose; onClose = null; fn(); }
  }
  function isOpen() { return !overlay().hidden; }

  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen()) close(); });
  document.addEventListener("click", (e) => { if (e.target === overlay()) close(); });

  function confirm(message, { danger = false, okLabel } = {}) {
    const { t } = window.I18N;
    return new Promise((resolve) => {
      open(`
        <h3>${escape(message)}</h3>
        <div class="modal-actions">
          <button class="${danger ? "btn-danger" : "btn-primary"}" id="m-ok">${escape(okLabel || t("common.ok"))}</button>
          <button class="btn-secondary" id="m-cancel">${escape(t("common.cancel"))}</button>
        </div>`, { onclose: () => resolve(false) });
      box().querySelector("#m-ok").onclick = () => { onClose = null; close(); resolve(true); };
      box().querySelector("#m-cancel").onclick = () => close();
    });
  }

  function escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* Render one input for a schema field (name/type/required/choices). */
  function fieldInput(field, value) {
    const id = `f-${field.name}`;
    const v = value ?? field.default ?? "";
    if (field.choices) {
      const opts = field.choices.map((c) => `<option value="${escape(c)}" ${c === v ? "selected" : ""}>${escape(c)}</option>`).join("");
      return `<select id="${id}" name="${field.name}">${opts}</select>`;
    }
    if (field.type === "boolean") {
      const state = v === true ? "true" : v === false ? "false" : "";
      return `<select id="${id}" name="${field.name}">
        <option value="" ${state === "" ? "selected" : ""}>auto</option>
        <option value="true" ${state === "true" ? "selected" : ""}>true</option>
        <option value="false" ${state === "false" ? "selected" : ""}>false</option></select>`;
    }
    const type = field.type === "integer" || field.type === "number" ? "number" : "text";
    const step = field.type === "number" ? ' step="any"' : "";
    return `<input type="${type}"${step} id="${id}" name="${field.name}" value="${escape(v)}" ${field.required ? "required" : ""}>`;
  }

  /* Read the attrs form back into a plain object with the right JS types. */
  function readFields(form, fields) {
    const out = {};
    for (const f of fields) {
      const el = form.querySelector(`[name="${f.name}"]`);
      if (!el) continue;
      let v = el.value;
      if (v === "" || v === null) { if (f.required) out[f.name] = ""; continue; }
      if (f.type === "integer") v = parseInt(v, 10);
      else if (f.type === "number") v = parseFloat(v);
      else if (f.type === "boolean") v = v === "true";
      out[f.name] = v;
    }
    return out;
  }

  return { open, close, isOpen, confirm, escape, fieldInput, readFields };
})();
