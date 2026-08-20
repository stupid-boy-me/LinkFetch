"""Locate bundled ffmpeg for yt-dlp (works in source + PyInstaller)."""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def get_ffmpeg_path() -> str:
    """
    Prefer imageio-ffmpeg bundled binary, then PATH, then empty.
    Returns absolute path to ffmpeg executable or "".
    """
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass

    # PyInstaller: look next to unpacked binaries
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for root, _dirs, files in os.walk(meipass):
            for name in files:
                if name.lower().startswith("ffmpeg") and name.lower().endswith(".exe"):
                    return os.path.join(root, name)

    which = shutil.which("ffmpeg")
    return which or ""


def apply_ffmpeg_opts(opts: dict) -> dict:
    """Inject ffmpeg_location into yt-dlp options when available."""
    path = get_ffmpeg_path()
    if path:
        opts["ffmpeg_location"] = path
    return opts
