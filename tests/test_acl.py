from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from rag.acl import NextcloudLiveAcl, build_fileid_search_xml, parse_authorized_fileids


MULTISTATUS_ONE = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:response><d:propstat><d:prop><oc:fileid>2</oc:fileid></d:prop></d:propstat></d:response>
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
