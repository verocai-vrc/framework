/* Sprint 0 shell: apply strings, poll /health, render the status badges. */
(() => {
  const { t, apply } = window.I18N;

  function toast(message, kind = "info") {
    const host = document.getElementById("toast-host");
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }
  window.toast = toast;

  async function refreshHealth() {
    const badge = document.getElementById("badge-health");
    const text = document.getElementById("badge-health-text");
    const guard = document.getElementById("badge-passive");
    try {
      const h = await window.API.health();
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

  apply();
  refreshHealth();
  setInterval(refreshHealth, 15000);
})();
