"""Batch / playlist / user-space listing for selectable downloads."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yt_dlp import YoutubeDL

from linkfetch.platforms import detect_platform, is_bilibili_url, is_douyin_url
from linkfetch.ffmpeg_util import apply_ffmpeg_opts


LogCallback = Callable[[str], None]


@dataclass
class BatchItem:
    index: int
    title: str
    url: str
    selected: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchList:
    source_url: str
    title: str
    platform: str
    items: list[BatchItem] = field(default_factory=list)


def _entry_url(entry: dict[str, Any], fallback_ie: str = "") -> str:
    u = entry.get("url") or entry.get("webpage_url") or ""
    if u.startswith("http"):
        return u
    eid = entry.get("id") or ""
    ie = (entry.get("ie_key") or entry.get("extractor_key") or fallback_ie or "").lower()
    if "bili" in ie and eid:
        return f"https://www.bilibili.com/video/{eid}"
    if "douyin" in ie and eid:
        return f"https://www.douyin.com/video/{eid}"
    return u


def extract_batch_list(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    max_items: int = 80,
    log: Optional[LogCallback] = None,
) -> BatchList:
    """
    Flat-extract playlist / space / collection entries.
    Works best for Bilibili; Douyin depends on yt-dlp availability.
    """
    log = log or (lambda _m: None)
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": max_items,
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser and cookies_from_browser not in ("", "无", "自动", "auto"):
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    apply_ffmpeg_opts(opts)

    log("合集/主页：正在拉取列表…")
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("无法解析该合集/主页链接")

    entries = [e for e in (info.get("entries") or []) if e]
    # Some pages return a single video without entries
    if not entries and info.get("id"):
        entries = [info]

    if not entries:
        raise RuntimeError(
            "未解析到可勾选条目。\n"
            "请确认是 B站合集/收藏/空间视频列表，或抖音可被识别的列表页。\n"
            "单条视频请切换到「单链接」模式。"
        )

    platform = detect_platform(url)
    if platform == "generic":
        if is_bilibili_url(url):
            platform = "bilibili"
        elif is_douyin_url(url):
            platform = "douyin"

    items: list[BatchItem] = []
    for i, e in enumerate(entries[:max_items]):
        title = (e.get("title") or e.get("id") or f"条目{i+1}").strip()
        link = _entry_url(e, str(info.get("extractor") or ""))
        if not link:
            continue
        items.append(BatchItem(index=i, title=title, url=link, selected=True, extra=dict(e)))

    if not items:
        raise RuntimeError("列表为空或条目缺少有效链接")

    title = info.get("title") or "合集/主页"
    log(f"合集/主页：共 {len(items)} 条，可勾选下载")
    return BatchList(source_url=url, title=title, platform=platform, items=items)
