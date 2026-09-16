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
      axis: n.axis, // kept on the vis node so clusterByAxis() can group on it
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
    const risk = [e.impact && `impact ${e.impact}${e.impact_manual ? "*" : ""}`, e.probability && `prob ${e.probability}${e.probability_manual ? "*" : ""}`, e.risk_level && `risk ${e.risk_level}`].filter(Boolean).join(" · ");
    const base = {
      id: e.id, from: e.source_id, to: e.target_id, label: e.rel, dashes: ext ? [6, 4] : false,
      title: `${e.rel}${e.cross_axis ? " · cross-axis" : ""}${risk ? "\n" + risk : ""}`,
      color: { color: "#3d444d", highlight: "#58a6ff", hover: "#8b949e", opacity: 0.9 }, width: 1.2,
    };
    if (e.impact) base.color = { color: impactColor(e.impact), highlight: "#ffffff", hover: impactColor(e.impact), opacity: 0.9 };
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
    // Cluster nodes have no raw counterpart: a click opens them instead of selecting.
    network.on("selectNode", (p) => { const n = raw.nodes.get(p.nodes[0]); if (n) handlers.onSelectNode(n); });
    network.on("selectEdge", (p) => { const e = raw.edges.get(p.edges[0]); if (p.nodes.length === 0 && e) handlers.onSelectEdge(e); });
    network.on("deselectNode", () => handlers.onDeselect());
    network.on("deselectEdge", (p) => { if (p.nodes.length === 0) handlers.onDeselect(); });
    network.on("click", (p) => { const id = p.nodes[0]; if (id && clusters.has(id)) { network.openCluster(id); clusters.delete(id); updateClusterState(); } });
    network.on("stabilized", fitView);
    container.addEventListener("dblclick", fitView);
    renderLegend();
    return network;
  }

  function load(graph) {
    highlight = null;
    if (network) unclusterAll();
    raw.nodes = new Map(graph.nodes.map((n) => [n.id, n]));
    raw.edges = new Map(graph.edges.map((e) => [e.id, e]));
    nodes.clear();
    edges.clear();
    nodes.add(graph.nodes.map(visNode));
    edges.add(graph.edges.map(visEdge));
    updateEmpty();
    if (network) network.stabilize();
  }
  function upsertNode(n) { raw.nodes.set(n.id, n); nodes.update(highlight && !highlight.nodes.has(n.id) ? { ...visNode(n), opacity: 0.18 } : visNode(n)); updateEmpty(); }
  function upsertEdge(e) { raw.edges.set(e.id, e); if (highlight && highlight.edges.has(e.id)) return; edges.update(highlight ? { ...visEdge(e), color: { ...visEdge(e).color, opacity: 0.08 } } : visEdge(e)); }
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
  function relayout() { unclusterAll(); network.stabilize(); }
  /* Fit the whole graph, or just the path while an overlay is active. */
  function fitView() {
    if (highlight) network.fit({ nodes: [...highlight.nodes], minZoomLevel: 0.3, maxZoomLevel: 1.1, animation: { duration: 400 } });
    else network.fit({ animation: { duration: 300 } });
  }

  /* Axis clustering: collapse every axis with two or more nodes into one cluster node so a
   * large graph reads as the four thesis axes (plus the ORG anchor). Clicking a cluster
   * opens it; any path overlay or relayout expands everything first. */
  const clusters = new Set(); // ids of the cluster nodes currently on the canvas
  const clusterId = (axis) => `cluster:${axis}`;
  function clusterByAxis() {
    unclusterAll();
    const counts = new Map();
    for (const n of raw.nodes.values()) counts.set(n.axis, (counts.get(n.axis) || 0) + 1);
    for (const [axis, count] of counts) {
      if (count < 2) continue;
      const color = window.Schema.axisColor(axis);
      network.cluster({
        joinCondition: (opts) => opts.axis === axis,
        clusterNodeProperties: {
          id: clusterId(axis), axis, label: `${axis} (${count})`, shape: "dot",
          size: 22 + Math.min(count, 24), borderWidth: 3, borderWidthSelected: 4,
          color: { background: shade(color, -20), border: color, highlight: { background: color, border: "#ffffff" }, hover: { background: color, border: "#ffffff" } },
          font: { color: "#ffffff", size: 13, face: "IBM Plex Sans, system-ui, sans-serif" },
          title: window.I18N.t("graph.cluster_open"),
        },
        clusterEdgeProperties: { width: 2, color: { color: "#58a6ff", opacity: 0.6 }, label: "", smooth: { enabled: true, type: "dynamic" } },
      });
      clusters.add(clusterId(axis));
    }
    updateClusterState();
    network.fit({ animation: { duration: 300 } });
  }
  function unclusterAll() {
    if (!network) return;
    for (const id of clusters) if (network.isCluster(id)) network.openCluster(id);
    clusters.clear();
    updateClusterState();
  }
  const isClustered = () => clusters.size > 0;
  function updateClusterState() {
    const btn = document.getElementById("btn-cluster");
    if (btn) btn.classList.toggle("on", isClustered());
  }
  function toggleCluster() { if (isClustered()) { unclusterAll(); fitView(); } else clusterByAxis(); }

  /* Legend: axes come from the schema colours, the rest mirrors the styling rules above. */
  function renderLegend() {
    const host = document.getElementById("legend-body");
    if (!host) return;
    const t = window.I18N.t;
    const axes = ["ORG", "DIGITAL", "HUMANO", "FISICO", "ECOSSISTEMA"];
    const sw = (style) => `<span class="lg-swatch" style="${style}"></span>`;
    host.innerHTML = `
      <div class="lg-group">${axes.map((a) => `<div class="lg-row">${sw(`background:${window.Schema.axisColor(a)}`)}<span>${t("legend.axis." + a)}</span></div>`).join("")}</div>
      <div class="lg-group">
        <div class="lg-row">${sw("background:#3b82f6;border:2px solid #ffffff;box-sizing:border-box")}<span>${t("legend.ot")}</span></div>
        <div class="lg-row">${sw("background:#a371f7;transform:rotate(45deg);border-radius:0;width:9px;height:9px;margin:0 2px")}<span>${t("legend.anchor")}</span></div>
      </div>
      <div class="lg-group">
        <div class="lg-row"><span class="lg-line" style="border-top:2px dashed #8b949e"></span><span>${t("legend.extension")}</span></div>
        <div class="lg-row"><span class="lg-line" style="border-top:2px solid #f85149"></span><span>${t("legend.impact_critico")}</span></div>
        <div class="lg-row"><span class="lg-line" style="border-top:2px solid #f0883e"></span><span>${t("legend.impact_alto")}</span></div>
        <div class="lg-row"><span class="lg-line" style="border-top:2px solid #d29922"></span><span>${t("legend.impact_medio")}</span></div>
        <div class="lg-row"><span class="lg-line" style="border-top:3px solid #58a6ff;box-shadow:0 0 6px rgba(88,166,255,0.7)"></span><span>${t("legend.path")}</span></div>
      </div>`;
  }
  function select(id) { unclusterAll(); network.selectNodes([id]); network.focus(id, { scale: Math.max(network.getScale(), 0.9), animation: { duration: 250 } }); handlers.onSelectNode(raw.nodes.get(id)); }
  function selectEdge(id) { network.unselectAll(); network.selectEdges([id]); handlers.onSelectEdge(raw.edges.get(id)); }

  /* Path overlay: dim everything, then draw the path nodes/edges on top. Restoring is a
   * plain re-render from the raw state, so no per-element bookkeeping is needed. */
  let highlight = null;
  function highlightPath(nodeIds, edgeIds) {
    const wasClustered = isClustered();
    unclusterAll();
    highlight = { nodes: new Set(nodeIds), edges: new Set(edgeIds) };
    nodes.update([...raw.nodes.values()].map((n) => {
      const v = visNode(n);
      return highlight.nodes.has(n.id)
        ? { ...v, borderWidth: 4, color: { ...v.color, border: "#58a6ff" }, font: { color: "#ffffff" }, opacity: 1 }
        : { ...v, opacity: 0.18 };
    }));
    edges.update([...raw.edges.values()].map((e) => {
      const v = visEdge(e);
      return highlight.edges.has(e.id)
        ? { ...v, width: 4, color: { color: "#58a6ff", highlight: "#ffffff", hover: "#58a6ff", opacity: 1 }, font: { color: "#e6edf3" }, shadow: { enabled: true, color: "rgba(88,166,255,0.6)", size: 10 } }
        : { ...v, color: { ...v.color, opacity: 0.08 }, font: { color: "#30363d" } };
    }));
    fitView();
    // Opening clusters restarts physics; refit once the nodes have settled.
    if (wasClustered) setTimeout(fitView, 900);
  }
  function clearHighlight() {
    if (!highlight) return;
    highlight = null;
    nodes.update([...raw.nodes.values()].map((n) => ({ ...visNode(n), opacity: 1 })));
    edges.update([...raw.edges.values()].map((e) => ({ ...visEdge(e), shadow: { enabled: false }, font: { color: "#8b949e" } })));
  }
  const isHighlighted = () => highlight !== null;
  function unselect() { network.unselectAll(); }
  function selection() { return { nodes: network.getSelectedNodes(), edges: network.getSelectedEdges() }; }
  const node = (id) => raw.nodes.get(id);
  const edge = (id) => raw.edges.get(id);
  const allNodes = () => [...raw.nodes.values()];
  const allEdges = () => [...raw.edges.values()];

  return { init, load, upsertNode, upsertEdge, removeNode, removeEdge, enterAddEdgeMode, exitMode, relayout, select, selectEdge, unselect, selection, node, edge, allNodes, allEdges, highlightPath, clearHighlight, isHighlighted, clusterByAxis, unclusterAll, toggleCluster, isClustered, renderLegend };
})();
