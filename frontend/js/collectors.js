/* Tools panel: launch collectors against the project seed or the selected node, show the
 * passive-guard state, and keep the review-queue badge in sync. Launching never touches
 * the canvas: results land in the review queue. */
window.Collectors = (() => {
  const { t } = window.I18N;
  const { escape } = window.Modals;
  const API = window.API;
  const $ = (id) => document.getElementById(id);
  let list = [];
  let selected = null; // currently selected graph node (or null)

  const AXIS_DOT = { DIGITAL: "var(--axis-digital)", HUMANO: "var(--axis-humano)", FISICO: "var(--axis-fisico)", ECOSSISTEMA: "var(--axis-ecossistema)" };

  // Manual OSINT tool categories (reference list from the original notepad). These are links
  // only; key-gated services are used through manual import, never automated.
  const REFERENCE = [
    { axis: "DIGITAL", title: "tools.ref.digital", items: [
      ["crt.sh", "https://crt.sh", "Certificate Transparency logs"],
      ["Subfinder", "https://github.com/projectdiscovery/subfinder", "passive subdomain enumeration"],
      ["Amass", "https://github.com/owasp-amass/amass", "passive-mode attack-surface mapping"],
      ["theHarvester", "https://github.com/laramies/theHarvester", "passive recon aggregator (also HUMANO)"],
      ["Recon-ng", "https://github.com/lanmaster53/recon-ng", "modular passive recon framework"],
      ["SpiderFoot", "https://github.com/smicallef/spiderfoot", "OSINT automation across many sources"],
      ["Shodan", "https://www.shodan.io", "exposed devices and services (key-gated beyond InternetDB: manual import)"],
      ["Censys", "https://search.censys.io", "attack-surface search (key-gated: manual import)"],
      ["ZoomEye", "https://www.zoomeye.org", "cyberspace search engine (key-gated: manual import)"],
      ["FOFA", "https://fofa.info", "cyberspace search engine (key-gated: manual import)"],
      ["DNSDumpster", "https://dnsdumpster.com", "passive DNS reconnaissance"],
      ["urlscan.io", "https://urlscan.io", "URL/website scan search"],
      ["Wayback Machine", "https://web.archive.org", "historical snapshots (also used by the wayback collector)"],
      ["NVD/CVE", "https://nvd.nist.gov/vuln/search", "vulnerability database"],
      ["CISA KEV", "https://www.cisa.gov/known-exploited-vulnerabilities-catalog", "known exploited vulnerabilities"],
      ["ExploitDB", "https://www.exploit-db.com", "public exploits"],
    ]},
    { axis: "HUMANO", title: "tools.ref.humano", items: [
      ["theHarvester", "https://github.com/laramies/theHarvester", "e-mails and names from open sources"],
      ["HaveIBeenPwned", "https://haveibeenpwned.com", "leaked credentials"],
      ["DeHashed", "https://dehashed.com", "breach/credential search (key-gated: manual import)"],
      ["LinkedIn", "https://www.linkedin.com", "roles and profiles (SOCMINT)"],
      ["Sherlock", "https://github.com/sherlock-project/sherlock", "username search across platforms"],
      ["OSINT Framework", "https://osintframework.com", "curated index of OSINT tools by category"],
    ]},
    { axis: "FISICO", title: "tools.ref.fisico", items: [
      ["Google Earth / Maps", "https://earth.google.com", "satellite and street imagery of facilities"],
      ["OpenStreetMap", "https://www.openstreetmap.org", "facility tagging (also used by the facilities collector)"],
      ["Wikidata", "https://www.wikidata.org", "organization facts, HQ and operated sites (also used by the facilities collector)"],
      ["ANEEL SIGA", "https://sigel.aneel.gov.br", "Brazilian power-generation facility registry"],
      ["ANP dados abertos", "https://www.gov.br/anp/pt-br/acesso-a-informacao/dados-abertos", "Brazilian oil/gas facility datasets"],
      ["Regulator registries", "https://www.gov.br/aneel", "public facility records (e.g. ANEEL)"],
    ]},
    { axis: "ECOSSISTEMA", title: "tools.ref.ecossistema", items: [
      ["RDAP", "https://client.rdap.org", "domain and IP registration"],
      ["RIPEstat", "https://stat.ripe.net", "ASN / BGP data"],
      ["BGP.HE.NET", "https://bgp.he.net", "ASN / prefix / peering lookup"],
      ["Wikidata", "https://www.wikidata.org", "corporate structure, subsidiaries, suppliers"],
      ["Procurement portals", "https://www.gov.br/compras", "public contracts and suppliers"],
    ]},
  ];

  async function load() {
    list = await API.get("/api/collectors");
    render();
  }

  function seedControl(c) {
    const proj = window.App.state.project || {};
    if (c.input_kind === "domain") {
      return `<input type="text" class="seed-input" data-c="${c.name}" value="${escape(proj.seed_domain || "")}" placeholder="${t("collectors.seed_domain_ph")}">`;
    }
    if (c.input_kind === "ip") {
      return `<input type="text" class="seed-input" data-c="${c.name}" placeholder="${t("collectors.seed_ip_ph")}">`;
    }
    if (c.input_kind === "org") {
      return `<input type="text" class="seed-input" data-c="${c.name}" value="${escape(proj.org_name || "")}" placeholder="${t("collectors.seed_org_ph")}">`;
    }
    return `<span class="muted small seed-note" data-c="${c.name}">${t("collectors.needs_software")}</span>`;
  }

  function usable(c) {
    if (!selected) return null;
    if (c.input_kind === "software" && selected.label === "Software") return selected;
    if (c.input_kind === "ip" && (selected.label === "Endereco_IP" || (selected.label === "Fornecedor" && selected.attrs.asn))) return selected;
    if (c.input_kind === "domain" && selected.label === "Dominio") return selected;
    if (c.input_kind === "org" && selected.label === "Organizacao") return selected;
    return null;
  }

  function render() {
    const host = $("tools-body");
    if (!host) return;
    host.innerHTML = `
      <div class="collectors">
        ${list.map((c) => {
          const node = usable(c);
          const blocked = !c.allowed;
          return `
          <div class="collector ${blocked ? "blocked" : ""}" data-name="${c.name}">
            <div class="collector-head">
              <span class="axis-dot" style="background:${AXIS_DOT[c.axis] || "var(--axis-none)"}"></span>
              <strong class="mono">${escape(c.name)}</strong>
              <span class="badge badge-mini">${escape(c.source_family)}</span>
              ${blocked ? `<span class="badge badge-mini badge-blocked" title="${t("collectors.blocked_tip")}">🔒 ${t("collectors.blocked")}</span>` : ""}
            </div>
            <div class="collector-desc muted small">${escape(c.description)}</div>
            <div class="collector-run">
              ${seedControl(c)}
              <button class="btn-sm btn-run" data-c="${c.name}" ${c.input_kind === "software" && !node ? "disabled" : ""}>
                ${node ? t("collectors.run_on", { title: node.title }) : t("collectors.run")}
              </button>
            </div>
          </div>`;
        }).join("")}
      </div>
      <details class="tools-ref">
        <summary>${t("tools.reference")}</summary>
        ${REFERENCE.map((g) => `
          <div class="ref-group">
            <div class="ref-title"><span class="axis-dot" style="background:${AXIS_DOT[g.axis]}"></span>${t(g.title)}</div>
            <ul>${g.items.map(([n, u, d]) => `<li><a href="${u}" target="_blank" rel="noopener">${escape(n)}</a> — ${escape(d)}</li>`).join("")}</ul>
          </div>`).join("")}
        <p class="muted small">${t("tools.reference_note")}</p>
      </details>`;
    host.querySelectorAll(".btn-run").forEach((b) => { b.onclick = () => run(b.dataset.c); });
    host.querySelectorAll(".seed-input").forEach((i) => { i.onkeydown = (e) => { if (e.key === "Enter") run(i.dataset.c); }; });
  }

  async function run(name) {
    const proj = window.App.state.project;
    if (!proj) return window.App.openNewProject(true);
    const c = list.find((x) => x.name === name);
    const node = usable(c);
    const input = document.querySelector(`.seed-input[data-c="${name}"]`);
    const body = {};
    if (node) body.node_id = node.id;
    else if (input && input.value.trim()) body.seed = input.value.trim();
    const btn = document.querySelector(`.btn-run[data-c="${name}"]`);
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = t("collectors.running");
    try {
      const r = await API.post(`/api/projects/${proj.id}/collectors/${name}/run`, body);
      const msg = t("collectors.done", { n: r.staged, seed: r.seed }) + (r.skipped_pending || r.skipped_in_graph ? ` ${t("collectors.skipped", { p: r.skipped_pending, g: r.skipped_in_graph })}` : "");
      window.App.toast(msg, r.staged ? "success" : "info");
      await refreshCount();
      if (r.staged) window.Review.open();
    } catch (err) {
      window.App.toast(err.detail || err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  async function refreshCount() {
    const proj = window.App.state.project;
    const btn = $("btn-review");
    if (!proj || !btn) return;
    try {
      const { pending } = await API.get(`/api/projects/${proj.id}/candidates/count`);
      btn.textContent = t("review.button", { n: pending });
      btn.classList.toggle("has-pending", pending > 0);
    } catch (_) { /* degraded engine: leave the badge as is */ }
  }

  function setSelected(node) { selected = node || null; render(); }

  return { load, render, run, refreshCount, setSelected };
})();
