"""yt-dlp wrapper + Douyin/XHS dedicated channels."""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional

from yt_dlp import YoutubeDL

from linkfetch.models import FormatOption, MediaInfo
from linkfetch.platforms import detect_platform
from linkfetch.ffmpeg_util import apply_ffmpeg_opts


ProgressCallback = Callable[[dict[str, Any]], None]
LogCallback = Callable[[str], None]

# Re-export for existing imports
__all__ = [
    "Downloader",
    "FormatOption",
    "MediaInfo",
    "find_default_cookies_files",
    "is_cookie_related_error",
    "looks_like_url",
    "extract_share_url",
    "resolve_cookie_attempts",
]


def _human_size(n: Optional[int]) -> str:
    if not n:
        return ""
    units = ["B", "KB", "MB", "GB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f}{u}"
        size /= 1024
    return ""


def _base_opts(
    outdir: str,
    cookies_from_browser: str = "",
    cookies_file: str = "",
    proxy: str = "",
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "noplaylist": False,
        "outtmpl": os.path.join(outdir, "%(title).180B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "windowsfilenames": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        # Help Chinese sites / mixed environments
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        },
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser:
        # e.g. "chrome", "edge", "firefox"
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if proxy:
        opts["proxy"] = proxy
    return apply_ffmpeg_opts(opts)


def find_default_cookies_files() -> list[str]:
    """Common places users drop exported cookies.txt."""
    home = os.path.expanduser("~")
    here = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    candidates = [
        os.path.join(here, "cookies.txt"),
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(home, "Downloads", "cookies.txt"),
        os.path.join(home, "Downloads", "LinkFetch", "cookies.txt"),
        os.path.join(home, "cookies.txt"),
    ]
    return [p for p in candidates if os.path.isfile(p)]


def is_cookie_related_error(err: BaseException) -> bool:
    text = str(err).lower()
    keys = (
        "dpapi",
        "decrypt",
        "cookie",
        "cookies",
        "permission denied",
        "could not copy",
        "10927",
        "7271",
    )
    return any(k in text for k in keys)


def resolve_cookie_attempts(
    cookies_file: str = "",
    cookies_from_browser: str = "",
    auto: bool = False,
) -> list[tuple[str, str, str]]:
    """
    Returns list of (label, cookies_file, cookies_from_browser).
    When auto=True, try file -> firefox -> edge -> chrome -> none.
    """
    attempts: list[tuple[str, str, str]] = []

    if cookies_file and os.path.isfile(cookies_file):
        attempts.append((f"Cookie文件:{cookies_file}", cookies_file, ""))
    elif auto:
        for p in find_default_cookies_files():
            attempts.append((f"自动发现Cookie文件:{p}", p, ""))

    if cookies_from_browser and cookies_from_browser not in ("", "无", "自动", "auto"):
        attempts.append((f"浏览器:{cookies_from_browser}", "", cookies_from_browser))
    elif auto:
        for b in ("firefox", "edge", "chrome", "brave"):
            attempts.append((f"浏览器:{b}", "", b))

    # Always end with no-cookie fallback
    attempts.append(("无Cookie", "", ""))

    # Deduplicate while preserving order
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str, str]] = []
    for label, f, b in attempts:
        key = (f, b)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((label, f, b))
    return uniq


def _collect_formats(info: dict[str, Any]) -> list[FormatOption]:
    formats = info.get("formats") or []
    options: list[FormatOption] = []
    seen: set[str] = set()

    # Best merged progressive-ish choices first
    video_candidates: list[dict[str, Any]] = []
    audio_candidates: list[dict[str, Any]] = []

    for f in formats:
        fid = str(f.get("format_id", ""))
        if not fid:
            continue
        vcodec = (f.get("vcodec") or "none").lower()
        acodec = (f.get("acodec") or "none").lower()
        height = f.get("height")
        ext = f.get("ext") or ""
        filesize = f.get("filesize") or f.get("filesize_approx")

        if vcodec != "none" and acodec != "none":
            video_candidates.append(f)
        elif vcodec != "none":
            video_candidates.append(f)
        elif acodec != "none":
            audio_candidates.append(f)

    # Prefer unique heights for video
    by_height: dict[int, dict[str, Any]] = {}
    for f in video_candidates:
        h = int(f.get("height") or 0)
        if h <= 0:
            continue
        prev = by_height.get(h)
        # Prefer mp4 / has audio / larger filesize
        score = 0
        if (f.get("ext") or "") == "mp4":
            score += 3
        if (f.get("acodec") or "none") != "none":
            score += 2
        score += 1 if (f.get("filesize") or 0) else 0
        if prev is None:
            by_height[h] = f
            continue
        pscore = 0
        if (prev.get("ext") or "") == "mp4":
            pscore += 3
        if (prev.get("acodec") or "none") != "none":
            pscore += 2
        if score >= pscore:
            by_height[h] = f

    for h in sorted(by_height.keys(), reverse=True):
        f = by_height[h]
        fid = str(f["format_id"])
        acodec = (f.get("acodec") or "none").lower()
        # If video-only, ask yt-dlp to merge best audio
        fmt = fid if acodec != "none" else f"{fid}+bestaudio/best"
        label = f"{h}p"
        ext = f.get("ext") or "mp4"
        size = _human_size(f.get("filesize") or f.get("filesize_approx"))
        if size:
            label = f"{label} · {ext} · {size}"
        else:
            label = f"{label} · {ext}"
        if fmt not in seen:
            seen.add(fmt)
            options.append(
                FormatOption(
                    format_id=fmt,
                    label=label,
                    height=h,
                    ext=ext,
                    vcodec=str(f.get("vcodec") or ""),
                    acodec=str(f.get("acodec") or ""),
                    filesize=f.get("filesize") or f.get("filesize_approx"),
                    is_audio_only=False,
                )
            )

    # Always offer best
    if "bv*+ba/b" not in seen:
        options.insert(
            0,
            FormatOption(
                format_id="bv*+ba/b",
                label="最佳画质（自动合并音视频）",
                height=None,
                ext="mp4",
                is_audio_only=False,
            ),
        )

    # Audio-only
    options.append(
        FormatOption(
            format_id="ba/b",
            label="仅音频（最佳）",
            is_audio_only=True,
            ext="m4a",
        )
    )
    # Dedup common audio heights not needed
    return options


def _subtitle_langs(info: dict[str, Any]) -> list[str]:
    langs: set[str] = set()
    for key in ("subtitles", "automatic_captions"):
        subs = info.get(key) or {}
        for lang in subs.keys():
            langs.add(lang)
    # Prefer common first
    preferred = ["zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh", "en", "en-US"]
    ordered = [p for p in preferred if p in langs]
    ordered += sorted(l for l in langs if l not in ordered)
    return ordered


class Downloader:
    def __init__(
        self,
        outdir: str,
        cookies_from_browser: str = "",
        cookies_file: str = "",
        proxy: str = "",
        auto_cookies: bool = True,
        log_cb: Optional[LogCallback] = None,
    ) -> None:
        self.outdir = outdir
        self.cookies_from_browser = cookies_from_browser
        self.cookies_file = cookies_file
        self.proxy = proxy
        self.auto_cookies = auto_cookies
        self.log_cb = log_cb or (lambda _m: None)
        self._cancel = False
        self.active_cookie_label = "无Cookie"

    def cancel(self) -> None:
        self._cancel = True

    def reset_cancel(self) -> None:
        self._cancel = False

    def _apply_cookie(self, cookies_file: str, cookies_from_browser: str) -> None:
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser

    def _ydl(
        self,
        extra: Optional[dict[str, Any]] = None,
        cookies_file: str = "",
        cookies_from_browser: str = "",
    ) -> YoutubeDL:
        opts = _base_opts(
            self.outdir,
            cookies_from_browser,
            cookies_file,
            self.proxy,
        )
        if extra:
            opts.update(extra)

        def hook(d: dict[str, Any]) -> None:
            if self._cancel:
                raise KeyboardInterrupt("用户取消下载")

        # Keep existing progress hooks if provided by caller via extra
        if "progress_hooks" not in opts or opts["progress_hooks"] is None:
            opts["progress_hooks"] = [hook]
        else:
            hooks = list(opts["progress_hooks"])
            hooks.insert(0, hook)
            opts["progress_hooks"] = hooks
        return YoutubeDL(opts)

    def _attempts(self) -> list[tuple[str, str, str]]:
        return resolve_cookie_attempts(
            cookies_file=self.cookies_file,
            cookies_from_browser=self.cookies_from_browser,
            auto=self.auto_cookies,
        )

    def _run_with_cookie_fallback(self, action_name: str, fn: Callable[..., Any]) -> Any:
        last_err: Optional[BaseException] = None
        attempts = self._attempts()
        for label, cfile, cbrowser in attempts:
            if self._cancel:
                raise KeyboardInterrupt("用户取消下载")
            try:
                self.log_cb(f"{action_name}：尝试 {label}")
                result = fn(cfile, cbrowser)
                self.active_cookie_label = label
                self._apply_cookie(cfile, cbrowser)
                if label != "无Cookie":
                    self.log_cb(f"{action_name}：已使用 {label}")
                return result
            except KeyboardInterrupt:
                raise
            except Exception as e:
                last_err = e
                if is_cookie_related_error(e) and label != attempts[-1][0]:
                    self.log_cb(f"{action_name}：{label} 失败，自动切换… ({e})")
                    continue
                # Non-cookie error on a cookie attempt: still try next if auto,
                # because some extractors fail oddly without valid cookies.
                if self.auto_cookies and label != attempts[-1][0]:
                    self.log_cb(f"{action_name}：{label} 未成功，继续尝试… ({e})")
                    continue
                raise
        assert last_err is not None
        raise last_err

    def extract(self, url: str, process_playlist: bool = True) -> MediaInfo:
        self.reset_cancel()
        url = url.strip()
        if not url:
            raise ValueError("链接为空")

        platform = detect_platform(url)
        if platform == "douyin":
            from linkfetch.douyin_channel import extract_douyin

            return extract_douyin(
                url,
                cookies_file=self.cookies_file,
                cookies_from_browser=self.cookies_from_browser,
                auto_cookies=self.auto_cookies,
                log=self.log_cb,
                cancel_flag=lambda: self._cancel,
            )
        if platform == "xhs":
            from linkfetch.xhs_channel import extract_xhs

            return extract_xhs(
                url,
                outdir=self.outdir,
                cookies_file=self.cookies_file,
                log=self.log_cb,
                cancel_flag=lambda: self._cancel,
            )

        def _once(cfile: str, cbrowser: str) -> MediaInfo:
            extra = {
                "skip_download": True,
                "extract_flat": "in_playlist" if process_playlist else False,
            }
            with self._ydl(extra, cfile, cbrowser) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                raise RuntimeError("无法解析该链接，请检查网址或登录 Cookie")

            # Playlist
            if info.get("_type") == "playlist" or (
                info.get("entries") and not info.get("formats")
            ):
                entries = [e for e in (info.get("entries") or []) if e]
                return MediaInfo(
                    url=url,
                    title=info.get("title") or "播放列表",
                    extractor=str(info.get("extractor") or info.get("ie_key") or ""),
                    thumbnail=info.get("thumbnail") or "",
                    is_playlist=True,
                    playlist_count=len(entries),
                    entries=entries,
                    formats=[
                        FormatOption("bv*+ba/b", "最佳画质（自动合并音视频）"),
                        FormatOption("ba/b", "仅音频（最佳）", is_audio_only=True, ext="m4a"),
                    ],
                    subtitles=[],
                    raw=info,
                )

            # Single video: may need full extract if flat
            if not info.get("formats"):
                with self._ydl(
                    {"skip_download": True, "noplaylist": True}, cfile, cbrowser
                ) as ydl:
                    info = ydl.extract_info(url, download=False) or info

            return MediaInfo(
                url=url,
                title=info.get("title") or "未命名",
                extractor=str(info.get("extractor") or ""),
                thumbnail=info.get("thumbnail") or "",
                duration=info.get("duration"),
                is_playlist=False,
                formats=_collect_formats(info),
                subtitles=_subtitle_langs(info),
                raw=info,
            )

        return self._run_with_cookie_fallback("解析", _once)

    def download(
        self,
        url: str,
        format_id: str,
        *,
        audio_only: bool = False,
        write_subs: bool = False,
        sub_langs: Optional[list[str]] = None,
        playlist: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        media: Optional[MediaInfo] = None,
    ) -> None:
        self.reset_cancel()
        os.makedirs(self.outdir, exist_ok=True)

        platform = detect_platform(url)
        if platform == "douyin":
            from linkfetch.douyin_channel import download_douyin, extract_douyin

            info = media
            if info is None or (info.raw or {}).get("channel") != "douyin":
                info = extract_douyin(
                    url,
                    cookies_file=self.cookies_file,
                    cookies_from_browser=self.cookies_from_browser,
                    auto_cookies=self.auto_cookies,
                    log=self.log_cb,
                    cancel_flag=lambda: self._cancel,
                )
            download_douyin(
                info,
                format_id,
                self.outdir,
                audio_only=audio_only,
                progress_cb=progress_cb,
                cancel_flag=lambda: self._cancel,
                log=self.log_cb,
            )
            return

        if platform == "xhs":
            from linkfetch.xhs_channel import download_xhs, extract_xhs

            info = media
            if info is None or (info.raw or {}).get("channel") != "xhs":
                info = extract_xhs(
                    url,
                    outdir=self.outdir,
                    cookies_file=self.cookies_file,
                    log=self.log_cb,
                    cancel_flag=lambda: self._cancel,
                )
            download_xhs(
                info,
                format_id,
                self.outdir,
                audio_only=audio_only,
                progress_cb=progress_cb,
                cancel_flag=lambda: self._cancel,
                log=self.log_cb,
            )
            return

        def _once(cfile: str, cbrowser: str) -> None:
            extra: dict[str, Any] = {
                "format": format_id,
                "noplaylist": not playlist,
                "progress_hooks": [],
            }

            if audio_only or format_id.startswith("ba"):
                extra["format"] = format_id if format_id else "ba/b"
                extra["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                        "preferredquality": "0",
                    }
                ]
            else:
                extra["merge_output_format"] = "mp4"

            if write_subs:
                extra["writesubtitles"] = True
                extra["writeautomaticsub"] = True
                extra["subtitleslangs"] = sub_langs or ["zh-Hans", "zh-CN", "zh", "en"]
                extra["subtitlesformat"] = "srt/best"

            def hook(d: dict[str, Any]) -> None:
                if self._cancel:
                    raise KeyboardInterrupt("用户取消下载")
                if progress_cb:
                    progress_cb(d)

            extra["progress_hooks"] = [hook]
            self.log_cb(f"开始下载: {url}")
            with self._ydl(extra, cfile, cbrowser) as ydl:
                ydl.download([url])
            self.log_cb("下载完成")

        # If parse already found a working cookie, try it first by pinning.
        self._run_with_cookie_fallback("下载", _once)


def looks_like_url(text: str) -> bool:
    from linkfetch.platforms import looks_like_url as _looks

    return _looks(text)


def extract_share_url(text: str) -> str:
    from linkfetch.platforms import extract_share_url as _extract

    return _extract(text)
