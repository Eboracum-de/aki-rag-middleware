from rag.source_registry import _resolve_sidecar_member_path


def test_sidecar_member_uses_container_path():
    sidecar = "Mailarchiv/main/INBOX/2025/09/msg/.mailmeta.json"
    assert _resolve_sidecar_member_path(sidecar, "mail.txt") == "Mailarchiv/main/INBOX/2025/09/msg/mail.txt"
    assert _resolve_sidecar_member_path(sidecar, "a01_Rechnung.pdf") == "Mailarchiv/main/INBOX/2025/09/msg/a01_Rechnung.pdf"


def test_sidecar_member_keeps_absolute_eml_path():
    sidecar = "Mailarchiv/main/INBOX/2025/09/msg/.mailmeta.json"
    assert _resolve_sidecar_member_path(sidecar, "/EML/main/INBOX/2025/09/msg/message.eml") == "EML/main/INBOX/2025/09/msg/message.eml"


def test_same_attachment_name_in_different_mail_containers_is_unambiguous():
    first = _resolve_sidecar_member_path("Mailarchiv/a/.mailmeta.json", "Rechnung.pdf")
    second = _resolve_sidecar_member_path("Mailarchiv/b/.mailmeta.json", "Rechnung.pdf")
    assert first == "Mailarchiv/a/Rechnung.pdf"
    assert second == "Mailarchiv/b/Rechnung.pdf"
    assert first != second
