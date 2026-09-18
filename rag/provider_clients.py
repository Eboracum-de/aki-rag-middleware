"""Admin CLI for trusted frontend/provider client credentials."""
from __future__ import annotations

import argparse
from pathlib import Path

from rag.credential_store import CredentialStore


def _store(path: str) -> CredentialStore:
    return CredentialStore(Path(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage trusted RAG frontend clients")
    parser.add_argument("--store", default="runtime/users.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a client and print its API key once")
    create.add_argument("client_id")
    create.add_argument("--name", default="")

    rotate = sub.add_parser("rotate", help="replace a client's API key and print the new key once")
    rotate.add_argument("client_id")
    rotate.add_argument("--name", default="")

    sub.add_parser("list", help="list clients; secrets are never shown")

    enable = sub.add_parser("enable")
    enable.add_argument("client_id")
    disable = sub.add_parser("disable")
    disable.add_argument("client_id")
    delete = sub.add_parser("delete")
    delete.add_argument("client_id")

    args = parser.parse_args()
    store = _store(args.store)

    if args.command == "create":
        key = store.create_client(args.client_id, name=args.name)
        print(f"client_id={args.client_id}")
        print(f"api_key={key}")
        return
    if args.command == "rotate":
        import secrets
        key = secrets.token_urlsafe(32)
        store.register_client(args.client_id, key, name=args.name or args.client_id, replace=True)
        print(f"client_id={args.client_id}")
        print(f"api_key={key}")
        return
    if args.command == "list":
        for item in store.list_clients():
            last = "never" if item.last_used_at is None else f"{item.last_used_at:.0f}"
            print(f"{item.client_id}\t{'enabled' if item.enabled else 'disabled'}\tlast_used={last}\t{item.name}")
        return
    if args.command in {"enable", "disable"}:
        ok = store.set_client_enabled(args.client_id, args.command == "enable")
        print("updated" if ok else "not found")
        return
    if args.command == "delete":
        print("deleted" if store.delete_client(args.client_id) else "not found")


if __name__ == "__main__":
    main()
