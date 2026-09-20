from unittest.mock import patch

from rag.nextcloud_tls import nextcloud_verify_value


def test_nextcloud_tls_defaults_to_verified_system_trust():
    with patch("rag.nextcloud_tls.configure_tls_compat") as compat:
        cfg = {}
        assert nextcloud_verify_value(cfg) is True
        compat.assert_called_once_with(cfg)


def test_nextcloud_ca_file_is_canonical_and_scoped():
    cfg = {
        "nextcloud": {
            "verify_tls": True,
            "ca_file": "/opt/nextcloud-rag/runtime/ca/nextcloud-ca-bundle.pem",
        },
        "acl": {"verify_tls": False, "ca_file": "/legacy/acl.pem"},
    }
    with patch("rag.nextcloud_tls.configure_tls_compat"):
        assert nextcloud_verify_value(cfg, "acl") == "/opt/nextcloud-rag/runtime/ca/nextcloud-ca-bundle.pem"


def test_explicit_canonical_verify_false_beats_legacy_ca():
    cfg = {
        "nextcloud": {"verify_tls": False, "ca_file": ""},
        "acl": {"ca_file": "/legacy/acl.pem"},
    }
    with patch("rag.nextcloud_tls.configure_tls_compat"):
        assert nextcloud_verify_value(cfg, "acl") is False


def test_legacy_component_ca_remains_supported_for_upgrades():
    cfg = {
        "nextcloud": {"base_url": "https://nc.example"},
        "acl": {"verify_tls": True, "ca_file": "/legacy/acl.pem"},
    }
    with patch("rag.nextcloud_tls.configure_tls_compat"):
        assert nextcloud_verify_value(cfg, "acl") == "/legacy/acl.pem"


def test_legacy_sources_follow_caller_priority():
    cfg = {
        "nextcloud": {"base_url": "https://nc.example"},
        "auth": {"verify_tls": False},
        "acl": {"ca_file": "/legacy/acl.pem"},
    }
    with patch("rag.nextcloud_tls.configure_tls_compat"):
        assert nextcloud_verify_value(cfg, "auth", "acl") is False
