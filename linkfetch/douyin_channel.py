"""Douyin download channel: f2 (signed API) + Edge intercept fallback."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Optional

from linkfetch.cookies_util import (
    cookies_to_header,
    parse_netscape_cookies,
    try_browser_cookie_header,
)
from linkfetch.http_download import download_url, safe_filename
from linkfetch.models import FormatOption, MediaInfo


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict[str, Any]], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


def _guest_cookie() -> str:
    from f2.apps.douyin.utils import TokenManager

    ttwid = TokenManager.gen_ttwid()
    try:
        ms = TokenManager.gen_real_msToken()
    except Exception:
        ms = TokenManager.gen_false_msToken()
    return f"ttwid={ttwid}; msToken={ms}"


def build_douyin_cookie(
    cookies_file: str = "",
    cookies_from_browser: str = "",
    auto: bool = True,
    log: Optional[LogCallback] = None,
) -> tuple[str, str]:
    """Return (cookie_header, label)."""
    log = log or (lambda _m: None)

    if cookies_file and os.path.isfile(cookies_file):
        parsed = parse_netscape_cookies(cookies_file, "douyin")
        if not parsed:
            parsed = parse_netscape_cookies(cookies_file)
        if parsed:
            header = cookies_to_header(parsed)
            if "ttwid=" not in header:
                header = _guest_cookie() + "; " + header
            return header, f"Cookie文件:{cookies_file}"

    browsers: list[str] = []
    if cookies_from_browser and cookies_from_browser not in ("", "无", "自动", "auto"):
        browsers = [cookies_from_browser]
    elif auto:
        browsers = ["firefox", "edge", "chrome", "brave"]

    for b in browsers:
        header = try_browser_cookie_header(b, "douyin.com")
        if header:
            if "ttwid=" not in header:
                header = _guest_cookie() + "; " + header
            log(f"抖音通道：使用浏览器 Cookie ({b})")
            return header, f"浏览器:{b}"

    log("抖音通道：使用访客 ttwid/msToken")
    return _guest_cookie(), "访客Token"


def _formats_from_aweme(aweme: dict[str, Any]) -> list[FormatOption]:
    options: list[FormatOption] = []
    video = aweme.get("video") or {}
    bit_rate = video.get("bit_rate") or []
    seen: set[str] = set()

    for i, item in enumerate(bit_rate):
        play = item.get("play_addr") or {}
        urls = play.get("url_list") or []
        if not urls:
            continue
        url = urls[0]
        if url in seen:
            continue
        seen.add(url)
        h = play.get("height") or item.get("height")
        gear = item.get("gear_name") or ""
        if h and gear:
            label = f"{h}p · {gear}"
        elif h:
            label = f"{h}p"
        else:
            label = gear or f"清晰度{i+1}"
        options.append(
            FormatOption(
                format_id=f"direct:{i}",
                label=label,
                height=int(h) if h else None,
                ext="mp4",
                direct_url=url,
            )
        )

    if not options:
        play = video.get("play_addr") or {}
        urls = play.get("url_list") or []
        if urls:
            options.append(
                FormatOption(
                    format_id="direct:0",
                    label="默认画质",
                    ext="mp4",
                    direct_url=urls[0],
                )
            )

    music = aweme.get("music") or {}
    mplay = ((music.get("play_url") or {}).get("url_list") or [None])[0]
    if mplay:
        options.append(
            FormatOption(
                format_id="direct:audio",
                label="仅音频（原声）",
                is_audio_only=True,
                ext="m4a",
                direct_url=mplay,
            )
        )
    return options


def _media_from_aweme(url: str, aweme: dict[str, Any], extractor: str) -> MediaInfo:
    desc = (aweme.get("desc") or "").strip() or "抖音视频"
    author = ((aweme.get("author") or {}).get("nickname") or "").strip()
    title = desc if not author else f"{desc} - {author}"
    duration = None
    video = aweme.get("video") or {}
    if video.get("duration"):
        d = video.get("duration")
        try:
            duration = float(d) / 1000.0 if float(d) > 1000 else float(d)
        except Exception:
            duration = None
    cover = ""
    for key in ("origin_cover", "cover", "dynamic_cover"):
        c = video.get(key) or {}
        ul = c.get("url_list") or []
        if ul:
            cover = ul[0]
            break
    return MediaInfo(
        url=url,
        title=title,
        extractor=extractor,
        thumbnail=cover,
        duration=duration,
        formats=_formats_from_aweme(aweme),
        raw={"aweme": aweme, "channel": "douyin"},
    )


async def _f2_fetch(aweme_id: str, cookie: str) -> dict[str, Any]:
    from f2.apps.douyin.crawler import DouyinCrawler
    from f2.apps.douyin.model import PostDetail
    from f2.log.logger import logger

    logger.setLevel("ERROR")
    kwargs = {
        "headers": {"User-Agent": _UA, "Referer": "https://www.douyin.com/"},
        "proxies": {"http://": None, "https://": None},
        "cookie": cookie,
    }
    async with DouyinCrawler(kwargs) as crawler:
        return await crawler.fetch_post_detail(PostDetail(aweme_id=aweme_id))


async def _f2_aweme_id(url: str) -> str:
    from f2.apps.douyin.utils import AwemeIdFetcher

    return await AwemeIdFetcher.get_aweme_id(url)


def _edge_predicates():
    return [
        lambda u: any(
            x in u
            for x in (
                "/video/tos/",
                "bytevod",
                "douyinvod",
                "mime_type=video",
                "aweme/v1/play",
            )
        )
        and "douyin-pc-web" not in u
        and "uuu_" not in u
    ]


def extract_douyin(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    auto_cookies: bool = True,
    log: Optional[LogCallback] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> MediaInfo:
    log = log or (lambda _m: None)
    if cancel_flag and cancel_flag():
        raise KeyboardInterrupt("用户取消下载")

    cookie, label = build_douyin_cookie(
        cookies_file, cookies_from_browser, auto_cookies, log
    )
    log(f"抖音通道：解析中（{label}）…")

    aweme_id = ""
    try:
        aweme_id = asyncio.run(_f2_aweme_id(url))
        log(f"抖音通道：aweme_id={aweme_id}")
        resp = asyncio.run(_f2_fetch(aweme_id, cookie))
        aweme = resp.get("aweme_detail")
        if isinstance(aweme, dict) and (aweme.get("video") or aweme.get("images")):
            info = _media_from_aweme(url, aweme, "Douyin/f2")
            if info.formats:
                log(f"抖音通道：f2 解析成功 · {len(info.formats)} 个清晰度")
                return info
        reason = (resp.get("filter_detail") or {}).get("filter_reason") or "无详情"
        log(f"抖音通道：f2 未返回可下载内容（{reason}），尝试 Edge 拦截…")
    except Exception as e:
        log(f"抖音通道：f2 失败，尝试 Edge 拦截… ({e})")

    if cancel_flag and cancel_flag():
        raise KeyboardInterrupt("用户取消下载")

    from linkfetch.edge_session import intercept_media

    open_url = url
    if aweme_id:
        open_url = f"https://www.douyin.com/video/{aweme_id}"
    elif "v.douyin.com" in url:
        try:
            aweme_id = asyncio.run(_f2_aweme_id(url))
            open_url = f"https://www.douyin.com/video/{aweme_id}"
        except Exception:
            open_url = url

    result = intercept_media(
        open_url,
        url_predicates=_edge_predicates(),
        wait_ms=12000,
        log=log,
    )

    aweme = result.get("aweme")
    if isinstance(aweme, dict):
        info = _media_from_aweme(url, aweme, "Douyin/Edge")
        if info.formats:
            log(f"抖音通道：Edge 解析成功 · {len(info.formats)} 个清晰度")
            return info

    media_urls = result.get("media_urls") or []
    preferred = [
        u
        for u in media_urls
        if "mime_type=video_mp4" in u or ("media-video" not in u and ".mp4" in u)
    ]
    preferred = preferred or [u for u in media_urls if "media-video" in u]
    preferred = preferred or media_urls
    if preferred:
        formats = [
            FormatOption(
                format_id=f"direct:{i}",
                label="最佳画质（Edge 拦截）" if i == 0 else f"媒体流 {i+1}",
                ext="mp4",
                direct_url=u,
            )
            for i, u in enumerate(preferred[:6])
        ]
        title = (result.get("title") or "抖音视频").split(" - 抖音")[0].strip()
        return MediaInfo(
            url=url,
            title=title or "抖音视频",
            extractor="Douyin/Edge",
            formats=formats,
            raw={"media_urls": media_urls, "channel": "douyin"},
        )

    raise RuntimeError(
        "抖音解析失败。请确认链接可在浏览器打开；"
        "若仍失败，请导出已登录抖音的 cookies.txt 后重试。"
    )


def download_douyin(
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
    fmt: Optional[FormatOption] = None
    for f in media.formats:
        if f.format_id == format_id:
            fmt = f
            break
    if audio_only:
        for f in media.formats:
            if f.is_audio_only and f.direct_url:
                fmt = f
                break
    if fmt is None:
        for f in media.formats:
            if f.direct_url and not f.is_audio_only:
                fmt = f
                break
    if fmt is None or not fmt.direct_url:
        raise RuntimeError("没有可用的抖音直链，请重新解析")

    ext = "m4a" if (audio_only or fmt.is_audio_only) else (fmt.ext or "mp4")
    filename = safe_filename(media.title) + f".{ext}"
    outpath = os.path.join(outdir, filename)
    log(f"抖音通道：开始下载 → {filename}")
    download_url(
        fmt.direct_url,
        outpath,
        headers={"Referer": "https://www.douyin.com/"},
        progress_cb=progress_cb,
        cancel_flag=cancel_flag,
    )
    log("抖音通道：下载完成")
    return outpath
