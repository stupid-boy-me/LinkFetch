"""Trial + one-time license gate (offline activation codes)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Any


# Change before public sale builds if you want a private key pool.
# Keep in sync with tools/gen_license_keys.py
_LICENSE_SECRET = b"LinkFetch-OneTime-2026-v1"

TRIAL_SECONDS = 3600  # 1 hour full-feature trial
_STATE_FILE = "license.json"
_KEY_RE = re.compile(r"^LF1-([A-F0-9]{4}-){3}[A-F0-9]{4}$", re.I)


def config_dir() -> str:
    """License lives next to downloads: ~/Downloads/LinkFetch/license.json"""
    path = os.path.join(os.path.expanduser("~"), "Downloads", "LinkFetch")
    os.makedirs(path, exist_ok=True)
    return path


def _legacy_state_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "LinkFetch", _STATE_FILE)


def _state_path() -> str:
    return os.path.join(config_dir(), _STATE_FILE)


def _migrate_from_appdata() -> None:
    """One-time move from %APPDATA%\\LinkFetch\\license.json if present."""
    new_path = _state_path()
    if os.path.isfile(new_path):
        return
    old_path = _legacy_state_path()
    if not os.path.isfile(old_path):
        return
    try:
        with open(old_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _save(data)
        try:
            os.remove(old_path)
        except OSError:
            pass
    except Exception:
        pass


def _load() -> dict[str, Any]:
    _migrate_from_appdata()
    path = _state_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_first_run() -> dict[str, Any]:
    data = _load()
    if "first_run_at" not in data:
        data["first_run_at"] = int(time.time())
        _save(data)
    return data


def normalize_key(key: str) -> str:
    k = (key or "").strip().upper().replace(" ", "")
    k = k.replace("—", "-").replace("–", "-")
    return k


def _checksum(body16: str) -> str:
    digest = hmac.new(
        _LICENSE_SECRET,
        body16.encode("ascii"),
        hashlib.sha256,
    ).hexdigest().upper()
    return digest[:8]


def verify_key_format(key: str) -> bool:
    k = normalize_key(key)
    if not _KEY_RE.match(k):
        return False
    compact = k.replace("LF1-", "").replace("-", "")
    if len(compact) != 16:
        return False
    body, sig = compact[:8], compact[8:]
    return hmac.compare_digest(_checksum(body), sig)


def generate_key() -> str:
    """Create one valid one-time license key (for seller tooling)."""
    import secrets

    body = secrets.token_hex(4).upper()  # 8 hex chars
    sig = _checksum(body)
    compact = body + sig
    groups = [compact[i : i + 4] for i in range(0, 16, 4)]
    return "LF1-" + "-".join(groups)


def is_licensed() -> bool:
    data = ensure_first_run()
    if not data.get("activated"):
        return False
    key = normalize_key(str(data.get("license_key") or ""))
    return bool(key) and verify_key_format(key)


def trial_seconds_left() -> int:
    data = ensure_first_run()
    if is_licensed():
        return 0
    started = int(data.get("first_run_at") or time.time())
    elapsed = max(0, int(time.time()) - started)
    return max(0, TRIAL_SECONDS - elapsed)


def format_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def trial_hms_left() -> str:
    return format_hms(trial_seconds_left())


def is_trial_active() -> bool:
    return (not is_licensed()) and trial_seconds_left() > 0


def has_pro_access() -> bool:
    """Full features: licensed buyout OR still in trial."""
    return is_licensed() or is_trial_active()


def activate(key: str) -> tuple[bool, str]:
    k = normalize_key(key)
    if not verify_key_format(k):
        return False, "激活码无效，请检查是否输入完整（LF1-xxxx-xxxx-xxxx-xxxx）。"
    data = ensure_first_run()
    data["activated"] = True
    data["license_key"] = k
    data["activated_at"] = int(time.time())
    _save(data)
    return True, "激活成功：已解锁全部功能（一次性买断）。"


def status_label() -> str:
    if is_licensed():
        return "已买断激活"
    left = trial_seconds_left()
    if left > 0:
        return f"试用 {trial_hms_left()}"
    return "免费版·仅单链接"


def _trial_duration_label() -> str:
    return format_hms(TRIAL_SECONDS)


def status_detail() -> str:
    if is_licensed():
        return "许可证有效：单链接 / 图文 / 合集主页 / 扫码登录均已解锁。"
    if is_trial_active():
        return (
            f"试用期剩余 {trial_hms_left()}（共 {_trial_duration_label()}）。\n"
            "试用期内可使用全部功能；到期后仅保留「单链接」。"
        )
    return (
        "试用已结束。\n"
        "免费版仅可使用「单链接」下载。\n"
        "购买激活码后可永久解锁图文、合集主页、扫码登录。"
    )


def require_pro_message() -> str:
    return (
        "该功能需要买断版或试用期内可用。\n\n"
        f"{status_detail()}\n\n"
        "请点击侧边栏「激活」输入激活码，或继续使用「单链接」。"
    )
