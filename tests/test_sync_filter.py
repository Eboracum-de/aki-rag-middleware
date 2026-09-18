from rag.sync import semantic_document_allowed


def hit(title, content="text", content_type=""):
    return {"_id": "files:1", "_source": {"title": title, "content": content, "attachment": {"content_type": content_type}}}


def test_raw_eml_is_excluded_by_default():
    allowed, reason = semantic_document_allowed({}, hit("Mail/test.eml", "From: a@example.org\nBody", "message/rfc822"))
    assert allowed is False
    assert reason == "excluded_extension:eml"


def test_raw_mbox_is_excluded_by_default():
    allowed, reason = semantic_document_allowed({}, hit("Mail/archive.mbox", "From sender@example.org", "text/plain"))
    assert allowed is False
    assert reason == "excluded_extension:mbox"


def test_extensionless_raw_mail_is_excluded_by_mime_fallback():
    allowed, reason = semantic_document_allowed({}, hit("Mail/blob", "From: a@example.org\nBody", "message/rfc822"))
    assert allowed is False
    assert reason == "excluded_mime:message/rfc822"


def test_cleaned_mail_txt_wins_over_source_mail_mime():
    allowed, reason = semantic_document_allowed(
        {},
        hit(
            "Mail/2022-02-11-12-Text-Flächen-Brauerei-Musterstadt.txt",
            "From: Frank Muster <fh@example.org>\nSubject: Flächen Brauerei Musterstadt\n\nBody",
            "message/rfc822",
        ),
    )
    assert allowed is True
    assert reason == "allowed"


def test_non_hidden_mailmeta_json_is_excluded():
    allowed, reason = semantic_document_allowed({}, hit("Mail/message.mailmeta.json", '{"schema":"nextcloud-mailmeta-v1"}', "application/json"))
    assert allowed is False
    assert reason == "machine_mailmeta"


def test_image_with_extracted_content_is_allowed():
    allowed, reason = semantic_document_allowed({}, hit("Scans/scan.tiff", "Useful OCR or metadata text", "image/tiff"))
    assert allowed is True
    assert reason == "allowed"


def test_extensionless_image_with_extracted_content_is_allowed():
    allowed, reason = semantic_document_allowed({}, hit("Scans/blob", "Useful OCR or metadata text", "image/jpeg"))
    assert allowed is True
    assert reason == "allowed"


def test_ocr_pdf_remains_allowed():
    allowed, reason = semantic_document_allowed({}, hit("Scans/scan.pdf", "Useful OCR text", "application/pdf"))
    assert allowed is True
    assert reason == "allowed"


def test_archive_is_excluded_by_extension():
    allowed, reason = semantic_document_allowed({}, hit("Archive/data.zip", "names from archive", "text/plain"))
    assert allowed is False
    assert reason == "excluded_extension:zip"


def test_extensionless_archive_is_excluded_by_mime_fallback():
    allowed, reason = semantic_document_allowed({}, hit("Archive/blob", "names from archive", "application/zip"))
    assert allowed is False
    assert reason == "excluded_mime:application/zip"
