# Thesis-to-code mapping

> Living document; finalised in Sprint 5. Keep it explicit for the defense.

| Thesis element | Code |
|----------------|------|
| Tabela 7 — node labels, axes, layers | `app/db/schema.py`: `NodeLabel`, `Axis`, `Layer`, `LABEL_SPECS` |
| Relationship list (Section 5.2) | `app/db/schema.py`: `THESIS_REL_TYPES`, `ALLOWED_EDGES` |
| Tabela 8 — cross-axis impact | `app/analysis/risk.py::IMPACT_RULES` (rows `T8.1`–`T8.6`; `classify_impact`). Stamped on edges as `impact`; report column “Rule”. |
| Tabela 2 — risk matrix | `app/analysis/risk.py::RISK_MATRIX` (3×3) and `risk_level()`. Stamped on edges as `risk_level`. |
| Criterion 1 — ≥ 3 of 4 axes | `app/analysis/criteria.py::criterion_axis_coverage` (`ORG` never counts) |
| Criterion 2 — seed → OT path | `app/analysis/paths.py::shortest_path_to_ot` (Cypher `shortestPath`, hops); optional `weighted_path_to_ot` (GDS Dijkstra, attacker effort); `criteria.py::criterion_seed_to_ot` |
| Criterion 3 — ≥ 1 CRITICO/ALTO cross-axis edge | `app/analysis/risk.py::high_impact` (`cross_axis` **and** impact ∈ {CRITICO, ALTO}); `criteria.py::criterion_high_impact` |
| Passive vs active collection (Section 2.1) | `app/config.py` `PASSIVE_ONLY`; `Collector.interacts_with_target`; `app/collectors/registry.py::check_passive_guard` runs before any collector; `active_example.py` demonstrates the refusal |
| Human-in-the-loop review | `app/review/staging.py`: collectors write `:Candidate` only; `approve()` is the sole path into the live graph |
| Provenance (`source`, `collected_at`, `reviewed`) | `app/models/common.py::Provenance`; manual = `manual/true`; collector merges = `<collector>/true`; candidates carry the run timestamp |
| Source families: CT logs, RDAP/WHOIS, ASN, NVD/CVE | `crtsh.py`, `rdap.py`, `bgp.py`, `nvd.py` (`source_family` attribute and module docstrings) |

## Interpretation choices in the analysis engine

These are decisions the thesis text leaves open; each is a one-line change if the
committee prefers otherwise.

| Question | Choice | Where |
|----------|--------|-------|
| What is “cross-axis”? | Endpoints in two distinct *validation* axes, or TI vs TO inside DIGITAL (Tabela 8 lists TI → TO rows). `ORG` is the anchor, not an axis, so anchoring edges never cross. | `app/graph/crud.py::cross_axis` |
| Tabela 8 rows name labels, not relationship types | Rows match on the endpoint labels in either edge direction, so `Dispositivo_Industrial -[OPERA_SOBRE]-> Software` satisfies the “Software with CVE → Dispositivo_Industrial” row. | `risk.py::classify_impact` |
| Row preconditions (“with CVE”, “remote-auth”, “staging/homolog”) | Preconditions, not decorations: unmet ⇒ the edge stays *unclassified* and is listed for the analyst instead of guessing a level. | `risk.py::IMPACT_RULES` predicates |
| Tabela 8 has four impact levels, Tabela 2 three impact columns | A CRITICO impact is read in the ALTO column (the matrix has no higher one); so CRITICO × ALTA = CRITICO, CRITICO × BAIXA = MEDIO. | `risk.py::risk_level` |
| Probability | Heuristic from evidence on the endpoints and one hop around them (CVSS ≥ 7 ⇒ ALTA; known CVE, exposed remote-auth service, non-production domain, supplier access, direct OT access ⇒ MEDIA; leaked credential against remote-auth ⇒ ALTA; else BAIXA). Always overridable per edge (`probability_manual`). | `risk.py::estimate_probability` |
| Where does the seed-to-OT path start? | At the `Organizacao` anchor. Thesis edges point *to* the anchor, so the anchoring hop is traversed in reverse and counted; every other hop follows edge direction. Entry policy `digital` restricts entry points to `Dominio` nodes (the *public* seed); `any` also admits employees, facilities and suppliers. Without an anchor, the seed `Dominio` itself is the start. | `paths.py` |
| Which OT node? | A `Dispositivo_Industrial` is preferred over TO-layer `Software`; ties broken by fewer hops (or lower effort). | `paths.py` queries |
| Attacker effort | Edge property `weight` (default 1). Dijkstra is optional (GDS) and reported next to the hop path; the criterion itself uses the hop path. | `paths.py::weighted_path_to_ot` |
| Analyst overrides | Impact/probability set by hand (or present in an imported file) are flagged manual and never replaced by the engine until cleared. Criterion 3 counts the effective value, override included. | `models/edges.py`, `crud.py::update_edge` |

## Extensions beyond the thesis schema

All are marked `EXTENSION` in `app/db/schema.py`.

| Relationship | Endpoints | Why |
|--------------|-----------|-----|
| `PERTENCE_A` | `Dominio`/`Instalacao_Fisica` → `Organizacao` | Anchoring so the graph is traversable from the seed (brief, Section 5.2). |
| `FORNECE_PARA` | `Fornecedor` → `Organizacao` | Same. |
| `OPERA` | `Funcionario` → `Dispositivo_Industrial` | Tabela 8 row "Funcionario → Dispositivo_Industrial = ALTO" has no thesis relationship; without this edge the rule could never fire. |
| `HOSPEDADO_POR` | `Dominio` → `Fornecedor` | Tabela 8 row "Dominio (staging/homolog) → Fornecedor = MEDIO", same reason. |
| `PIVOT_LATERAL` | `Servico` → `Servico` | Explicit attacker movement, from the reference OSINT.ree scenario. |
| `ACESSA_DIRETAMENTE` | `Servico` → `Dispositivo_Industrial` | Same. With thesis edges only, `Organizacao` is a sink and `OPERA_SOBRE` points away from the device, so no *directed* seed-to-OT path can exist. |

Internal, non-semantic additions: the `:Entity` secondary label, `:Project` and `:Candidate`
nodes (staging store, brief Section 5.5).
