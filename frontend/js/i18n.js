/* Centralised front-end strings. Every user-visible string lives here so a Portuguese
 * locale is a table entry, not a code change. `t(key)` falls back to English, then the key. */
window.I18N = (() => {
  const STRINGS = {
    en: {
      "app.name": "OSINTree",
      "health.checking": "checking…",
      "health.ok": "Neo4j connected",
      "health.degraded": "Neo4j unavailable",
      "health.offline": "engine unreachable",
      "guard.passive": "passive-only",
      "guard.active": "ACTIVE MODE",
      "guard.tooltip": "Collectors that would touch the target are refused while PASSIVE_ONLY is on.",
      "common.ok": "OK",
      "common.cancel": "Cancel",
      "common.create": "Create",
      "common.add": "Add",
      "common.delete": "Delete",
      "project.label": "Project",
      "project.new": "＋ New project",
      "project.new_title": "New project",
      "project.name": "Project name *",
      "project.name_ph": "e.g. Utility X — passive surface",
      "project.org_name": "Target organization (creates the anchor node)",
      "project.org_name_ph": "e.g. Utility X",
      "project.seed_domain": "Seed domain",
      "project.note": "The target is supplied here at runtime; nothing about it is built into the tool.",
      "project.none": "No projects yet. Create one to start mapping.",
      "project.created": "Project “{name}” created.",
      "graph.add_node": "＋ Node",
      "graph.add_edge": "→ Edge",
      "graph.delete": "🗑 Delete",
      "graph.layout": "⟳ Layout",
      "graph.empty": "No nodes yet. Use “＋ Node” to add the first one.",
      "graph.connect_hint": "Drag from one node to another to connect them · Esc to cancel",
      "node.add_title": "Add node",
      "node.label": "Type",
      "node.title": "Title (optional, derived from the attributes when empty)",
      "node.title_ph": "display name",
      "node.layer": "Layer",
      "node.created": "Node “{title}” added.",
      "node.deleted": "Node deleted.",
      "node.delete_confirm": "Delete “{title}” and all its relationships?",
      "edge.add_title": "Add relationship",
      "edge.from": "From",
      "edge.to": "To",
      "edge.rel": "Relationship",
      "edge.ext_mark": "(extension)",
      "edge.need_two": "Add at least two nodes before connecting them.",
      "edge.self": "A node cannot be connected to itself.",
      "edge.reverse_hint": "Not allowed in this direction. The opposite direction allows: {rels}.",
      "edge.none_hint": "No relationship type connects {a} to {b}.",
      "edge.created": "Relationship {rel} added.",
      "edge.deleted": "Relationship deleted.",
      "edge.delete_confirm": "Delete this {rel} relationship?",
      "tools.title": "Tools & collectors",
      "tools.empty": "Collectors arrive in Sprint 3.",
      "editor.placeholder": "Select a node or relationship in the graph to see its details.",
      "editor.attributes": "Attributes",
      "editor.description": "Description",
      "editor.provenance": "Provenance",
      "editor.soon": "Editing (title, description, Markdown notes) arrives in Sprint 2.",
      "error.generic": "Something went wrong.",
    },
    pt: {
      "app.name": "OSINTree",
      "health.checking": "verificando…",
      "health.ok": "Neo4j conectado",
      "health.degraded": "Neo4j indisponível",
      "health.offline": "motor inacessível",
      "guard.passive": "somente passivo",
      "guard.active": "MODO ATIVO",
      "guard.tooltip": "Coletores que tocariam o alvo são recusados enquanto PASSIVE_ONLY estiver ativo.",
      "common.ok": "OK",
      "common.cancel": "Cancelar",
      "common.create": "Criar",
      "common.add": "Adicionar",
      "common.delete": "Excluir",
      "project.label": "Projeto",
      "project.new": "＋ Novo projeto",
      "project.new_title": "Novo projeto",
      "project.name": "Nome do projeto *",
      "project.name_ph": "ex.: Distribuidora X — superfície passiva",
      "project.org_name": "Organização-alvo (cria o nó âncora)",
      "project.org_name_ph": "ex.: Distribuidora X",
      "project.seed_domain": "Domínio semente",
      "project.note": "O alvo é informado aqui em tempo de execução; nada sobre ele está embutido na ferramenta.",
      "project.none": "Nenhum projeto ainda. Crie um para começar o mapeamento.",
      "project.created": "Projeto “{name}” criado.",
      "graph.add_node": "＋ Nó",
      "graph.add_edge": "→ Aresta",
      "graph.delete": "🗑 Excluir",
      "graph.layout": "⟳ Layout",
      "graph.empty": "Nenhum nó ainda. Use “＋ Nó” para adicionar o primeiro.",
      "graph.connect_hint": "Arraste de um nó a outro para conectá-los · Esc para cancelar",
      "node.add_title": "Adicionar nó",
      "node.label": "Tipo",
      "node.title": "Título (opcional; derivado dos atributos se vazio)",
      "node.title_ph": "nome de exibição",
      "node.layer": "Camada",
      "node.created": "Nó “{title}” adicionado.",
      "node.deleted": "Nó excluído.",
      "node.delete_confirm": "Excluir “{title}” e todas as suas relações?",
      "edge.add_title": "Adicionar relação",
      "edge.from": "De (origem)",
      "edge.to": "Para (destino)",
      "edge.rel": "Relação",
      "edge.ext_mark": "(extensão)",
      "edge.need_two": "Adicione pelo menos dois nós antes de conectá-los.",
      "edge.self": "Um nó não pode ser conectado a si mesmo.",
      "edge.reverse_hint": "Não permitido nesta direção. A direção oposta permite: {rels}.",
      "edge.none_hint": "Nenhum tipo de relação conecta {a} a {b}.",
      "edge.created": "Relação {rel} adicionada.",
      "edge.deleted": "Relação excluída.",
      "edge.delete_confirm": "Excluir esta relação {rel}?",
      "tools.title": "Ferramentas e coletores",
      "tools.empty": "Coletores chegam no Sprint 3.",
      "editor.placeholder": "Selecione um nó ou relação no grafo para ver seus detalhes.",
      "editor.attributes": "Atributos",
      "editor.description": "Descrição",
      "editor.provenance": "Proveniência",
      "editor.soon": "Edição (título, descrição, notas em Markdown) chega no Sprint 2.",
      "error.generic": "Algo deu errado.",
    },
  };

  let locale = "en";
  try { locale = localStorage.getItem("osintree.locale") || "en"; } catch (_) { /* storage may be blocked */ }

  function t(key, vars) {
    const table = STRINGS[locale] || STRINGS.en;
    let s = table[key] ?? STRINGS.en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
    return s;
  }

  function apply(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  }

  function setLocale(next) {
    if (!STRINGS[next]) return;
    locale = next;
    try { localStorage.setItem("osintree.locale", next); } catch (_) { /* ignore */ }
    apply();
  }

  return { t, apply, setLocale, get locale() { return locale; }, locales: Object.keys(STRINGS) };
})();
