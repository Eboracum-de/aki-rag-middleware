from rag.carddav_sync import _sanitize_vcard_for_retry


def test_vcard_retry_rejoins_literal_newline_continuation():
    raw = "BEGIN:VCARD\r\nVERSION:3.0\r\nADR:;;Street\r\n\\nGiselastraße 6\r\nEND:VCARD\r\n"
    cleaned, changed = _sanitize_vcard_for_retry(raw)
    assert changed is True
    assert "ADR:;;Street\\nGiselastraße 6" in cleaned


def test_vcard_retry_drops_standalone_literal_newline_marker():
    raw = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Example\r\n\\n\r\nEND:VCARD\r\n"
    cleaned, changed = _sanitize_vcard_for_retry(raw)
    assert changed is True
    assert "\r\n\\n\r\n" not in cleaned
