/* vis-network canvas: renders the live project graph, colours by axis, shapes by label,
 * and exposes selection + drag-to-connect hooks. All mutations go through the API first;
 * the canvas only mirrors what the backend confirmed. */
window.Graph = (() => {
  const nodes = new vis.DataSet([]);
  const edges = new vis.DataSet([]);
  let network = null;
  let handlers = { onSelectNode: () => {}, onSelectEdge: () => {}, onDeselect: () => {}, onConnect: () => {} };
  const raw = { nodes: new Map(), edges: new Map() };

  const OPTIONS = {
    autoResize: true,
    interaction: { hover: true, multiselect: false, navigationButtons: false, keyboard: false, tooltipDelay: 200 },
    physics: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: { gravitationalConstant: -60, centralGravity: 0.008, springLength: 140, springConstant: 0.06, damping: 0.5 },
      stabilization: { iterations: 200, fit: true },
    },
    nodes: {
      size: 16,
      borderWidth: 2,
      font: { color: "#c9d1d9", size: 12, face: "IBM Plex Sans, system-ui, sans-serif", strokeWidth: 0 },
      shadow: { enabled: true, color: "rgba(0,0,0,0.5)", size: 8, x: 0, y: 2 },
    },
    edges: {
      arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      color: { color: "#3d444d", highlight: "#58a6ff", hover: "#8b949e", opacity: 0.9 },
      font: { color: "#8b949e", size: 9, face: "JetBrains Mono, monospace", strokeWidth: 0, align: "middle", background: "rgba(22,27,34,0.85)" },
      smooth: { enabled: true, type: "dynamic" },
      width: 1.2,
      selectionWidth: 2,
    },
    manipulation: {
      enabled: false,
      addEdge: (data, callback) => {
        // Drag-to-connect finished: hand the endpoints to the app; never add locally.
        callback(null);
        exitMode();
        if (data.from !== data.to) handlers.onConnect(data.from, data.to);
      },
    },
  };

  function visNode(n) {
    const color = window.Schema.axisColor(n.axis);
    const isOT = n.layer === "TO";
    return {
      id: n.id,
      label: n.title,
      title: `${window.Schema.display(n.label)} · ${n.axis}${n.layer ? "/" + n.layer : ""}`,
      shape: window.Schema.shape(n.label),
      size: n.label === "Organizacao" ? 26 : isOT ? 20 : 16,
      color: { background: color, border: isOT ? "#ffffff" : shade(color, -25), highlight: { background: color, border: "#ffffff" }, hover: { background: shade(color, 12), border: "#ffffff" } },
      borderWidth: isOT ? 3 : 2,
      font: { color: "#c9d1d9" },
    };
  }
  function visEdge(e) {
    const ext = window.Schema.isExtension(e.rel);
    const base = { id: e.id, from: e.source_id, to: e.target_id, label: e.rel, dashes: ext ? [6, 4] : false };
    if (e.impact) base.color = { color: impactColor(e.impact), highlight: "#ffffff", hover: impactColor(e.impact) };
    if (e.cross_axis) base.width = 2;
    return base;
  }
  function impactColor(impact) {
    return { CRITICO: "#f85149", ALTO: "#f0883e", MEDIO: "#d29922", BAIXO: "#8b949e" }[impact] || "#3d444d";
  }
  function shade(hex, pct) {
    const n = parseInt(hex.slice(1), 16);
    const f = (c) => Math.max(0, Math.min(255, Math.round(c + (pct / 100) * 255)));
    const r = f(n >> 16), g = f((n >> 8) & 255), b = f(n & 255);
    return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
  }

  function init(container, h) {
    handlers = { ...handlers, ...h };
    network = new vis.Network(container, { nodes, edges }, OPTIONS);
    network.on("selectNode", (p) => handlers.onSelectNode(raw.nodes.get(p.nodes[0])));
    network.on("selectEdge", (p) => { if (p.nodes.length === 0) handlers.onSelectEdge(raw.edges.get(p.edges[0])); });
    network.on("deselectNode", () => handlers.onDeselect());
    network.on("deselectEdge", (p) => { if (p.nodes.length === 0) handlers.onDeselect(); });
    network.on("stabilized", () => network.fit({ animation: { duration: 300 } }));
    return network;
  }

  function load(graph) {
    raw.nodes = new Map(graph.nodes.map((n) => [n.id, n]));
    raw.edges = new Map(graph.edges.map((e) => [e.id, e]));
    nodes.clear();
    edges.clear();
    nodes.add(graph.nodes.map(visNode));
    edges.add(graph.edges.map(visEdge));
    updateEmpty();
    if (network) network.stabilize();
  }
  function upsertNode(n) { raw.nodes.set(n.id, n); nodes.update(visNode(n)); updateEmpty(); }
  function upsertEdge(e) { raw.edges.set(e.id, e); edges.update(visEdge(e)); }
  function removeNode(id) {
    raw.nodes.delete(id);
    for (const [eid, e] of raw.edges) if (e.source_id === id || e.target_id === id) raw.edges.delete(eid);
    nodes.remove(id);
    updateEmpty();
  }
  function removeEdge(id) { raw.edges.delete(id); edges.remove(id); }
  function updateEmpty() { document.getElementById("graph-empty").hidden = nodes.length > 0; }

  function enterAddEdgeMode() { network.addEdgeMode(); document.getElementById("mode-hint").hidden = false; document.getElementById("mode-hint").textContent = window.I18N.t("graph.connect_hint"); }
  function exitMode() { if (network) network.disableEditMode(); document.getElementById("mode-hint").hidden = true; }
  function relayout() { network.stabilize(); }
  function select(id) { network.selectNodes([id]); handlers.onSelectNode(raw.nodes.get(id)); }
  function unselect() { network.unselectAll(); }
  function selection() { return { nodes: network.getSelectedNodes(), edges: network.getSelectedEdges() }; }
  const node = (id) => raw.nodes.get(id);
  const edge = (id) => raw.edges.get(id);
  const allNodes = () => [...raw.nodes.values()];
  const allEdges = () => [...raw.edges.values()];

  return { init, load, upsertNode, upsertEdge, removeNode, removeEdge, enterAddEdgeMode, exitMode, relayout, select, unselect, selection, node, edge, allNodes, allEdges };
})();
