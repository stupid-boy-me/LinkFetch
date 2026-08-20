"""Platform detection and share-text URL extraction."""

from __future__ import annotations

import re
from urllib.parse import urlparse


# Prefer these hosts when multiple URLs appear in share text
_PRIORITY_HOST_PARTS = (
    "v.douyin.com",
    "douyin.com",
    "iesdouyin.com",
    "xhslink.com",
    "xhslink.cn",
    "xiaohongshu.com",
    "bilibili.com",
    "b23.tv",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "weibo.com",
    "instagram.com",
)

_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'）】\]}，。；、！？]+",
    re.IGNORECASE,
)

# Bare short links without scheme, e.g. xhslink.cn/o/xxx  v.douyin.com/xxx/
_BARE_HOST_RE = re.compile(
    r"(?<![\w./-])("
    r"(?:v\.)?douyin\.com/[^\s<>\"'）】\]}，。；、！？]+"
    r"|xhslink\.(?:com|cn)/[^\s<>\"'）】\]}，。；、！？]+"
    r"|www\.xiaohongshu\.com/[^\s<>\"'）】\]}，。；、！？]+"
    r"|b23\.tv/[^\s<>\"'）】\]}，。；、！？]+"
    r"|www\.bilibili\.com/[^\s<>\"'）】\]}，。；、！？]+"
    r")",
    re.IGNORECASE,
)


def normalize_url(url: str) -> str:
    return (url or "").strip()


def _clean_url_candidate(raw: str) -> str:
    u = (raw or "").strip()
    # Strip common trailing punctuation from share text
    u = u.rstrip("，。；、！？,.!?;:）)」』】]}>\"'")
    # Some clients append Chinese/fullwidth junk
    u = re.sub(r"[^\w\-./:?#=&%~+@]+$", "", u)
    if u.lower().startswith("www."):
        u = "https://" + u
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^(?:[\w-]+\.)+[\w-]+/", u, re.I):
            u = "https://" + u
    return u.strip()


def _host_priority(url: str) -> int:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path
    full = f"{host}{path}".lower()
    for i, part in enumerate(_PRIORITY_HOST_PARTS):
        if part in host or part in full:
            return i
    return 1000


def extract_share_urls(text: str) -> list[str]:
    """Extract all candidate media URLs from arbitrary share / clipboard text."""
    text = text or ""
    found: list[str] = []
    seen: set[str] = set()

    for m in _URL_RE.finditer(text):
        u = _clean_url_candidate(m.group(0))
        if not u or u in seen:
            continue
        if not re.match(r"^https?://", u, re.I):
            continue
        seen.add(u)
        found.append(u)

    for m in _BARE_HOST_RE.finditer(text):
        u = _clean_url_candidate(m.group(1))
        if not u or u in seen:
            continue
        seen.add(u)
        found.append(u)

    found.sort(key=_host_priority)
    return found


def extract_share_url(text: str) -> str:
    """
    Pick the best media URL from share text.
    Returns empty string if none found.
    """
    urls = extract_share_urls(text)
    return urls[0] if urls else ""


def looks_like_url(text: str) -> bool:
    """True if text is a URL, or contains an extractable media URL."""
    t = (text or "").strip()
    if re.match(r"^https?://", t, re.I):
        return True
    return bool(extract_share_url(t))


def is_douyin_url(url: str) -> bool:
    u = normalize_url(url).lower()
    host = urlparse(u).netloc
    return any(
        x in host
        for x in (
            "douyin.com",
            "iesdouyin.com",
            "v.douyin.com",
            "amemv.com",
        )
    ) or "v.douyin.com" in u


def is_xhs_url(url: str) -> bool:
    u = normalize_url(url).lower()
    host = urlparse(u).netloc
    return any(
        x in host
        for x in (
            "xiaohongshu.com",
            "xhslink.com",
            "xhslink.cn",
            "xhscdn.com",
        )
    )


def is_bilibili_url(url: str) -> bool:
    u = normalize_url(url).lower()
    host = urlparse(u).netloc
    return "bilibili.com" in host or "b23.tv" in host


def detect_platform(url: str) -> str:
    if is_douyin_url(url):
        return "douyin"
    if is_xhs_url(url):
        return "xhs"
    return "generic"
