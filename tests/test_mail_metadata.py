from rag.mail_metadata import (
    is_mail_metadata_sidecar,
    message_key,
    normalize_mail_metadata,
    reply_parent_id,
    representation_role,
    sidecar_candidates,
)


def sample_meta():
    return normalize_mail_metadata({
        "schema": "nextcloud-mailmeta-v1",
        "content_kind": "email",
        "headers": {
            "message_id": "<child@example.org>",
            "in_reply_to": ["<parent@example.org>"],
            "references": ["<root@example.org>", "<parent@example.org>"],
            "date_iso": "2026-08-30T10:15:00+02:00",
            "subject": "Re: Test",
        },
        "files": {
            "eml": "original.eml",
            "text": "mail.txt",
            "html_pdf": ["mail.pdf"],
            "readme": "Readme.md",
            "attachments": ["anlage.pdf"],
        },
    })


def test_directory_sidecar_candidate():
    assert sidecar_candidates("Mailarchiv/Thread/mail.txt")[0] == "Mailarchiv/Thread/.mailmeta.json"


def test_flat_mail_sync_sidecar_candidate():
    title = "Mailarchiv/main/INBOX/2026/08/20260830-101500_42_mail.txt"
    assert sidecar_candidates(title) == [
        "Mailarchiv/main/INBOX/2026/08/.mailmeta.json",
        "Mailarchiv/main/INBOX/2026/08/.20260830-101500_42.mailmeta.json",
    ]


def test_machine_sidecars_are_detected():
    assert is_mail_metadata_sidecar("Mailarchiv/x/.mailmeta.json")
    assert is_mail_metadata_sidecar("Mailarchiv/x/.20260830-101500_42.mailmeta.json")
    assert not is_mail_metadata_sidecar("Mailarchiv/x/mail.txt")


def test_roles_are_deterministic():
    meta = sample_meta()
    assert representation_role(meta, "x/mail.txt") == "plain_text"
    assert representation_role(meta, "x/mail.pdf") == "html_pdf"
    assert representation_role(meta, "x/Readme.md") == "readme"
    assert representation_role(meta, "x/original.eml") == "eml"
    assert representation_role(meta, "x/anlage.pdf") == "attachment"
    assert representation_role(meta, "x/other.pdf") is None


def test_reply_parent_prefers_in_reply_to_then_references():
    meta = sample_meta()
    assert reply_parent_id(meta) == "<parent@example.org>"
    meta["headers"]["in_reply_to"] = []
    assert reply_parent_id(meta) == "<parent@example.org>"


def test_message_key_never_infers_identity_from_subject():
    assert message_key("<a@example.org>", "x/.mailmeta.json") == "message-id:<a@example.org>"
    assert message_key("", "x/.mailmeta.json") == "sidecar:x/.mailmeta.json"
