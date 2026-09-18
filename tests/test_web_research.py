import pytest

from rag.web_research import _PageParser, _validate_public_url, load_web_config


def test_html_parser_extracts_real_page_text_and_metadata():
    parser = _PageParser()
    parser.feed('''<!doctype html><html><head><title>Example</title>
      <meta property="article:published_time" content="2026-08-01T10:00:00+02:00">
      <meta property="og:site_name" content="Example Publisher"></head>
      <body><script>ignore me</script><h1>Headline</h1><p>Evidence text.</p></body></html>''')
    parser.close()
    assert parser.title() == "Example"
    assert parser.published() == "2026-08-01T10:00:00+02:00"
    assert parser.publisher() == "Example Publisher"
    assert "Headline" in parser.text()
    assert "Evidence text." in parser.text()
    assert "ignore me" not in parser.text()


def test_private_url_is_blocked_without_network_lookup():
    with pytest.raises(RuntimeError):
        _validate_public_url("http://127.0.0.1/admin")


def test_web_yaml_is_separate_config():
    cfg = load_web_config()
    assert "search" in cfg
    assert "archive" in cfg


def test_archive_research_markdown_contains_query_sources_and_output_markers():
    from datetime import datetime, timezone
    from rag.web_research import NextcloudWebArchive, FetchedSource

    cfg = {
        "archive": {"enabled": True, "root": "Webarchiv"},
        "search": {"provider": "searxng", "max_results": 10},
        "relevance": {"min_score": 0.58, "max_sources": 5},
    }
    archive = NextcloudWebArchive(cfg, {"nextcloud": {"base_url": "http://127.0.0.1"}, "acl": {"enabled": False}})
    src = FetchedSource(
        rank=1, title="Quelle", url="https://example.org/a", final_url="https://example.org/a",
        text="Beleg", content_type="text/html", raw=b"<html></html>",
        retrieved_at="2026-08-29T17:00:00+00:00", content_hash="abc123",
        search_provider="searxng", search_rank=1,
    )
    md = archive._research_markdown(
        query="Greenwich AG", run_id="29-190000-abcd",
        created_at=datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc),
        rag_user_id="user", selected=[(src, 0.91, "relevant")],
        source_records=[{"text_path": "Webarchiv/x/01.txt", "raw_path": ""}],
        stats={"search_provider": "searxng", "searched": 10, "fetched": 8},
        relevance_model="qwen3:8b",
    )
    assert "Greenwich AG" in md
    assert "searxng" in md
    assert "qwen3:8b" in md
    assert "[W1] Quelle" in md
    assert NextcloudWebArchive.LLM_START in md
    assert NextcloudWebArchive.LLM_END in md



def test_lexical_passage_finds_named_entity_late_in_long_fetched_text():
    from rag.web_research import _chunk_text, _lexical_passage

    text = ("Navigation Allgemeines Kontakt Datenschutz. " * 180) + (
        "Michaela Merz ist hier als Geschäftsführerin und Ansprechpartnerin genannt. "
        "Weitere konkrete Informationen zu Michaela Merz folgen in diesem Abschnitt."
    )
    chunks = _chunk_text(text, size=900, overlap=100)
    passage = _lexical_passage("Michaela Merz", chunks, 1400)
    assert "Michaela Merz" in passage


@pytest.mark.asyncio
async def test_relevance_gate_uses_best_fetched_passage_not_page_prefix(monkeypatch):
    import rag.web_research as wr

    class FakeBackend:
        def __init__(self):
            self.messages = None

        async def complete(self, messages, **kwargs):
            self.messages = messages
            return {
                "content": '{"sources":[{"id":1,"relevant":true,"score":0.91,"reason":"Treffer"}]'
                           '}'
            }

    gate = wr.RelevanceGate.__new__(wr.RelevanceGate)
    gate.backend = FakeBackend()
    gate.model = "test"
    gate.timeout = 5
    gate.num_ctx = 4096
    gate.num_predict = 200
    gate.max_sources = 5
    gate.min_score = 0.58
    gate.preview_chars = 1200

    source = wr.FetchedSource(
        rank=1,
        title="Lange Seite",
        url="https://example.org/x",
        final_url="https://example.org/x",
        text="UNRELEVANTER SEITENANFANG " * 400 + " Michaela Merz relevante Passage",
        content_type="text/html",
        raw=b"x",
        retrieved_at="2026-09-09T00:00:00+00:00",
    )

    monkeypatch.setattr(
        wr,
        "best_passage",
        lambda query, text, max_chars: "Michaela Merz relevante Passage",
    )
    selected = await gate.evaluate("Michaela Merz", [source])

    assert len(selected) == 1
    prompt = gate.backend.messages[1]["content"]
    assert "Michaela Merz relevante Passage" in prompt
    assert "UNRELEVANTER SEITENANFANG" not in prompt

@pytest.mark.asyncio
async def test_relevance_gate_retries_empty_decision_array_instead_of_treating_as_irrelevant(monkeypatch):
    import rag.web_research as wr

    class FakeBackend:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"content": '{"sources":[]}', "done_reason": "stop"}
            return {
                "content": '{"sources":[{"id":1,"relevant":true,"score":0.93,"reason":"Treffer"}]}',
                "done_reason": "stop",
            }

    gate = wr.RelevanceGate.__new__(wr.RelevanceGate)
    gate.backend = FakeBackend()
    gate.model = "test"
    gate.timeout = 5
    gate.num_ctx = 4096
    gate.num_predict = 200
    gate.max_sources = 5
    gate.min_score = 0.58
    gate.preview_chars = 1200

    source = wr.FetchedSource(
        rank=1,
        title="Michaela Merz",
        url="https://example.org/x",
        final_url="https://example.org/x",
        text="Michaela Merz relevante Passage",
        content_type="text/html",
        raw=b"x",
        retrieved_at="2026-09-09T00:00:00+00:00",
    )
    monkeypatch.setattr(wr, "best_passage", lambda query, text, max_chars: text)

    selected = await gate.evaluate("Michaela Merz", [source])

    assert gate.backend.calls == 2
    assert len(selected) == 1
    assert selected[0][1] == pytest.approx(0.93)


def test_relevance_schema_is_openai_strict_compatible():
    from rag.web_research import _RELEVANCE_SCHEMA

    assert _RELEVANCE_SCHEMA["additionalProperties"] is False
    item = _RELEVANCE_SCHEMA["properties"]["sources"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"id", "relevant", "score", "reason"}
    assert "minimum" not in item["properties"]["id"]
    assert "minimum" not in item["properties"]["score"]
    assert "maximum" not in item["properties"]["score"]


def test_fetch_log_records_selected_rejected_and_fetch_errors():
    import json
    import rag.web_research as wr

    selected = wr.FetchedSource(
        rank=1, title="Selected", url="https://one.example/a", final_url="https://one.example/a",
        text="A" * 200, content_type="text/html", raw=b"<html></html>",
        retrieved_at="2026-09-12T10:00:00+00:00", content_hash="aaa",
        search_provider="brave", search_rank=1, http_status=200,
    )
    rejected = wr.FetchedSource(
        rank=2, title="Rejected", url="https://two.example/b", final_url="https://two.example/b",
        text="B" * 200, content_type="text/html", raw=b"<html></html>",
        retrieved_at="2026-09-12T10:00:01+00:00", content_hash="bbb",
        search_provider="brave", search_rank=2, http_status=200,
    )
    failed = wr.FetchedSource(
        rank=3, title="Failed", url="https://three.example/c", final_url="https://three.example/c",
        text="", content_type="", raw=b"", retrieved_at="2026-09-12T10:00:02+00:00",
        fetch_error="HTTPStatusError: 404", search_provider="brave", search_rank=3, http_status=404,
    )
    decisions = [
        {
            "search_rank": 1, "requested_url": selected.url, "final_url": selected.final_url,
            "relevant": True, "score": 0.93, "accepted": True, "selected": True,
            "reason": "primary source",
        },
        {
            "search_rank": 2, "requested_url": rejected.url, "final_url": rejected.final_url,
            "relevant": False, "score": 0.1, "accepted": False, "selected": False,
            "reason": "not relevant",
        },
    ]

    rows = [json.loads(line) for line in wr.NextcloudWebArchive._fetch_log_bytes(
        [selected, rejected, failed], decisions
    ).decode("utf-8").splitlines()]
    assert [row["outcome"] for row in rows] == ["selected", "rejected", "fetch_error"]
    assert rows[0]["relevance"]["reason"] == "primary source"
    assert rows[2]["http_status"] == 404


@pytest.mark.asyncio
async def test_archive_run_queues_rendered_pdf_and_updates_metadata_in_background(monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace
    import rag.web_research as wr

    cfg = {
        "archive": {
            "enabled": True,
            "root": "Webarchiv",
            "write_text_snapshot": True,
            "write_raw_pdf": True,
            "write_raw_html": False,
            "write_fetch_log": True,
            "write_metadata_json": True,
            "write_rendered_pdf": True,
            "renderer": {"enabled": False, "background": True},
        },
        "search": {"provider": "brave", "max_results": 10},
        "relevance": {"min_score": 0.58, "max_sources": 5},
    }
    archive = wr.NextcloudWebArchive(
        cfg,
        {"nextcloud": {"base_url": "http://127.0.0.1"}, "acl": {"enabled": False}},
    )

    release_render = asyncio.Event()

    class FakeRenderer:
        enabled = True

        async def render(self, source):
            await release_render.wait()
            return wr.RenderedSnapshot(
                pdf=b"%PDF-1.4\nfake\n",
                requested_url=source.final_url,
                final_url=source.final_url,
                title=source.title,
                sha256="pdfhash",
                elapsed_ms=123,
                media="screen",
                video_posters=2,
                cookie_consent="accepted",
                cookie_actions=1,
                overlays_dismissed=1,
                overlays_removed=0,
                dom_modified=False,
            )

    archive.renderer = FakeRenderer()
    monkeypatch.setattr(archive, "_credential", lambda user: SimpleNamespace(username="u", password="p"))

    async def fake_ensure_dir(client, credential, relpath):
        return None

    written = {}

    async def fake_put(client, credential, target, content, content_type):
        written[target] = (content, content_type)

    monkeypatch.setattr(archive, "_ensure_dir", fake_ensure_dir)
    monkeypatch.setattr(archive, "_put", fake_put)

    source = wr.FetchedSource(
        rank=1, title="Example", url="https://example.org/a", final_url="https://example.org/a",
        text="Evidence " * 30, content_type="text/html", raw=b"<html></html>",
        retrieved_at="2026-09-12T10:00:00+00:00", content_hash="abc123456789",
        search_provider="brave", search_rank=1, http_status=200,
    )
    decisions = [{
        "search_rank": 1, "requested_url": source.url, "final_url": source.final_url,
        "relevant": True, "score": 0.9, "accepted": True, "selected": True, "reason": "relevant",
    }]

    result = await archive.archive_run(
        "Example query", [(source, 0.9, "relevant")], fetched=[source],
        relevance_decisions=decisions, rag_user_id=None,
        stats={"search_provider": "brave", "searched": 1, "fetched": 1},
        relevance_model="test-model",
    )

    record = result["source_records"][0]
    assert record["pdf_path"] == ""
    assert result["render_pending"] == 1
    assert record["metadata_path"].split("/")[-1].startswith(".")
    assert record["metadata_path"].endswith(".metadata.json")
    assert result["fetch_log_path"].endswith("fetch-log.jsonl")
    initial_metadata = json.loads(written[record["metadata_path"]][0].decode("utf-8"))
    assert initial_metadata["render"]["status"] == "pending"
    target_pdf = initial_metadata["render"]["target_path"]
    assert target_pdf.endswith(".pdf")
    assert target_pdf not in written

    pending = list(archive._render_tasks)
    release_render.set()
    if pending:
        await asyncio.gather(*pending)

    assert written[target_pdf][0].startswith(b"%PDF-")
    metadata = json.loads(written[record["metadata_path"]][0].decode("utf-8"))
    assert metadata["render"]["status"] == "complete"
    assert metadata["render"]["media"] == "screen"
    assert metadata["render"]["video_posters"] == 2
    assert metadata["render"]["cleanup"] == {
        "cookie_consent": "accepted",
        "cookie_actions": 1,
        "overlays_dismissed": 1,
        "overlays_removed": 0,
        "dom_modified": False,
    }
    assert metadata["archive"]["pdf_path"] == target_pdf


def test_brave_searcher_reports_missing_key_as_unconfigured(monkeypatch):
    import rag.web_research as wr

    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    searcher = wr.WebSearchProvider({
        "search": {"provider": "brave", "api_key_env": "WEB_SEARCH_API_KEY"}
    })
    ready, error = searcher.readiness()
    assert ready is False
    assert "WEB_SEARCH_API_KEY" in error


def test_best_passage_skips_disabled_reranker_without_warning_path(monkeypatch):
    import rag.reranker as rr
    import rag.web_research as wr

    monkeypatch.setattr(rr.reranker, "backend", "none")
    monkeypatch.setattr(
        rr.reranker,
        "score",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("disabled reranker must not be called")),
    )
    text = "Allgemeiner Inhalt.\n\nICHI BAN AG hat ihren Sitz in Berlin."
    passage = wr.best_passage("ICHI BAN AG Berlin", text, 1000)
    assert "ICHI BAN AG" in passage
