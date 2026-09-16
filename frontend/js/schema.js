/* Schema knowledge for the UI, loaded once from GET /api/schema (the backend is the single
 * source of truth for labels, fields, relationship types and allowed combinations). */
window.Schema = (() => {
  let info = null;
  const byLabel = new Map();
  const allowed = new Map(); // "src|dst" -> [rel, ...]

  const AXIS_COLORS = {
    ORG: "#a371f7",
    DIGITAL: "#3b82f6",
    HUMANO: "#f59e0b",
    FISICO: "#ef4444",
    ECOSSISTEMA: "#22c55e",
  };
  const SHAPES = {
    Organizacao: "star",
    Dominio: "dot",
    Endereco_IP: "square",
    Servico: "triangle",
    Software: "hexagon",
    Dispositivo_Industrial: "diamond",
    CVE: "triangleDown",
    Funcionario: "dot",
    Credencial_Vazada: "square",
    Instalacao_Fisica: "hexagon",
    Fornecedor: "dot",
  };

  async function load() {
    info = await window.API.get("/api/schema");
    byLabel.clear();
    allowed.clear();
    for (const l of info.labels) byLabel.set(l.label, l);
    for (const [src, rel, dst] of info.allowed_edges) {
      const key = `${src}|${dst}`;
      if (!allowed.has(key)) allowed.set(key, []);
      allowed.get(key).push(rel);
    }
    return info;
  }

  const label = (name) => byLabel.get(name);
  const labels = () => info.labels;
  const display = (name) => {
    const l = byLabel.get(name);
    return l ? (l.display[window.I18N.locale] || l.display.pt) : name;
  };
  const axisColor = (axis) => AXIS_COLORS[axis] || "#6e7681";
  const shape = (name) => SHAPES[name] || "dot";
  const allowedRels = (src, dst) => allowed.get(`${src}|${dst}`) || [];
  const isExtension = (rel) => (info.rel_types.find((r) => r.rel === rel) || {}).extension === true;

  return { load, label, labels, display, axisColor, shape, allowedRels, isExtension, get info() { return info; } };
})();
