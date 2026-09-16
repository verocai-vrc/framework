from __future__ import annotations

import pytest

from app.db.schema import (
    ALLOWED_EDGES,
    EXTENSION_REL_TYPES,
    LABEL_SPECS,
    SCHEMA_NAMES,
    SCHEMA_STATEMENTS,
    THESIS_REL_TYPES,
    VALIDATION_AXES,
    Axis,
    Layer,
    NodeLabel,
    RelType,
    allowed_rel_types,
    is_allowed_edge,
)

# The exact thesis list (brief, Section 5.2). If this test changes, METHODOLOGY_MAPPING.md
# must change with it.
THESIS_EDGES = {
    ("Funcionario", "TRABALHA_EM", "Organizacao"),
    ("Dominio", "RESOLVE_PARA", "Endereco_IP"),
    ("Endereco_IP", "EXPOE", "Servico"),
    ("Servico", "HOSPEDA", "Software"),
    ("Software", "POSSUI_VULNERABILIDADE", "CVE"),
    ("Funcionario", "POSSUI_CREDENCIAL_EXPOSTA", "Credencial_Vazada"),
    ("Credencial_Vazada", "VIABILIZA_ACESSO_A", "Servico"),
    ("Instalacao_Fisica", "ABRIGA", "Dispositivo_Industrial"),
    ("Fornecedor", "MANTEM_ACESSO_A", "Endereco_IP"),
    ("Dispositivo_Industrial", "OPERA_SOBRE", "Software"),
}


def test_thesis_edges_present_exactly():
    got = {(s.value, r.value, t.value) for s, r, t in ALLOWED_EDGES if r in THESIS_REL_TYPES}
    assert got == THESIS_EDGES


def test_every_rel_type_is_thesis_or_extension():
    assert set(RelType) == THESIS_REL_TYPES | EXTENSION_REL_TYPES
    assert not THESIS_REL_TYPES & EXTENSION_REL_TYPES
    expected_extensions = {
        RelType.PERTENCE_A,
        RelType.FORNECE_PARA,
        RelType.OPERA,
        RelType.HOSPEDADO_POR,
        RelType.PIVOT_LATERAL,
        RelType.ACESSA_DIRETAMENTE,
    }
    assert expected_extensions == EXTENSION_REL_TYPES


def test_every_rel_type_has_at_least_one_allowed_combination():
    used = {r for _, r, _ in ALLOWED_EDGES}
    assert used == set(RelType)


@pytest.mark.parametrize(
    ("src", "rel", "dst", "ok"),
    [
        (NodeLabel.DOMINIO, RelType.RESOLVE_PARA, NodeLabel.ENDERECO_IP, True),
        (NodeLabel.ENDERECO_IP, RelType.RESOLVE_PARA, NodeLabel.DOMINIO, False),  # reversed
        (NodeLabel.CVE, RelType.POSSUI_VULNERABILIDADE, NodeLabel.SOFTWARE, False),
        (NodeLabel.FUNCIONARIO, RelType.TRABALHA_EM, NodeLabel.FORNECEDOR, False),
        (NodeLabel.SERVICO, RelType.ACESSA_DIRETAMENTE, NodeLabel.DISPOSITIVO_INDUSTRIAL, True),
    ],
)
def test_is_allowed_edge(src, rel, dst, ok):
    assert is_allowed_edge(src, rel, dst) is ok


def test_allowed_rel_types_between_labels():
    assert allowed_rel_types(NodeLabel.DOMINIO, NodeLabel.ORGANIZACAO) == [RelType.PERTENCE_A]
    assert allowed_rel_types(NodeLabel.CVE, NodeLabel.ORGANIZACAO) == []


def test_label_specs_cover_tabela_7():
    assert set(LABEL_SPECS) == set(NodeLabel)
    assert LABEL_SPECS[NodeLabel.ORGANIZACAO].axis == Axis.ORG
    assert {s.axis for s in LABEL_SPECS.values()} - {Axis.ORG} == VALIDATION_AXES
    assert LABEL_SPECS[NodeLabel.DISPOSITIVO_INDUSTRIAL].layers == (Layer.TO,)
    assert LABEL_SPECS[NodeLabel.SOFTWARE].layers == (Layer.TI, Layer.TO)
    assert LABEL_SPECS[NodeLabel.FUNCIONARIO].layers == ()
    assert LABEL_SPECS[NodeLabel.ENDERECO_IP].display_pt == "Endereço IP"


def test_schema_statements_are_idempotent_and_named():
    assert len(SCHEMA_NAMES) == len(SCHEMA_STATEMENTS)
    for name, stmt in SCHEMA_STATEMENTS:
        assert "IF NOT EXISTS" in stmt
        assert name in stmt


# --- integration ------------------------------------------------------------------------


async def test_constraints_and_indexes_exist_in_database(neo4j):
    status = await neo4j.schema_status()
    assert status["missing"] == []
    assert set(status["present"]) == SCHEMA_NAMES
