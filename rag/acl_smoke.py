"""Small diagnostic for the live Nextcloud ACL path."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

from rag.acl import NextcloudLiveAcl


def main() -> int:
    parser = argparse.ArgumentParser(description="Test live Nextcloud ACL for file IDs")
    parser.add_argument("file_ids", nargs="+", help="files:123 or numeric Nextcloud fileid")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--user-id", default=os.getenv("RAG_TEST_USER_ID", ""))
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    acl = NextcloudLiveAcl(cfg)
    # The CLI is explicitly an ACL test, so do not silently succeed when ACL
    # has not been enabled in the config.
    if not acl.enabled:
        print("ACL is disabled in config.yaml (acl.enabled=false)")
        return 2
    items = []
    for value in args.file_ids:
        text = str(value).strip()
        if text.isdigit():
            text = "files:" + text
        items.append({"document_id": text, "title": text})
    decision = acl.authorize(items, rag_user_id=args.user_id or None)
    authorized = {str(item.get("document_id")) for item in decision.results}
    for item in items:
        doc_id = str(item["document_id"])
        print(f"{'ALLOW' if doc_id in authorized else 'NOT_VISIBLE'}  {doc_id}")
    print(f"checked={decision.checked} authorized={decision.authorized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
