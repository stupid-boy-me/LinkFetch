"""Xiaohongshu channel: Edge session cookies + yt-dlp, media intercept fallback."""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional

import httpx
from yt_dlp import YoutubeDL

from linkfetch.http_download import download_url, safe_filename
from linkfetch.models import FormatOption, MediaInfo


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict[str, Any]], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


def resolve_xhs_url(url: str) -> str:
    """Follow redirects for xhslink short URLs."""
    u = (url or "").strip()
    low = u.lower()
    if "xhslink.com" not in low and "xhslink.cn" not in low:
        return u
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=20,
            headers={"User-Agent": _UA},
        ) as client:
            r = client.get(u)
            return str(r.url)
    except Exception:
        return u


def _ydl_opts(outdir: str, cookies_file: str = "") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": os.path.join(outdir, "%(title).180B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "retries": 5,
        "http_headers": {"User-Agent": _UA, "Referer": "https://www.xiaohongshu.com/"},
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    return opts


def _collect_formats(info: dict[str, Any]) -> list[FormatOption]:
    formats = info.get("formats") or []
    options: list[FormatOption] = []
    seen: set[int] = set()
    for f in sorted(formats, key=lambda x: int(x.get("height") or 0), reverse=True):
        h = int(f.get("height") or 0)
        url = f.get("url")
        if not url:
            continue
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        label = f"{h}p · mp4" if h else f.get("format_id") or "默认"
        options.append(
            FormatOption(
                format_id=str(f.get("format_id") or f"h{h}"),
                label=label,
                height=h or None,
                ext=f.get("ext") or "mp4",
                direct_url=url,
            )
        )
    if not options and info.get("url"):
        options.append(
            FormatOption(
                format_id="best",
                label="最佳画质",
                ext=info.get("ext") or "mp4",
                direct_url=info["url"],
            )
        )
    if options:
        options.insert(
            0,
            FormatOption(
                format_id="bv*+ba/b",
                label="最佳画质（自动）",
                ext="mp4",
                direct_url=options[0].direct_url,
            )
        )
    options.append(
        FormatOption(
            format_id="ba/b",
            label="仅音频（最佳）",
            is_audio_only=True,
            ext="m4a",
            direct_url=options[0].direct_url if options else None,
        )
    )
    return options


def ensure_xhs_cookies(
    cookies_file: str = "",
    log: Optional[LogCallback] = None,
) -> str:
    """
    Return a usable cookies.txt path.
    Prefer user file; otherwise warm an Edge guest session on explore.
    """
    log = log or (lambda _m: None)
    if cookies_file and os.path.isfile(cookies_file):
        return cookies_file

    from linkfetch.edge_session import collect_site_cookies

    _cookies, path = collect_site_cookies(
        "https://www.xiaohongshu.com/explore",
        wait_ms=6000,
        log=log,
    )
    return path


def extract_xhs(
    url: str,
    *,
    outdir: str,
    cookies_file: str = "",
    log: Optional[LogCallback] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> MediaInfo:
    log = log or (lambda _m: None)
    if cancel_flag and cancel_flag():
        raise KeyboardInterrupt("用户取消下载")

    url = resolve_xhs_url(url)
    log("小红书通道：准备 Cookie 会话…")
    cfile = ensure_xhs_cookies(cookies_file, log=log)

    # yt-dlp first
    try:
        log("小红书通道：yt-dlp 解析…")
        with YoutubeDL({**_ydl_opts(outdir, cfile), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if info and (info.get("formats") or info.get("url")):
            title = info.get("title") or "小红书笔记"
            formats = _collect_formats(info)
            log(f"小红书通道：yt-dlp 成功 · {len(formats)} 个格式")
            return MediaInfo(
                url=url,
                title=title,
                extractor="XiaoHongShu",
                thumbnail=(info.get("thumbnail") or ""),
                duration=info.get("duration"),
                formats=formats,
                raw={"ydl": info, "channel": "xhs", "cookies_file": cfile},
            )
    except Exception as e:
        log(f"小红书通道：yt-dlp 未成功，改用 Edge 拦截… ({e})")

    if cancel_flag and cancel_flag():
        raise KeyboardInterrupt("用户取消下载")

    from linkfetch.edge_session import intercept_media

    result = intercept_media(
        url,
        url_predicates=[
            lambda u: any(
                k in u
                for k in (
                    "sns-video",
                    "video.xhscdn",
                    "sns-bak",
                    "mime_type=video",
                )
            )
            or (".mp4" in u and "xhscdn" in u)
        ],
        wait_ms=12000,
        log=log,
    )
    media_urls = result.get("media_urls") or []
    # Prefer higher quality markers when present (_261 often 1080)
    media_urls = list(dict.fromkeys(media_urls))
    if not media_urls:
        # image note fallback: grab large images from page via simple httpx not available;
        # raise with guidance
        raise RuntimeError(
            "小红书未解析到视频流。若是图文笔记，请确认链接含视频；"
            "或导出已登录 cookies.txt 后重试。请尽量使用带 xsec_token 的完整链接。"
        )

    formats = [
        FormatOption(
            format_id=f"direct:{i}",
            label="最佳画质（Edge 拦截）" if i == 0 else f"媒体流 {i+1}",
            ext="mp4",
            direct_url=u,
        )
        for i, u in enumerate(media_urls[:6])
    ]
    title = (result.get("title") or "小红书视频").replace(" - 小红书", "").strip()
    # Prefer cookies from this session for later download
    session_cookies = result.get("cookies_path") or cfile
    return MediaInfo(
        url=url,
        title=title or "小红书视频",
        extractor="XiaoHongShu/Edge",
        formats=formats,
        raw={"media_urls": media_urls, "channel": "xhs", "cookies_file": session_cookies},
    )


def download_xhs(
    media: MediaInfo,
    format_id: str,
    outdir: str,
    *,
    audio_only: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
    log: Optional[LogCallback] = None,
) -> str:
    log = log or (lambda _m: None)
    os.makedirs(outdir, exist_ok=True)

    # Prefer direct_url on selected format
    fmt: Optional[FormatOption] = None
    for f in media.formats:
        if f.format_id == format_id:
            fmt = f
            break
    if fmt is None and media.formats:
        fmt = media.formats[0]

    if fmt and fmt.direct_url and (
        format_id.startswith("direct:")
        or media.extractor.endswith("/Edge")
        or (fmt.direct_url and "xhscdn.com" in fmt.direct_url)
    ):
        ext = "m4a" if audio_only else (fmt.ext or "mp4")
        outpath = os.path.join(outdir, safe_filename(media.title) + f".{ext}")
        log(f"小红书通道：直链下载 → {os.path.basename(outpath)}")
        download_url(
            fmt.direct_url,
            outpath,
            headers={"Referer": "https://www.xiaohongshu.com/"},
            progress_cb=progress_cb,
            cancel_flag=cancel_flag,
        )
        log("小红书通道：下载完成")
        return outpath

    # yt-dlp download path
    cfile = (media.raw or {}).get("cookies_file") or ""
    opts = _ydl_opts(outdir, cfile)
    opts["format"] = "ba/b" if audio_only else (format_id or "bv*+ba/b")
    if audio_only:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }
        ]
    else:
        opts["merge_output_format"] = "mp4"

    def hook(d: dict[str, Any]) -> None:
        if cancel_flag and cancel_flag():
            raise KeyboardInterrupt("用户取消下载")
        if progress_cb:
            progress_cb(d)

    opts["progress_hooks"] = [hook]
    log("小红书通道：yt-dlp 下载…")
    with YoutubeDL(opts) as ydl:
        ydl.download([media.url])
    log("小红书通道：下载完成")
    return outdir
