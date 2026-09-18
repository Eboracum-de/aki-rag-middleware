from types import SimpleNamespace

from rag.retrieval_planner import (
    extract_safe_hard_constraints,
    normalize_generated_probes,
    safe_constraint_summary,
)


def test_safe_constraints_are_language_neutral_and_do_not_promote_entities():
    value = extract_safe_hard_constraints(
        "Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025"
    )
    assert value["years"] == ["2025"]
    assert value["filenames"] == []
    assert value["identifiers"] == []
    assert "Nordstern" not in safe_constraint_summary(
        "Suche die Rechnungen der Nordstern GmbH an Example Logistics GmbH 2025"
    )


def test_safe_constraints_work_for_english_query_without_language_rule():
    value = extract_safe_hard_constraints(
        "Find invoices from Nordstern GmbH to Example Logistics GmbH in 2025"
    )
    assert value["years"] == ["2025"]
    assert value["identifiers"] == []


def test_filename_and_identifier_are_safe_constraints():
    value = extract_safe_hard_constraints(
        "Analyse RG-EX-2025-001.pdf and compare it with AZ-47-2025"
    )
    assert value["filenames"] == ["RG-EX-2025-001.pdf"]
    assert "AZ-47-2025" in value["identifiers"]
    assert "2025" in value["years"]


def test_model_generated_valid_strict_probe_is_preserved_as_es_recall_view():
    probes = normalize_generated_probes(
        "Suche Rechnungen 2025",
        [{"kind": "strict_lexical", "query": "+Rechnungen +2025"}],
        max_additional=2,
        retrieval_arms={"files", "vector", "graph"},
    )
    assert probes == [{"kind": "strict_lexical", "query": "+Rechnungen +2025"}]


def test_bounded_document_set_detects_document_type_plus_year_without_claiming_exhaustive():
    from rag.retrieval_planner import detect_bounded_document_set, detect_exhaustive_intent

    query = "Suche Rechnungen von examplehost aus dem Jahr 2025"
    assert detect_bounded_document_set(query) is True
    assert detect_exhaustive_intent(query) is False
    assert detect_bounded_document_set("Wo ging es 2025 um examplehost?") is False
    assert detect_bounded_document_set("Suche alle Rechnungen von examplehost aus 2025") is False


def test_model_generated_weak_strict_probe_is_downgraded():
    probes = normalize_generated_probes(
        "Suche Rechnungen",
        [{"kind": "strict_lexical", "query": "+Rechnung 2025"}],
        max_additional=2,
        retrieval_arms={"files", "vector", "graph"},
    )
    assert probes == [{"kind": "lexical", "query": "Rechnung 2025"}]
