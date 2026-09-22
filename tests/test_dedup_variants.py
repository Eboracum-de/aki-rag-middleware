from rag.search import (
    _dedup_content_hash,
    _dedup_filename_signature,
    _same_filename_variant,
    deduplicate_retrieval_arm,
    filename_lookup,
)


def test_same_stem_mail_representations_are_document_variants():
    txt = _dedup_filename_signature({"path": "RAG/Mailarchiv/msg-1/message.txt"})
    html = _dedup_filename_signature({"path": "RAG/Mailarchiv/msg-1/message.html"})
    md = _dedup_filename_signature({"path": "RAG/Mailarchiv/msg-1/message.md"})
    pdf = _dedup_filename_signature({"path": "RAG/Mailarchiv/msg-1/message.pdf"})

    assert txt is not None and html is not None and md is not None and pdf is not None
    assert _same_filename_variant(txt, html) is True
    assert _same_filename_variant(txt, md) is True
    assert _same_filename_variant(html, pdf) is True


def test_same_stem_in_different_directories_is_not_collapsed():
    left = _dedup_filename_signature({"path": "A/message.txt"})
    right = _dedup_filename_signature({"path": "B/message.html"})
    assert _same_filename_variant(left, right) is False



def _result(document_id, path, *, content_hash="", snippet=""):
    return {
        "document_id": document_id,
        "title": path,
        "path": "/" + path.lstrip("/"),
        "rank": 1,
        "score": 1.0,
        "snippet": snippet,
        "es_snippet": snippet,
        "content_hash": content_hash,
        "duplicate_variants": [],
    }


def test_exact_extracted_content_hash_is_primary_duplicate_signal():
    digest = "0123456789abcdef0123456789abcdef"
    results = [
        _result("files:10", "A/rechnung.pdf", content_hash=digest, snippet="erste Fassung"),
        _result("files:20", "B/scan.odt", content_hash=digest.upper(), snippet="andere Trefferpassage"),
    ]
    unique = deduplicate_retrieval_arm(results, "es")
    assert len(unique) == 1
    assert unique[0]["document_id"] == "files:10"
    assert unique[0]["duplicate_count"] == 2
    assert unique[0]["duplicate_variants"][0]["document_id"] == "files:20"
    assert unique[0]["duplicate_variants"][0]["reason"] == "exact_extracted_content_hash"
    assert unique[0]["duplicate_variants"][0]["similarity"] == 1.0


def test_invalid_or_missing_hash_never_forces_duplicate_grouping():
    left = _result("files:10", "A/alpha.pdf", content_hash="not-an-md5", snippet="kurz alpha")
    right = _result("files:20", "B/beta.odt", content_hash="not-an-md5", snippet="kurz beta")
    assert _dedup_content_hash(left) == ""
    unique = deduplicate_retrieval_arm([left, right], "es")
    assert [item["document_id"] for item in unique] == ["files:10", "files:20"]


def test_hash_field_is_requested_and_mapped_from_nextcloud_elasticsearch(monkeypatch):
    digest = "0123456789abcdef0123456789abcdef"
    captured = {}

    class FakeResponse:
        is_error = False
        status_code = 200
        reason_phrase = "OK"
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "hits": {
                    "hits": [{
                        "_id": "files:1",
                        "_score": 1.0,
                        "_source": {
                            "title": "Folder/report.pdf",
                            "hash": digest,
                        },
                    }]
                }
            }

    def fake_post(endpoint, *, json, timeout):
        captured["body"] = json
        return FakeResponse()

    monkeypatch.setattr("rag.search._es_post", fake_post)
    results = filename_lookup("report.pdf")

    assert "hash" in captured["body"]["_source"]
    assert results[0]["content_hash"] == digest
