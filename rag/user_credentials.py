"""Admin CLI for canonical user bindings and protected credentials."""
from __future__ import annotations

import argparse
import getpass

from rag.credential_store import CredentialStore, scope_identity, split_scoped_identity


def _identity(user_id: str, client_id: str) -> str:
    if split_scoped_identity(user_id) is not None:
        return user_id
    if client_id:
        return scope_identity(client_id, user_id)
    return user_id


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--store", default="runtime/users.sqlite")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set-nextcloud")
    s.add_argument("user_id", help="external user id, or already scoped client::user id")
    s.add_argument("username")
    s.add_argument("--client", default="", help="trusted provider client id for an external user id")
    s.add_argument("--server", required=True, help="canonical Nextcloud base URL")
    s.add_argument("--app-password", default="")

    d = sub.add_parser("delete-nextcloud")
    d.add_argument("user_id")
    d.add_argument("--client", default="")

    sub.add_parser("list-users")

    args = p.parse_args()
    store = CredentialStore(args.store)

    if args.cmd == "list-users":
        for user in store.list_canonical_users():
            bindings = store.list_bindings(user.canonical_user_id)
            print(
                f"{user.canonical_user_id}\t{user.nextcloud_server}\t{user.nextcloud_login}\t"
                f"enabled={int(user.enabled)}\tbindings={len(bindings)}\t"
                f"mail_accounts={len(store.list_mail_accounts(user.canonical_user_id))}\t"
                f"web={'yes' if store.get_web_settings(user.canonical_user_id) else 'no'}"
            )
        return

    identity = _identity(args.user_id, args.client)
    if args.cmd == "set-nextcloud":
        secret = args.app_password or getpass.getpass("Nextcloud app password: ")
        store.set_credential(identity, "nextcloud", args.username, secret, server=args.server)
        canonical = store.bind_identity(identity, args.server, args.username)
        print(
            f"stored nextcloud credential for {identity}; canonical_user_id={canonical.canonical_user_id}"
        )
    else:
        print("deleted" if store.delete_credential(identity, "nextcloud") else "not found")


if __name__ == "__main__":
    main()
