"""Local encrypted-secret support for the portable credential-store backend.

Stage 1 deliberately keeps key management simple and distribution-neutral:
AES-256-GCM protects reversible secrets in SQLite while a separate master key
file is provisioned by root and readable by the RAG service account.  More
isolated backends (systemd credentials/TPM/HSM) can implement the same contract
later without changing CredentialStore callers.
"""
from __future__ import annotations

import base64
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rag.logging_utils import get_logger


log = get_logger("credentials")
ENCRYPTED_PREFIX = "enc:v1:"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_ALLOWED_MODES = {"disabled", "preferred", "required"}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_master_key_path(value: str | Path | None = None) -> Path:
    raw = str(value or os.getenv("RAG_CREDENTIAL_MASTER_KEY_FILE", "runtime/credential-master.key")).strip()
    path = Path(raw or "runtime/credential-master.key")
    if not path.is_absolute():
        path = _project_root() / path
    return path


def encryption_mode(value: str | None = None) -> str:
    mode = str(value or os.getenv("RAG_CREDENTIAL_ENCRYPTION", "preferred")).strip().lower()
    if mode not in _ALLOWED_MODES:
        raise RuntimeError(f"invalid RAG_CREDENTIAL_ENCRYPTION={mode!r}; expected disabled, preferred or required")
    return mode


def is_encrypted(value: str | bytes | None) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def _decode_key(raw: bytes) -> bytes:
    data = raw.strip()
    if len(data) == _KEY_BYTES:
        return bytes(data)
    try:
        decoded = base64.urlsafe_b64decode(data + b"=" * ((4 - len(data) % 4) % 4))
    except Exception as exc:
        raise RuntimeError("credential master key is neither 32 raw bytes nor URL-safe base64") from exc
    if len(decoded) != _KEY_BYTES:
        raise RuntimeError(f"credential master key must decode to {_KEY_BYTES} bytes")
    return decoded


def _encode_key(key: bytes) -> bytes:
    return base64.urlsafe_b64encode(key).rstrip(b"=") + b"\n"


def key_file_status(path: str | Path | None = None) -> dict[str, object]:
    p = resolve_master_key_path(path)
    out: dict[str, object] = {
        "path": str(p),
        "exists": p.exists(),
        "mode": None,
        "uid": None,
        "gid": None,
        "secure_permissions": False,
        "readable": False,
        "valid": False,
    }
    if not p.exists():
        return out
    try:
        st = p.stat()
        mode = stat.S_IMODE(st.st_mode)
        out.update(mode=f"{mode:04o}", uid=st.st_uid, gid=st.st_gid)
        # root:rag 0640 is the intended deployment.  Portable installs may use
        # another owner/group, but group/other write and any other access are rejected.
        out["secure_permissions"] = not bool(mode & 0o027) and bool(mode & 0o400)
        out["readable"] = os.access(p, os.R_OK)
        _decode_key(p.read_bytes())
        out["valid"] = True
    except Exception:
        log.debug("Credential master-key status check failed for %s", p, exc_info=True)
    return out


def generate_master_key(path: str | Path | None = None, *, force: bool = False, mode: int = 0o640) -> Path:
    p = resolve_master_key_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    fd = os.open(p, flags, mode)
    try:
        os.write(fd, _encode_key(secrets.token_bytes(_KEY_BYTES)))
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    return p


@dataclass(frozen=True)
class SecretCrypto:
    mode: str
    key_path: Path
    key: bytes | None

    @classmethod
    def from_environment(cls) -> "SecretCrypto":
        mode = encryption_mode()
        path = resolve_master_key_path()
        if mode == "disabled":
            return cls(mode=mode, key_path=path, key=None)
        if not path.exists():
            if mode == "required":
                raise RuntimeError(f"credential encryption is required but master key is missing: {path}")
            return cls(mode=mode, key_path=path, key=None)
        status = key_file_status(path)
        if not status.get("valid"):
            raise RuntimeError(f"credential master key is invalid: {path}")
        if mode == "required" and not status.get("secure_permissions"):
            raise RuntimeError(
                f"credential master key permissions are too open: {path} mode={status.get('mode')}; expected owner read and at most group read (e.g. 0640)"
            )
        return cls(mode=mode, key_path=path, key=_decode_key(path.read_bytes()))

    @property
    def enabled(self) -> bool:
        return self.key is not None and self.mode != "disabled"

    def encrypt(self, plaintext: str, *, aad: str) -> str:
        value = str(plaintext)
        if is_encrypted(value):
            return value
        if not self.enabled:
            if self.mode == "required":
                raise RuntimeError("credential encryption is required but no master key is available")
            return value
        nonce = secrets.token_bytes(_NONCE_BYTES)
        cipher = AESGCM(self.key).encrypt(nonce, value.encode("utf-8"), aad.encode("utf-8"))
        payload = base64.urlsafe_b64encode(nonce + cipher).decode("ascii").rstrip("=")
        return ENCRYPTED_PREFIX + payload

    def decrypt(self, stored: str, *, aad: str, allow_plaintext: bool = False) -> str:
        value = str(stored or "")
        if not is_encrypted(value):
            if self.mode == "required" and not allow_plaintext:
                raise RuntimeError("plaintext credential encountered while encryption is required; run rag.secret_admin migrate")
            return value
        if not self.key:
            raise RuntimeError(f"encrypted credential cannot be decrypted without master key: {self.key_path}")
        encoded = value[len(ENCRYPTED_PREFIX):].encode("ascii")
        try:
            raw = base64.urlsafe_b64decode(encoded + b"=" * ((4 - len(encoded) % 4) % 4))
            if len(raw) <= _NONCE_BYTES:
                raise ValueError("ciphertext too short")
            clear = AESGCM(self.key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], aad.encode("utf-8"))
            return clear.decode("utf-8")
        except Exception as exc:
            raise RuntimeError("credential decryption/authentication failed") from exc
