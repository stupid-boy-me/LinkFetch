"""Runtime dependency status (bundled vs system)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DepStatus:
    name: str
    ok: bool
    detail: str
    bundled: bool  # True = expected inside app / venv


def check_all() -> list[DepStatus]:
    out: list[DepStatus] = []

    # Python packages (always expected after pip / inside exe)
    for label, mod in (
        ("yt-dlp", "yt_dlp"),
        ("f2", "f2"),
        ("playwright", "playwright"),
        ("httpx", "httpx"),
        ("imageio-ffmpeg", "imageio_ffmpeg"),
        ("tkinterdnd2", "tkinterdnd2"),
        ("browser-cookie3", "browser_cookie3"),
        ("mutagen", "mutagen"),
        ("brotli", "brotli"),
        ("curl_cffi", "curl_cffi"),
    ):
        try:
            __import__(mod)
            out.append(DepStatus(label, True, "已加载", True))
        except Exception as e:
            out.append(DepStatus(label, False, str(e), True))

    from linkfetch.ffmpeg_util import get_ffmpeg_path

    ff = get_ffmpeg_path()
    out.append(
        DepStatus(
            "ffmpeg",
            bool(ff),
            ff or "未找到（合并音视频会失败）",
            True,
        )
    )

    # System Edge: used by Playwright channel=msedge (not shipped in exe)
    try:
        from linkfetch.edge_session import edge_available

        ok = edge_available()
        out.append(
            DepStatus(
                "Microsoft Edge",
                ok,
                "可用" if ok else "未检测到（抖音/小红书备用通道可能失败）",
                False,
            )
        )
    except Exception as e:
        out.append(DepStatus("Microsoft Edge", False, str(e), False))

    return out


def summary_text() -> str:
    lines = []
    for d in check_all():
        mark = "OK" if d.ok else "缺"
        kind = "内置" if d.bundled else "系统"
        lines.append(f"[{mark}][{kind}] {d.name}: {d.detail}")
    return "\n".join(lines)
