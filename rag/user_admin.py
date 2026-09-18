"""Administrative CLI for canonical users and per-user credentials.

Normal operations should use this CLI/Admin UI rather than editing users.sqlite
by hand. Secrets are never printed.
"""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from rag.credential_store import CredentialStore, canonical_credential_owner, normalize_nextcloud_server


def _select_user(store: CredentialStore, login: str, server: str = ""):
    wanted_login = str(login or "").strip()
    wanted_server = normalize_nextcloud_server(server) if server else ""
    rows = [u for u in store.list_canonical_users() if u.nextcloud_login == wanted_login]
    if wanted_server:
        rows = [u for u in rows if normalize_nextcloud_server(u.nextcloud_server) == wanted_server]
    if not rows:
        raise SystemExit(f"canonical user not found: {wanted_login}")
    if len(rows) > 1:
        raise SystemExit("login is ambiguous across Nextcloud servers; add --server")
    return rows[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Administer canonical RAG users without direct SQL")
    parser.add_argument("--store", default="runtime/users.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list canonical users")

    show = sub.add_parser("show", help="show one canonical user without secrets")
    show.add_argument("login")
    show.add_argument("--server", default="")

    reauth = sub.add_parser("reauth", help="clear Nextcloud app passwords/flows; next request re-authenticates")
    reauth.add_argument("login")
    reauth.add_argument("--server", default="")

    mail = sub.add_parser("set-mail-password", help="replace an IMAP password interactively")
    mail.add_argument("login")
    mail.add_argument("--server", default="")
    mail.add_argument("--account-id", default="")

    args = parser.parse_args()
    store = CredentialStore(Path(args.store))

    if args.command == "list":
        for user in store.list_canonical_users():
            print(f"{user.nextcloud_login}\t{'enabled' if user.enabled else 'disabled'}\t{user.nextcloud_server}\t{user.canonical_user_id}")
        return

    user = _select_user(store, args.login, args.server)

    if args.command == "show":
        bindings = store.list_bindings(user.canonical_user_id)
        mails = store.list_mail_accounts(user.canonical_user_id)
        web = store.get_web_settings(user.canonical_user_id)
        print(f"canonical_user_id={user.canonical_user_id}")
        print(f"nextcloud_server={user.nextcloud_server}")
        print(f"nextcloud_login={user.nextcloud_login}")
        print(f"enabled={str(user.enabled).lower()}")
        print(f"bindings={len(bindings)}")
        print(f"nextcloud_credential={'present' if store.get_nextcloud_credential_for_canonical_user(user.canonical_user_id) else 'missing'}")
        for account in mails:
            print(f"mail={account.account_id}\t{account.name}\t{account.username}@{account.host}\t{'enabled' if account.enabled else 'disabled'}\tsecret={'present' if account.has_secret else 'missing'}")
        if web:
            print(f"web={'enabled' if web.enabled else 'disabled'}\tarchive={'enabled' if web.archive_enabled else 'disabled'}\ttarget={web.target_path}")
        return

    if args.command == "reauth":
        result = store.clear_nextcloud_credentials_for_canonical_user(user.canonical_user_id)
        print("Nextcloud credentials cleared; next frontend request requires Login Flow v2")
        print(" ".join(f"{k}={v}" for k, v in result.items()))
        return

    if args.command == "set-mail-password":
        accounts = store.list_mail_accounts(user.canonical_user_id)
        if args.account_id:
            accounts = [a for a in accounts if a.account_id == args.account_id]
        if not accounts:
            raise SystemExit("mail account not found")
        if len(accounts) > 1:
            print("Multiple mail accounts configured; select one with --account-id:")
            for a in accounts:
                print(f"  {a.account_id}\t{a.name}\t{a.username}@{a.host}")
            raise SystemExit(2)
        account = accounts[0]
        secret = getpass.getpass(f"New IMAP password for {account.username}@{account.host}: ")
        if not secret:
            raise SystemExit("empty password refused")
        confirm = getpass.getpass("Repeat password: ")
        if secret != confirm:
            raise SystemExit("passwords do not match")
        store.set_credential(
            canonical_credential_owner(user.canonical_user_id),
            "mail_imap",
            account.username,
            secret,
            account_id=account.account_id,
            server=account.host,
        )
        print(f"mail password updated for account_id={account.account_id}")
        return


if __name__ == "__main__":
    main()
