# Thesis-to-code mapping

> Living document; completed in Sprint 5. Keep it explicit for the defense.

| Thesis element | Code |
|----------------|------|
| Tabela 7 — node labels, axes, layers | `app/db/schema.py`: `NodeLabel`, `Axis`, `Layer`, `LABEL_SPECS` |
| Relationship list (Section 5.2) | `app/db/schema.py`: `THESIS_REL_TYPES`, `ALLOWED_EDGES` |
| Tabela 8 — cross-axis impact | `app/analysis/risk.py` (Sprint 4) |
| Tabela 2 — risk matrix | `app/analysis/risk.py` (Sprint 4) |
| Criterion 1 — ≥ 3 of 4 axes | `app/analysis/criteria.py` (Sprint 4) |
| Criterion 2 — seed → OT path | `app/analysis/paths.py` (Sprint 4) |
| Criterion 3 — ≥ 1 CRITICO/ALTO cross-axis edge | `app/analysis/risk.py` (Sprint 4) |
| Passive vs active collection (Section 2.1) | `app/config.py` `PASSIVE_ONLY`; `Collector.interacts_with_target`; `app/collectors/registry.py::check_passive_guard` runs before any collector; `active_example.py` demonstrates the refusal |
| Human-in-the-loop review | `app/review/staging.py`: collectors write `:Candidate` only; `approve()` is the sole path into the live graph |
| Provenance (`source`, `collected_at`, `reviewed`) | `app/models/common.py::Provenance`; manual = `manual/true`; collector merges = `<collector>/true`; candidates carry the run timestamp |
| Source families: CT logs, RDAP/WHOIS, ASN, NVD/CVE | `crtsh.py`, `rdap.py`, `bgp.py`, `nvd.py` (`source_family` attribute and module docstrings) |

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
