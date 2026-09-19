from rag.search import _dedup_filename_signature, _same_filename_variant


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
