from email.message import EmailMessage

from rag.mail_sync import parse_mail, render_mail_metadata, render_mail_text


def build_raw():
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.org>"
    msg["To"] = "Bob <bob@example.org>"
    msg["Subject"] = "Re: Vorgang"
    msg["Message-ID"] = "<child@example.org>"
    msg["In-Reply-To"] = "<parent@example.org>"
    msg["References"] = "<root@example.org> <parent@example.org>"
    msg["Date"] = "Sun, 30 Aug 2026 10:15:00 +0200"
    msg.set_content("Hallo")
    return msg.as_bytes()


def test_mail_sync_preserves_thread_headers_in_text_and_sidecar():
    parsed = parse_mail(42, build_raw())
    assert parsed.in_reply_to == ["<parent@example.org>"]
    assert parsed.references == ["<root@example.org>", "<parent@example.org>"]

    text = render_mail_text("main", "INBOX", parsed)
    assert "IN-REPLY-TO: <parent@example.org>" in text
    assert "REFERENCES: <root@example.org> <parent@example.org>" in text

    sidecar = render_mail_metadata(
        "main", "INBOX", parsed,
        text_name="20260830-101500_42_mail.txt",
        attachment_names=[],
    ).decode("utf-8")
    assert '"schema": "nextcloud-mailmeta-v1"' in sidecar
    assert '"<parent@example.org>"' in sidecar
