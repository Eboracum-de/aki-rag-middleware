"""Administrative CLI for the local encrypted credential store.

This command never prints cleartext secrets.  Key creation is intentionally a
filesystem/OS-admin action; web administrators may inspect status and migrate
only if the running service account already has access to the master key.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path

from rag.credential_store import CredentialStore
from rag.secret_crypto import generate_master_key, key_file_status, resolve_master_key_path


def _print_status(status: dict[str, object]) -> None:
    key = dict(status.get("master_key") or {})
    print(f"encryption_mode={status.get('encryption_mode')}")
    print(f"master_key={key.get('path')} exists={int(bool(key.get('exists')))} valid={int(bool(key.get('valid')))} mode={key.get('mode') or '-'} uid={key.get('uid')} gid={key.get('gid')}")
    print(
        "credentials="
        f"{status.get('credentials_total', 0)} encrypted={status.get('credentials_encrypted', 0)} plaintext={status.get('credentials_plaintext', 0)}"
    )
    print(
        "login_flows="
        f"{status.get('flows_total', 0)} encrypted={status.get('flows_encrypted', 0)} plaintext={status.get('flows_plaintext', 0)}"
    )
    if "ok" in status:
        print(f"verify={'OK' if status.get('ok') else 'FAIL'}")
        for error in status.get("errors") or []:
            print(f"error={error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage encrypted RAG credentials without exposing secret values")
    parser.add_argument("--store", default="runtime/users.sqlite")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")

    init = sub.add_parser("init-key")
    init.add_argument("--path", default="")
    init.add_argument("--group", default="rag")
    init.add_argument("--force", action="store_true")

    sub.add_parser("migrate")
    sub.add_parser("verify")
    args = parser.parse_args()

    if args.cmd == "init-key":
        path = resolve_master_key_path(args.path or None)
        created = generate_master_key(path, force=args.force, mode=0o640)
        try:
            gid = grp.getgrnam(args.group).gr_gid
            os.chown(created, 0 if os.geteuid() == 0 else os.getuid(), gid)
        except (KeyError, PermissionError):
            # Portable/dev installs may not have a 'rag' group or root privileges.
            pass
        os.chmod(created, 0o640)
        result = key_file_status(created)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"created master key: {created}")
            print(f"mode={result.get('mode')} uid={result.get('uid')} gid={result.get('gid')} valid={int(bool(result.get('valid')))}")
        return

    store = CredentialStore(Path(args.store))
    if args.cmd == "status":
        result = store.secret_security_status()
    elif args.cmd == "migrate":
        changed = store.migrate_plaintext_secrets()
        result = store.secret_security_status()
        result["migrated"] = changed
    else:
        result = store.verify_secret_encryption()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if args.cmd == "migrate":
            migrated = result.get("migrated") or {}
            print(f"migrated credentials={migrated.get('credentials', 0)} login_flows={migrated.get('flows', 0)}")
        _print_status(result)
    if args.cmd == "verify" and not result.get("ok"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
