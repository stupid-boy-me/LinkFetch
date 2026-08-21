"""Track and delete managed temp cookie files written by Edge sessions."""

from __future__ import annotations

import atexit
import os
import threading
from typing import Iterable

_lock = threading.Lock()
_paths: set[str] = set()


def is_managed_temp_cookie(path: str) -> bool:
    if not path:
        return False
    name = os.path.basename(path)
    return name.startswith("linkfetch_cookies_") and name.endswith(".txt")


def register_temp_cookie(path: str) -> str:
    if path and is_managed_temp_cookie(path):
        with _lock:
            _paths.add(path)
    return path


def cleanup_cookie_file(path: str) -> None:
    """Delete one managed temp cookie file; never touch user-exported cookies."""
    if not path or not is_managed_temp_cookie(path):
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    with _lock:
        _paths.discard(path)


def cleanup_all_temp_cookies(extra: Iterable[str] | None = None) -> None:
    candidates: set[str]
    with _lock:
        candidates = set(_paths)
        _paths.clear()
    if extra:
        candidates.update(p for p in extra if p)
    for p in candidates:
        if not is_managed_temp_cookie(p):
            continue
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


atexit.register(cleanup_all_temp_cookies)
