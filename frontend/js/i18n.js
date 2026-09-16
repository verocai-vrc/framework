/* Centralised front-end strings. Every user-visible string lives here so a Portuguese
 * locale is a table entry, not a code change. `t(key)` falls back to English, then the key. */
window.I18N = (() => {
  const STRINGS = {
    en: {
      "app.name": "OSINTree",
      "health.checking": "checking…",
      "health.ok": "Neo4j connected",
      "health.degraded": "Neo4j unavailable",
      "health.offline": "API unreachable",
      "guard.passive": "passive-only",
      "guard.active": "ACTIVE MODE",
      "guard.tooltip": "Collectors that would touch the target are refused while PASSIVE_ONLY is on.",
      "graph.empty": "No graph yet. Create a project and add your first node.",
      "tools.title": "Tools & collectors",
      "tools.empty": "Collectors arrive in Sprint 3.",
      "editor.placeholder": "Select a node in the graph to edit its details.",
      "error.generic": "Something went wrong.",
    },
    pt: {
      "app.name": "OSINTree",
      "health.checking": "verificando…",
      "health.ok": "Neo4j conectado",
      "health.degraded": "Neo4j indisponível",
      "health.offline": "API inacessível",
      "guard.passive": "somente passivo",
      "guard.active": "MODO ATIVO",
      "guard.tooltip": "Coletores que tocariam o alvo são recusados enquanto PASSIVE_ONLY estiver ativo.",
      "graph.empty": "Nenhum grafo ainda. Crie um projeto e adicione o primeiro nó.",
      "tools.title": "Ferramentas e coletores",
      "tools.empty": "Coletores chegam no Sprint 3.",
      "editor.placeholder": "Selecione um nó no grafo para editar suas informações.",
      "error.generic": "Algo deu errado.",
    },
  };

  let locale = "en";
  try {
    locale = localStorage.getItem("osintree.locale") || "en";
  } catch (_) { /* storage may be blocked */ }

  function t(key, vars) {
    const table = STRINGS[locale] || STRINGS.en;
    let s = table[key] ?? STRINGS.en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
    return s;
  }

  function apply(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
  }

  function setLocale(next) {
    if (!STRINGS[next]) return;
    locale = next;
    try { localStorage.setItem("osintree.locale", next); } catch (_) { /* ignore */ }
    apply();
  }

  return { t, apply, setLocale, get locale() { return locale; }, locales: Object.keys(STRINGS) };
})();
