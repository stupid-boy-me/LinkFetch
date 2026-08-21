"""Password gate for VIP / member-content downloads (local only)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

_ITERATIONS = 120_000
_FILENAME = "vip_auth.json"


def _config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "LinkFetch")
    os.makedirs(path, exist_ok=True)
    return path


def _auth_path() -> str:
    return os.path.join(_config_dir(), _FILENAME)


def has_password() -> bool:
    return os.path.isfile(_auth_path())


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return digest.hex()


def set_password(password: str) -> None:
    password = (password or "").strip()
    if len(password) < 4:
        raise ValueError("密码至少 4 位")
    salt = secrets.token_bytes(16)
    payload = {
        "v": 1,
        "iterations": _ITERATIONS,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt),
    }
    path = _auth_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def verify_password(password: str) -> bool:
    path = _auth_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        salt = bytes.fromhex(data["salt"])
        expected = data["hash"]
        got = _hash_password(password or "", salt)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def clear_password() -> None:
    path = _auth_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
