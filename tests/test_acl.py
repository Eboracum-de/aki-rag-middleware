from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from rag.acl import (
    NextcloudLiveAcl,
    build_fileid_search_xml,
    parse_authorized_file_paths,
    parse_authorized_fileids,
)


MULTISTATUS_ONE = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:response><d:propstat><d:prop><oc:fileid>2</oc:fileid></d:prop></d:propstat></d:response>
</d:multistatus>'''

MULTISTATUS_PATH = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:response>
    <d:href>/remote.php/dav/files/alice/AKI-Chats/2026-09-22%20-%20Test%20-%20deadbeef.md</d:href>
    <d:propstat><d:prop><oc:fileid>42</oc:fileid></d:prop></d:propstat>
  </d:response>
</d:multistatus>'''

MULTISTATUS_SUBPATH = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:response>
    <d:href>/nextcloud/remote.php/dav/files/alice/AKI-Chats/2026-09-22%20-%20Test%20-%20deadbeef.md</d:href>
    <d:propstat><d:prop><oc:fileid>42</oc:fileid></d:prop></d:propstat>
  </d:response>
</d:multistatus>'''


class LiveAclTests(unittest.TestCase):
    def test_search_xml_contains_all_ids(self):
        body = build_fileid_search_xml("alice", ["1", "2", "2"])
        text = body.decode("utf-8")
        self.assertIn("/files/alice", text)
        self.assertEqual(text.count("<d:literal>2</d:literal>"), 1)
        self.assertIn("<d:literal>1</d:literal>", text)

    def test_balanced_search_xml_handles_large_id_sets(self):
        body = build_fileid_search_xml("alice", [str(i) for i in range(1, 2001)])
        text = body.decode("utf-8")
        self.assertIn("<d:literal>2000</d:literal>", text)

    def test_parse_fileids(self):
        self.assertEqual(parse_authorized_fileids(MULTISTATUS_ONE), {"2"})

    def test_parse_server_derived_visible_paths(self):
        self.assertEqual(
            parse_authorized_file_paths(MULTISTATUS_PATH, "alice"),
            {"42": "AKI-Chats/2026-09-22 - Test - deadbeef.md"},
        )

    def test_parse_server_derived_visible_paths_with_nextcloud_subpath(self):
        self.assertEqual(
            parse_authorized_file_paths(
                MULTISTATUS_SUBPATH,
                "alice",
                "/nextcloud/remote.php/dav/",
            ),
            {"42": "AKI-Chats/2026-09-22 - Test - deadbeef.md"},
        )

    def test_resolve_visible_file_path_uses_authenticated_dav_result(self):
        os.environ["NEXTCLOUD_USERNAME"] = "alice"
        os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
        cfg = {
            "nextcloud": {"base_url": "https://nc.example"},
            "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
        }
        response = httpx.Response(
            207,
            content=MULTISTATUS_PATH,
            request=httpx.Request("SEARCH", "https://nc.example/remote.php/dav/"),
        )
        with patch("rag.acl.httpx.request", return_value=response) as request_mock:
            path = NextcloudLiveAcl(cfg).resolve_visible_file_path("files:42")
        self.assertEqual(path, "AKI-Chats/2026-09-22 - Test - deadbeef.md")
        self.assertEqual(request_mock.call_args.kwargs["auth"], ("alice", "secret"))

    def test_resolve_visible_file_path_uses_nextcloud_subpath(self):
        os.environ["NEXTCLOUD_USERNAME"] = "alice"
        os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
        cfg = {
            "nextcloud": {"base_url": "https://nc.example/nextcloud"},
            "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
        }
        response = httpx.Response(
            207,
            content=MULTISTATUS_SUBPATH,
            request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
        )
        with patch("rag.acl.httpx.request", return_value=response):
            path = NextcloudLiveAcl(cfg).resolve_visible_file_path("files:42")
        self.assertEqual(path, "AKI-Chats/2026-09-22 - Test - deadbeef.md")

    def test_filter_does_not_backfill(self):
        os.environ["NEXTCLOUD_USERNAME"] = "alice"
        os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
        cfg = {
            "nextcloud": {"base_url": "https://nc.example/nextcloud"},
            "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
        }
        response = httpx.Response(
            207,
            content=MULTISTATUS_ONE,
            request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
        )
        with patch("rag.acl.httpx.request", return_value=response):
            decision = NextcloudLiveAcl(cfg).authorize([
                {"document_id": "files:1", "rank": 1},
                {"document_id": "files:2", "rank": 2},
                {"document_id": "files:3", "rank": 3},
            ])
        self.assertEqual([x["document_id"] for x in decision.results], ["files:2"])
        self.assertEqual(decision.checked, 3)
        self.assertEqual(decision.authorized, 1)

    def test_acl_batches_large_result_sets(self):
        os.environ["NEXTCLOUD_USERNAME"] = "alice"
        os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
        cfg = {
            "nextcloud": {"base_url": "https://nc.example/nextcloud"},
            "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False, "batch_size": 2},
        }
        response = httpx.Response(
            207, content=MULTISTATUS_ONE,
            request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
        )
        with patch("rag.acl.httpx.request", return_value=response) as request_mock:
            decision = NextcloudLiveAcl(cfg).authorize([
                {"document_id": f"files:{i}", "rank": i} for i in range(1, 6)
            ])
        self.assertEqual(request_mock.call_count, 3)
        self.assertEqual([x["document_id"] for x in decision.results], ["files:2"])


def test_acl_uses_canonical_nextcloud_ca_file():
    os.environ["NEXTCLOUD_USERNAME"] = "alice"
    os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
    cfg = {
        "nextcloud": {
            "base_url": "https://nc.example",
            "verify_tls": True,
            "ca_file": "/opt/nextcloud-rag/runtime/ca/nextcloud-ca-bundle.pem",
        },
        "acl": {"enabled": True, "identity_mode": "single_user"},
    }
    response = httpx.Response(
        207,
        content=MULTISTATUS_ONE,
        request=httpx.Request("SEARCH", "https://nc.example/remote.php/dav/"),
    )
    with patch("rag.acl.httpx.request", return_value=response) as request_mock:
        NextcloudLiveAcl(cfg).authorize([{"document_id": "files:2"}])
    assert request_mock.call_args.kwargs["verify"] == "/opt/nextcloud-rag/runtime/ca/nextcloud-ca-bundle.pem"


if __name__ == "__main__":
    unittest.main()


def test_acl_credential_store_mode(tmp_path):
    from rag.credential_store import CredentialStore
    store_path = tmp_path / "users.sqlite"
    CredentialStore(store_path).set_credential("owui-1", "nextcloud", "alice", "secret")
    cfg = {
        "nextcloud": {"base_url": "https://nc.example"},
        "acl": {
            "enabled": True,
            "identity_mode": "credential_store",
            "credential_store": str(store_path),
            "verify_tls": False,
        },
    }
    cred = NextcloudLiveAcl(cfg).credential_for_user("owui-1")
    assert cred.username == "alice"
    assert cred.password == "secret"


def test_acl_accepts_explicit_temporary_credential():
    cfg = {
        "nextcloud": {"base_url": "https://nc.example"},
        "acl": {"enabled": True, "verify_tls": False},
    }
    response = httpx.Response(
        207,
        content=MULTISTATUS_ONE,
        request=httpx.Request("SEARCH", "https://nc.example/remote.php/dav/"),
    )
    with patch("rag.acl.httpx.request", return_value=response) as request_mock:
        decision = NextcloudLiveAcl(cfg).authorize_with_credential(
            [{"document_id": "files:1"}, {"document_id": "files:2"}],
            username="alice",
            password="temporary",
        )
    assert [x["document_id"] for x in decision.results] == ["files:2"]
    assert request_mock.call_args.kwargs["auth"] == ("alice", "temporary")



def _multistatus_for(*file_ids: int) -> bytes:
    entries = "".join(
        f"<d:response><d:propstat><d:prop><oc:fileid>{file_id}</oc:fileid></d:prop></d:propstat></d:response>"
        for file_id in file_ids
    )
    return (
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
        'xmlns:oc="http://owncloud.org/ns">' + entries + "</d:multistatus>"
    ).encode("utf-8")


def test_acl_promotes_visible_duplicate_when_ranked_representative_is_denied():
    os.environ["NEXTCLOUD_USERNAME"] = "alice"
    os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
    cfg = {
        "nextcloud": {"base_url": "https://nc.example/nextcloud"},
        "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
    }
    response = httpx.Response(
        207,
        content=_multistatus_for(2),
        request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
    )
    result = {
        "document_id": "files:1",
        "title": "private.pdf",
        "context_text": "SECRET FROM DENIED REPRESENTATIVE",
        "context_enriched": True,
        "es_snippet": "SECRET ES",
        "text": "SECRET RAW TEXT",
        "chunk": "SECRET RAW CHUNK",
        "private_payload": {"body": "SECRET RAW OBJECT"},
        "rrf_rank": 4,
        "duplicate_variants": [{
            "document_id": "files:2",
            "title": "visible.pdf",
            "path": "/visible.pdf",
            "directory": "/",
            "filename": "visible.pdf",
            "nextcloud_openfile_id": "2",
            "source_url": "https://nc.example/open-visible",
            "es_snippet": "visible snippet",
            "snippet": "visible snippet",
            "reason": "exact_extracted_content_hash",
            "similarity": 1.0,
        }],
        "duplicate_count": 2,
    }
    with patch("rag.acl.httpx.request", return_value=response) as request_mock:
        decision = NextcloudLiveAcl(cfg).authorize([result])

    assert decision.checked == 1
    assert decision.authorized == 1
    assert len(decision.results) == 1
    promoted = decision.results[0]
    assert promoted["document_id"] == "files:2"
    assert promoted["title"] == "visible.pdf"
    assert promoted["context_text"] == "visible snippet"
    assert "SECRET" not in promoted["context_text"]
    assert "SECRET" not in promoted["es_snippet"]
    assert promoted["context_enriched"] is False
    assert promoted["acl_promoted_duplicate"] is True
    assert promoted["rrf_rank"] == 4
    for key in ("text", "chunk", "private_payload"):
        assert key not in promoted
    assert promoted["duplicate_variants"] == []
    request_xml = request_mock.call_args.kwargs["content"].decode("utf-8")
    assert "<d:literal>1</d:literal>" in request_xml
    assert "<d:literal>2</d:literal>" in request_xml


def test_acl_duplicate_promotion_drops_denied_identity_for_legacy_variant():
    os.environ["NEXTCLOUD_USERNAME"] = "alice"
    os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
    cfg = {
        "nextcloud": {"base_url": "https://nc.example/nextcloud"},
        "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
    }
    response = httpx.Response(
        207,
        content=_multistatus_for(2),
        request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
    )
    result = {
        "document_id": "files:1",
        "id": "files:1",
        "fileid": "1",
        "title": "private.pdf",
        "path": "/secret/private.pdf",
        "source_url": "https://nc.example/secret",
        "owner": "private-owner",
        "users": ["private-user"],
        "groups": ["private-group"],
        "source_origin": "documents",
        "es_snippet": "SECRET",
        "duplicate_variants": [{
            "fileid": "2",
            "title": "visible.pdf",
            "snippet": "visible snippet",
        }],
        "duplicate_count": 2,
    }

    with patch("rag.acl.httpx.request", return_value=response):
        decision = NextcloudLiveAcl(cfg).authorize([result])

    promoted = decision.results[0]
    assert promoted["document_id"] == "files:2"
    assert promoted["fileid"] == "2"
    assert promoted["title"] == "visible.pdf"
    assert promoted["context_text"] == "visible snippet"
    for key in ("id", "path", "source_url", "owner", "users", "groups", "source_origin"):
        assert key not in promoted
    assert "SECRET" not in promoted["context_text"]
    assert "SECRET" not in promoted["es_snippet"]


def test_acl_hides_unauthorized_duplicate_metadata_when_representative_is_visible():
    os.environ["NEXTCLOUD_USERNAME"] = "alice"
    os.environ["NEXTCLOUD_APP_PASSWORD"] = "secret"
    cfg = {
        "nextcloud": {"base_url": "https://nc.example/nextcloud"},
        "acl": {"enabled": True, "identity_mode": "single_user", "verify_tls": False},
    }
    response = httpx.Response(
        207,
        content=_multistatus_for(1),
        request=httpx.Request("SEARCH", "https://nc.example/nextcloud/remote.php/dav/"),
    )
    result = {
        "document_id": "files:1",
        "title": "visible.pdf",
        "duplicate_variants": [{
            "document_id": "files:2",
            "title": "hidden.pdf",
            "es_snippet": "HIDDEN VARIANT",
        }],
        "duplicate_count": 2,
    }
    with patch("rag.acl.httpx.request", return_value=response):
        decision = NextcloudLiveAcl(cfg).authorize([result])

    assert len(decision.results) == 1
    assert decision.results[0]["document_id"] == "files:1"
    assert decision.results[0]["duplicate_variants"] == []
    assert decision.results[0]["duplicate_count"] == 1
