from rag.openai_provider import _previous_web_source_map, _resolve_use_references


def _messages():
    return [
        {"role": "user", "content": "/web Test"},
        {
            "role": "assistant",
            "content": (
                "Antwort\n\n**Öffentliche Quellen:**\n"
                "- [W1] [Quelle Eins](https://one.example)\n"
                "  Archiv: `Webarchiv/2026-08/29-220000-abcd/01-one.txt`\n"
                "- [W2] [Quelle Zwei](https://two.example)\n"
                "  Archiv: `Webarchiv/2026-08/29-220000-abcd/02-two.txt`\n"
            ),
        },
        {"role": "user", "content": "/use:W1 Test"},
    ]


def test_previous_web_source_map():
    assert _previous_web_source_map(_messages()) == {
        1: "Webarchiv/2026-08/29-220000-abcd/01-one.txt",
        2: "Webarchiv/2026-08/29-220000-abcd/02-two.txt",
    }


def test_use_web_reference_resolves_to_archive_snapshot():
    resolved, missing, available = _resolve_use_references(["W1", "w2"], _messages())
    assert resolved == [
        "webarchive:Webarchiv/2026-08/29-220000-abcd/01-one.txt",
        "webarchive:Webarchiv/2026-08/29-220000-abcd/02-two.txt",
    ]
    assert missing == []
    assert available == []
