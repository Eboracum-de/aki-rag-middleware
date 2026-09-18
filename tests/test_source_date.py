from rag.source_date import infer_source_date


def test_explicit_german_header_date_beats_filename():
    result = infer_source_date(
        title="Scans/scan-2026-08-29.pdf",
        text="Karben, den 14. März 2016\nSehr geehrte Damen und Herren...",
    )
    assert result.value == "2016-03-14"
    assert result.precision == "day"
    assert result.confidence >= 0.9
    assert result.basis == "explicit_text"


def test_filename_date_is_fallback():
    result = infer_source_date(title="Vertrag-21-02-22.pdf", text="Vertrag zwischen A und B")
    assert result.value == "2022-02-21"
    assert result.basis == "filename"


def test_technical_date_is_not_inferred_when_content_has_none():
    result = infer_source_date(title="scan0562.pdf", text="Undatierter alter Scan")
    assert result.value == ""
