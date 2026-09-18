#!/usr/bin/env python3
"""Operator CLI for per-user Nextcloud CardDAV seed administration.

This is deliberately keyed by the human Nextcloud login. Canonical UUIDs stay an
internal join key and are never required for routine administration.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from rag.carddav_sync import (
    CardDAVClient,
    CardDAVSettings,
    _store_from_config,
    resolve_nextcloud_user,
    sync_for_canonical_user,
)
from rag.graph import BASE_DIR, load_config


def _settings_json(settings):
    if settings is None:
        return None
    data = asdict(settings)
    data["include_addressbooks"] = list(settings.include_addressbooks)
    data["exclude_addressbooks"] = list(settings.exclude_addressbooks)
    return data


def _resolve(store, parser, login: str, server: str):
    try:
        user = resolve_nextcloud_user(store, login, server=server)
    except ValueError as exc:
        parser.error(str(exc))
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Administer Nextcloud CardDAV contact seeds")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--store", default="", help="CredentialStore path (normally from config)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List known Nextcloud users and contact-seed status")

    for name, help_text in (
        ("status", "Show one user's contact-seed configuration/status"),
        ("books", "List the user's selected CardDAV address books"),
        ("sync", "Synchronize the user's selected address books into Neo4j"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--user", required=True, help="Nextcloud login")
        p.add_argument("--server", default="", help="Nextcloud base URL if login is ambiguous")
        if name == "sync":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--limit", type=int, default=0)
            p.add_argument("--force", action="store_true", help="Ignore disabled contact-sync setting")

    args = parser.parse_args()
    cfg = load_config(args.config)
    store = _store_from_config(cfg, args.store)

    if args.command == "list":
        rows = []
        for user in store.list_canonical_users():
            settings = store.get_contact_sync_settings(user.canonical_user_id)
            rows.append({
                "nextcloud_login": user.nextcloud_login,
                "nextcloud_server": user.nextcloud_server,
                "user_enabled": user.enabled,
                "has_nextcloud_credential": store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id) is not None,
                "contact_sync": _settings_json(settings),
            })
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    user = _resolve(store, parser, args.user, args.server)
    if user is None:
        print(json.dumps({
            "status": "skipped",
            "reason": "unknown_nextcloud_user",
            "nextcloud_login": args.user,
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        print(json.dumps({
            "nextcloud_login": user.nextcloud_login,
            "nextcloud_server": user.nextcloud_server,
            "user_enabled": user.enabled,
            "has_nextcloud_credential": store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id) is not None,
            "contact_sync": _settings_json(store.get_contact_sync_settings(user.canonical_user_id)),
        }, ensure_ascii=False, indent=2))
        return 0

    credential = store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id)
    if credential is None:
        print(json.dumps({
            "status": "skipped", "reason": "nextcloud_credential_missing",
            "nextcloud_login": user.nextcloud_login, "nextcloud_server": user.nextcloud_server,
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "books":
        settings = CardDAVSettings.for_canonical_user(
            cfg, user, credential, store.get_contact_sync_settings(user.canonical_user_id)
        )
        with CardDAVClient(settings) as dav:
            books = dav.selected_addressbooks()
        print(json.dumps(books, ensure_ascii=False, indent=2))
        return 0

    if args.command == "sync":
        summary = sync_for_canonical_user(
            cfg, store, user, dry_run=args.dry_run,
            limit=max(0, int(args.limit)), force=bool(args.force),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not summary.get("errors") else 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
