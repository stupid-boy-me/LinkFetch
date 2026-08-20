"""Direct HTTP download with progress (for media CDN URLs)."""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional

import httpx


ProgressCallback = Callable[[dict[str, Any]], None]
LogCallback = Callable[[str], None]


def safe_filename(name: str, fallback: str = "download") -> str:
    name = (name or fallback).strip() or fallback
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.rstrip(" .")
    return name[:180] or fallback


def download_url(
    url: str,
    outpath: str,
    *,
    headers: Optional[dict[str, str]] = None,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
    timeout: float = 120.0,
) -> str:
    """Stream download url to outpath. Returns final path."""
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)
    hdrs = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
        ),
        **(headers or {}),
    }
    with httpx.stream("GET", url, headers=hdrs, follow_redirects=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(outpath, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=256 * 1024):
                if cancel_flag and cancel_flag():
                    raise KeyboardInterrupt("用户取消下载")
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(
                        {
                            "status": "downloading",
                            "downloaded_bytes": done,
                            "total_bytes": total or None,
                            "filename": outpath,
                        }
                    )
    if progress_cb:
        progress_cb({"status": "finished", "filename": outpath})
    return outpath
