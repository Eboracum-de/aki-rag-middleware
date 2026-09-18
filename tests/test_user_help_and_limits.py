from dataclasses import replace

import rag.openai_provider as provider
from rag.openai_provider import (
    _COMMAND_HELP,
    _effective_verification_candidate_limit,
    _is_help_alias,
    _verification_limit_notice,
    _verification_notice_candidate_count,
)


def test_help_aliases_are_natural_and_health_is_not_listed():
    for text in ("help", "Help!", "hilfe", "Hilfe bitte", "aide", "ayuda", "aiuto", "pomoc"):
        assert _is_help_alias(text)
    assert not _is_help_alias("help me find invoices")
    assert "/health" not in _COMMAND_HELP
    assert "/use:1,2" in _COMMAND_HELP
    assert "/web" in _COMMAND_HELP


def test_verification_limit_notice_only_when_candidates_are_unchecked():
    assert _verification_limit_notice(6, 6, exhaustive=False) == ""
    exhaustive = _verification_limit_notice(7, 6, exhaustive=True)
    assert "vollständige Treffermenge" in exhaustive
    assert "unvollständig" in exhaustive
    notice = _verification_limit_notice(20, 6, exhaustive=False)
    assert "weitere mögliche Dokumenttreffer" in notice
    assert "grenzen Sie" in notice
    # Regression: the configured bounded window may be 30 while a remote
    # verifier is capped at 10.  The notice must use the actually reviewed
    # count, otherwise 22 ranked candidates incorrectly look complete.
    bounded = _verification_limit_notice(22, 10, exhaustive=False, bounded_document_set=True)
    assert "innerhalb der angegebenen Kriterien" in bounded
    assert "grenzen Sie" not in bounded


def test_remote_verifier_uses_exhaustive_budget_only_for_explicit_completeness(monkeypatch):
    monkeypatch.setattr(provider, "_role_remote", lambda role: role == "verifier")
    monkeypatch.setattr(provider, "REMOTE_VERIFIER_MAX_CANDIDATES", 10)
    monkeypatch.setattr(
        provider,
        "RETRIEVAL_PLANNER",
        replace(
            provider.RETRIEVAL_PLANNER,
            verification_candidate_limit=10,
            bounded_verification_candidate_limit=30,
            exhaustive_verification_candidate_limit=30,
        ),
    )

    assert _effective_verification_candidate_limit(10, exhaustive=False) == 10
    # A normal/bounded request remains protected by the remote safety cap.
    assert _effective_verification_candidate_limit(30, exhaustive=False) == 10
    # Explicit completeness intent may consume the configured exhaustive budget.
    assert _effective_verification_candidate_limit(30, exhaustive=True) == 30


def test_exhaustive_notice_count_uses_elasticsearch_total_beyond_return_window():
    payload = {"statistics": {"elasticsearch_total_hits": 47}}
    assert _verification_notice_candidate_count(30, payload, exhaustive=True) == 47
    assert _verification_notice_candidate_count(30, payload, exhaustive=False) == 30
    notice = _verification_limit_notice(
        _verification_notice_candidate_count(30, payload, exhaustive=True),
        30,
        exhaustive=True,
    )
    assert "unvollständig" in notice


def test_slash_hilfe_is_normalized_to_help_directive():
    parsed = provider._parse_retrieval_directives('/hilfe')
    assert parsed.seen == ['help']
    assert parsed.special_command == 'help'
    assert parsed.query == ''


def test_explicit_use_documentwise_completeness_is_narrow():
    assert provider._explicit_selection_needs_documentwise_completeness(
        'Liste Datum und Betrag tabellarisch auf.'
    ) is True
    assert provider._explicit_selection_needs_documentwise_completeness(
        'Fasse die wesentlichen Erkenntnisse zusammen.'
    ) is False
