from rag.openai_provider import (
    _normalize_natural_workflow,
    _resolve_use_references,
    _split_leading_natural_instruction,
)


def test_leading_parenthesis_is_instruction_with_optional_colon():
    assert _split_leading_natural_instruction(
        '(Nutze diese Dokumente und suche im Web): Fasse sie zusammen.'
    ) == (
        'Nutze diese Dokumente und suche im Web',
        'Fasse sie zusammen.',
    )
    assert _split_leading_natural_instruction(
        '(Nutze diese Dokumente) Fasse sie zusammen.'
    ) == ('Nutze diese Dokumente', 'Fasse sie zusammen.')


def test_parentheses_later_in_prompt_are_normal_text():
    assert _split_leading_natural_instruction(
        'Vergleiche die Schreiben (insbesondere Punkt 2).'
    ) is None


def test_slash_prompt_is_not_natural_instruction():
    assert _split_leading_natural_instruction(
        '/use:1 Prüfe den Unterschied (insbesondere Punkt 2).'
    ) is None


def test_natural_use_all_plus_web_compiles_to_closed_workflow():
    workflow = _normalize_natural_workflow(
        'Nutze diese Dokumente und suche anschließend im Web',
        'Fasse zusammen und recherchiere Cornelius Muster.',
        {
            'use_mode': 'all_previous',
            'use_references': [],
            'internal_search': 'none',
            'retrieval_arms': [],
            'web': True,
            'web_timing': 'after',
            'web_query': 'Cornelius Muster Rechtsanwaltsgesellschaft Berlin',
            'retrieval_query': 'Fasse zusammen und recherchiere Cornelius Muster.',
            'list_mode': 'none',
            'force': False,
            'context_reset': False,
        },
    )
    assert workflow.use_references == ['all']
    assert workflow.web_requested is True
    assert workflow.web_timing == 'after'
    assert workflow.web_only is False
    assert workflow.retrieval_arms is None
    # The instruction compiler must never rewrite the actual user task.
    assert workflow.retrieval_query == 'Fasse zusammen und recherchiere Cornelius Muster.'


def test_use_all_resolves_all_previous_internal_sources():
    messages = [
        {'role': 'assistant', 'content': '**Quellen:**\n- [1] A — [öffnen](https://x/?openfile=101)\n- [2] B — [öffnen](https://x/?openfile=202)'},
        {'role': 'user', 'content': '/use:all Test'},
    ]
    resolved, missing, available = _resolve_use_references(['all'], messages)
    assert resolved == ['files:101', 'files:202']
    assert missing == []
    assert available == [1, 2]


def test_instruction_compiler_uses_closed_structured_result(monkeypatch):
    import asyncio
    import json
    import rag.openai_provider as provider

    async def fake_complete(*args, **kwargs):
        assert kwargs["response_format"] is provider.NATURAL_INSTRUCTION_RESPONSE_SCHEMA
        assert "retrieval_query" not in provider.NATURAL_INSTRUCTION_RESPONSE_SCHEMA["properties"]
        return json.dumps({
            "use_mode": "all_previous",
            "use_references": [],
            "internal_search": "none",
            "retrieval_arms": [],
            "web": True,
            "web_timing": "after",
            "web_query": "Cornelius Muster Rechtsanwaltsgesellschaft Berlin",
            "list_mode": "none",
            "force": False,
            "context_reset": False,
        })

    monkeypatch.setattr(provider, "_ollama_complete", fake_complete)
    workflow = asyncio.run(provider._compile_natural_instruction(
        [{"role": "user", "content": "Vorherige Frage"}],
        "Nutze diese Dokumente und suche danach im Web",
        "Fasse die Dokumente zusammen.",
    ))
    assert workflow is not None
    assert workflow.use_references == ["all"]
    assert workflow.web_requested is True
    assert workflow.web_timing == "after"
    assert workflow.retrieval_query == "Fasse die Dokumente zusammen."


def test_instruction_prompt_treats_singular_ordinal_as_selected_document():
    import rag.openai_provider as provider

    prompt = provider.NATURAL_INSTRUCTION_SYSTEM_PROMPT
    assert "das erste Dokument" in prompt
    assert "use_mode=selected" in prompt
    assert "Das ist NICHT all_previous" in prompt
    description = provider.NATURAL_INSTRUCTION_RESPONSE_SCHEMA["properties"]["use_mode"]["description"]
    assert "first/second document" in description


def test_natural_nutze_alle_dokumente_forces_closed_previous_set():
    workflow = _normalize_natural_workflow(
        'Nutze alle Dokumente',
        'Bringe sie in eine Tabelle.',
        {
            'use_mode': 'none',
            'use_references': [],
            'internal_search': 'arms',
            'retrieval_arms': ['files'],
            'web': False,
            'web_timing': 'parallel',
            'web_query': '',
            'retrieval_query': 'Bringe sie in eine Tabelle.',
            'list_mode': 'none',
            'force': False,
            'context_reset': False,
        },
    )
    assert workflow.use_references == ['all']
    assert workflow.retrieval_arms is None
    assert workflow.retrieval_query == 'Bringe sie in eine Tabelle.'
