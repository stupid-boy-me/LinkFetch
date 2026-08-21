"""Batch / playlist / user-space listing for selectable downloads.

Supports:
- Bilibili: yt-dlp flat playlist (合集 / 空间 / 收藏等)
- Douyin: f2 用户主页作品 / collection 合集
- Xiaohongshu: Edge 滚动抓取用户主页笔记链接
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from linkfetch.ffmpeg_util import apply_ffmpeg_opts
from linkfetch.platforms import (
    detect_platform,
    is_bilibili_url,
    is_douyin_url,
    is_xhs_url,
)


LogCallback = Callable[[str], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


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


def _xhs_cover_url(note: dict[str, Any]) -> str:
    cover = note.get("cover") or {}
    if not isinstance(cover, dict):
        return ""
    for key in ("url_default", "url_pre", "url"):
        u = cover.get(key)
        if isinstance(u, str) and u.startswith("http"):
            return u.replace("http://", "https://", 1)
    for info in cover.get("info_list") or []:
        if isinstance(info, dict):
            u = info.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u.replace("http://", "https://", 1)
    return ""


def _xhs_interact(note: dict[str, Any]) -> dict[str, str]:
    info = note.get("interact_info") or {}
    if not isinstance(info, dict):
        info = {}
    def _s(key: str) -> str:
        v = info.get(key)
        if v is None:
            return "0"
        return str(v)

    return {
        "liked_count": _s("liked_count"),
        "collected_count": _s("collected_count"),
        "comment_count": _s("comment_count"),
        "share_count": _s("share_count"),
    }


def _xhs_time_label(note: dict[str, Any]) -> str:
    """Human-readable publish time from note payload."""
    from datetime import datetime

    raw = note.get("time") or note.get("last_update_time") or note.get("timestamp")
    if raw is None:
        return ""
    try:
        ts = int(raw)
        if ts > 10_000_000_000:  # ms
            ts //= 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(raw)[:16]


def _xhs_batch_item_from_note(note: dict[str, Any], index: int) -> Optional[BatchItem]:
    nid = str(note.get("note_id") or note.get("id") or "").strip()
    if not nid:
        return None
    link = _xhs_note_link(nid, str(note.get("xsec_token") or ""))
    if not link:
        return None
    title = (note.get("display_title") or note.get("title") or f"笔记 {nid}").strip()
    ntype = str(note.get("type") or "")
    interact = _xhs_interact(note)
    return BatchItem(
        index=index,
        title=title[:120],
        url=link,
        selected=True,
        extra={
            "note_id": nid,
            "type": ntype,
            "cover_url": _xhs_cover_url(note),
            "published_at": _xhs_time_label(note),
            "liked_count": interact["liked_count"],
            "collected_count": interact["collected_count"],
            "comment_count": interact["comment_count"],
            "share_count": interact["share_count"],
        },
    )


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
    if ("xhs" in ie or "xiaohongshu" in ie) and eid:
        return f"https://www.xiaohongshu.com/explore/{eid}"
    return u


def _extract_ydl_batch(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    max_items: int = 80,
    log: LogCallback,
) -> BatchList:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": max_items,
        "ignoreerrors": True,
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser and cookies_from_browser not in ("", "无", "自动", "auto"):
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    apply_ffmpeg_opts(opts)

    log("合集/主页：yt-dlp 拉取列表…")
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("无法解析该合集/主页链接")

    entries = [e for e in (info.get("entries") or []) if e]
    if not entries and info.get("id"):
        entries = [info]
    if not entries:
        raise RuntimeError("未解析到可勾选条目（yt-dlp）")

    platform = detect_platform(url)
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


def _douyin_cookie(
    cookies_file: str = "",
    cookies_from_browser: str = "",
    log: Optional[LogCallback] = None,
) -> str:
    from linkfetch.douyin_channel import build_douyin_cookie

    header, label = build_douyin_cookie(
        cookies_file,
        cookies_from_browser,
        auto=True,
        log=log,
    )
    if log:
        log(f"抖音合集：Cookie → {label}")
    return header


async def _extract_douyin_batch_async(
    url: str,
    *,
    cookie: str,
    max_items: int,
    log: LogCallback,
) -> BatchList:
    from f2.apps.douyin.handler import DouyinHandler
    from f2.apps.douyin.utils import MixIdFetcher, SecUserIdFetcher
    from f2.log.logger import logger

    logger.setLevel("ERROR")
    kwargs = {
        "headers": {"User-Agent": _UA, "Referer": "https://www.douyin.com/"},
        "proxies": {"http://": None, "https://": None},
        "cookie": cookie,
        "timeout": 1,
    }
    handler = DouyinHandler(kwargs)
    items: list[BatchItem] = []
    list_title = "抖音列表"

    is_mix = bool(re.search(r"/collection/|/mix/", url, re.I))
    if is_mix:
        log("抖音合集：识别为合集(collection/mix)…")
        mix_id = await MixIdFetcher.get_mix_id(url)
        list_title = f"抖音合集 {mix_id}"
        async for page in handler.fetch_user_mix_videos(mix_id, 0, 20, max_items):
            ids = page.aweme_id or []
            descs = page.desc or []
            if not isinstance(ids, list):
                ids = [ids] if ids else []
            if not isinstance(descs, list):
                descs = [descs] if descs else []
            for j, aid in enumerate(ids):
                if not aid or len(items) >= max_items:
                    continue
                title = str(descs[j] if j < len(descs) else "") or f"作品 {aid}"
                items.append(
                    BatchItem(
                        index=len(items),
                        title=title[:80],
                        url=f"https://www.douyin.com/video/{aid}",
                        selected=True,
                        extra={"aweme_id": str(aid)},
                    )
                )
            if len(items) >= max_items:
                break
    else:
        log("抖音合集：识别为用户主页，拉取作品列表…")
        sec = await SecUserIdFetcher.get_sec_user_id(url)
        list_title = f"抖音主页 {sec[:12]}…"
        try:
            profile = await handler.fetch_user_profile(sec)
            nick = getattr(profile, "nickname", None) or getattr(profile, "nickname_raw", None)
            if nick:
                list_title = f"抖音 · {nick}"
        except Exception:
            pass
        async for page in handler.fetch_user_post_videos(sec, 0, 0, 20, max_items):
            ids = page.aweme_id or []
            descs = page.desc or []
            if not isinstance(ids, list):
                ids = [ids] if ids else []
            if not isinstance(descs, list):
                descs = [descs] if descs else []
            for j, aid in enumerate(ids):
                if not aid or len(items) >= max_items:
                    continue
                title = str(descs[j] if j < len(descs) else "") or f"作品 {aid}"
                items.append(
                    BatchItem(
                        index=len(items),
                        title=title[:80],
                        url=f"https://www.douyin.com/video/{aid}",
                        selected=True,
                        extra={"aweme_id": str(aid)},
                    )
                )
            if len(items) >= max_items:
                break

    if not items:
        raise RuntimeError(
            "抖音未解析到作品列表。\n"
            "请使用用户主页链接（douyin.com/user/...）或合集链接（/collection/...），\n"
            "并尽量提供已登录 Cookie。"
        )
    log(f"抖音合集：共 {len(items)} 条")
    return BatchList(source_url=url, title=list_title, platform="douyin", items=items)


def _extract_douyin_batch(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    max_items: int = 80,
    log: LogCallback,
) -> BatchList:
    cookie = _douyin_cookie(cookies_file, cookies_from_browser, log=log)
    return asyncio.run(
        _extract_douyin_batch_async(url, cookie=cookie, max_items=max_items, log=log)
    )


def _xhs_note_link(note_id: str, xsec_token: str = "") -> str:
    nid = (note_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{24}", nid, re.I):
        return ""
    link = f"https://www.xiaohongshu.com/explore/{nid}"
    tok = (xsec_token or "").strip()
    if tok:
        from urllib.parse import quote

        link += f"?xsec_token={quote(tok, safe='')}&xsec_source=pc_user"
    return link


def _netscape_to_playwright_cookies(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, cpath, secure, expires, name, value = parts[:7]
            if "xiaohongshu" not in domain and "xhscdn" not in domain:
                continue
            try:
                exp = float(expires)
            except ValueError:
                exp = -1
            item: dict[str, Any] = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": cpath or "/",
                "secure": secure.upper() == "TRUE",
            }
            if exp > 0:
                item["expires"] = exp
            out.append(item)
    return out


def _browser_xhs_playwright_cookies(browser: str) -> list[dict[str, Any]]:
    try:
        import browser_cookie3
    except Exception:
        return []
    fn = {
        "firefox": getattr(browser_cookie3, "firefox", None),
        "chrome": getattr(browser_cookie3, "chrome", None),
        "edge": getattr(browser_cookie3, "edge", None),
        "brave": getattr(browser_cookie3, "brave", None),
    }.get((browser or "").lower())
    if not fn:
        return []
    try:
        jar = fn(domain_name="xiaohongshu.com")
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for c in jar:
        if not c.name:
            continue
        item: dict[str, Any] = {
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain or ".xiaohongshu.com",
            "path": c.path or "/",
            "secure": bool(getattr(c, "secure", False)),
        }
        exp = getattr(c, "expires", None)
        if exp:
            item["expires"] = float(exp)
        out.append(item)
    return out


def _extract_xhs_batch(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    max_items: int = 80,
    log: LogCallback,
) -> BatchList:
    """
    Xiaohongshu user home via persistent Edge profile (same as QR login).
    Plain cookie injection is not enough due to signed APIs (406).
    """
    from linkfetch.edge_session import (
        _launch_persistent_edge,
        edge_profile_dir,
        session_cookies_dir,
    )
    from linkfetch.xhs_channel import resolve_xhs_url

    url = resolve_xhs_url(url)
    # Cookie / profile live under download dir
    if cookies_file and os.path.isfile(cookies_file):
        base_dir = os.path.dirname(os.path.abspath(cookies_file))
    else:
        base_dir = session_cookies_dir("")

    profile = edge_profile_dir("xhs", base_dir)
    has_profile = os.path.isdir(profile) and any(os.scandir(profile))
    log("小红书合集：准备 Edge 登录档案…")
    log(f"小红书合集：档案目录 → {profile}（已有={has_profile}）")

    if not has_profile:
        raise RuntimeError(
            "小红书主页列表需要「扫码登录」生成的专用 Edge 档案。\n"
            "仅有 cookies.txt 不够（接口会返回 406）。\n\n"
            "请按顺序操作：\n"
            "1. 确认下载目录正确；\n"
            "2. 点击「扫码登录」→ 小红书 → 手机扫码；\n"
            "3. 成功后再点「解析」。"
        )

    log("小红书合集：打开主页并拦截笔记列表接口…")
    # headed briefly is more reliable for XHS anti-bot; window may flash
    pw, context, _ = _launch_persistent_edge("xhs", base_dir, headless=False)
    seen: dict[str, BatchItem] = {}
    has_more_flag = True
    page_title = "小红书主页"
    hit_login_wall = False
    api_errors: list[str] = []
    try:
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(resp) -> None:
            nonlocal has_more_flag
            u = resp.url or ""
            if "user_posted" not in u:
                return
            try:
                payload = resp.json()
            except Exception as e:
                api_errors.append(str(e))
                return
            if not (payload or {}).get("success", True) and payload.get("code") not in (0, None):
                api_errors.append(f"code={payload.get('code')} status={resp.status}")
            data = (payload or {}).get("data") or {}
            notes = data.get("notes") or []
            if not isinstance(notes, list):
                return
            if "has_more" in data:
                has_more_flag = bool(data.get("has_more"))
            for n in notes:
                if not isinstance(n, dict):
                    continue
                nid = str(n.get("note_id") or n.get("id") or "").strip()
                if not nid or nid in seen:
                    continue
                item = _xhs_batch_item_from_note(n, len(seen))
                if item:
                    seen[nid] = item

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(3000)

        cur = (page.url or "").lower()
        if "/login" in cur:
            hit_login_wall = True
            log("小红书合集：仍跳转登录页，请重新扫码登录")
        else:
            # Try notes tab
            for t in ("笔记", "作品"):
                try:
                    page.get_by_text(t, exact=True).first.click(timeout=1500)
                    page.wait_for_timeout(1200)
                    break
                except Exception:
                    pass

            for _ in range(25):
                if seen:
                    break
                page.wait_for_timeout(300)

            scrolls = 0
            max_scrolls = 22
            stagnant = 0
            while len(seen) < max_items and scrolls < max_scrolls and not hit_login_wall:
                before = len(seen)
                page.mouse.wheel(0, 3400)
                page.wait_for_timeout(1200)
                scrolls += 1
                if "/login" in ((page.url or "").lower()):
                    hit_login_wall = True
                    break
                log(f"小红书合集：滚动 {scrolls}/{max_scrolls}，已收集 {len(seen)} 条")
                if len(seen) == before:
                    stagnant += 1
                    if stagnant >= 3 and not has_more_flag:
                        break
                    if stagnant >= 6:
                        break
                else:
                    stagnant = 0

            page_title = (page.title() or "小红书主页").replace(" - 小红书", "").strip()
            try:
                nick = page.evaluate(
                    """() => {
                      const unwrap = (v) => (v && typeof v === 'object' && '_value' in v) ? v._value : v;
                      const s = window.__INITIAL_STATE__;
                      const info = unwrap(s && s.user && (s.user.userPageData || s.user.userInfo));
                      if (!info) return '';
                      const basic = unwrap(info.basicInfo) || info.basicInfo || info;
                      return (basic && (basic.nickname || basic.nickName)) || '';
                    }"""
                )
                if nick:
                    page_title = str(nick)
            except Exception:
                pass

            # Refresh cookies file if present
            if cookies_file:
                try:
                    from linkfetch.cookies_util import write_netscape_cookies

                    write_netscape_cookies(cookies_file, context.cookies())
                except Exception:
                    pass
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

    if not seen:
        if hit_login_wall:
            raise RuntimeError(
                "小红书登录已失效。\n"
                "请点击「扫码登录」重新扫码后再解析主页。"
            )
        extra = ("；接口：" + "; ".join(api_errors[:3])) if api_errors else ""
        raise RuntimeError(
            "小红书未解析到笔记列表" + extra + "。\n"
            "请重新「扫码登录」（会写入 edge_profile_xhs），\n"
            "确认下载目录与扫码时一致，然后再解析。\n"
            "单篇图文请用「图文」模式。"
        )

    items = list(seen.values())[:max_items]
    for i, it in enumerate(items):
        it.index = i
    log(f"小红书合集：共 {len(items)} 条，可勾选下载")
    return BatchList(source_url=url, title=page_title or "小红书主页", platform="xhs", items=items)


def extract_batch_list(
    url: str,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    max_items: int = 80,
    log: Optional[LogCallback] = None,
) -> BatchList:
    """
    Flat-extract playlist / space / collection / user-home entries.
    Routes: bilibili→yt-dlp, douyin→f2, xhs→Edge scrape.
    """
    log = log or (lambda _m: None)
    url = (url or "").strip()
    if not url:
        raise RuntimeError("缺少合集/主页链接")

    platform = detect_platform(url)
    log(f"合集/主页：平台={platform}")

    try:
        if platform == "douyin":
            return _extract_douyin_batch(
                url,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                max_items=max_items,
                log=log,
            )
        if platform == "xhs":
            return _extract_xhs_batch(
                url,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                max_items=max_items,
                log=log,
            )
        # bilibili + generic
        return _extract_ydl_batch(
            url,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
            max_items=max_items,
            log=log,
        )
    except Exception as e:
        # Douyin: optional yt-dlp fallback. XHS profile needs signed session — don't obscure.
        msg = str(e)
        if platform == "xhs" and (
            "扫码登录" in msg or "edge_profile" in msg or "406" in msg or "笔记列表" in msg
        ):
            raise
        if platform in ("douyin", "xhs"):
            log(f"合集/主页：专用通道失败，尝试 yt-dlp 兜底… ({e})")
            try:
                return _extract_ydl_batch(
                    url,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_from_browser,
                    max_items=max_items,
                    log=log,
                )
            except Exception:
                pass
        raise RuntimeError(
            f"未解析到可勾选条目。\n"
            f"B站：合集/空间/收藏夹链接\n"
            f"抖音：用户主页 /user/... 或合集 /collection/...\n"
            f"小红书：作者主页 /user/profile/...\n"
            f"单条内容请用「单链接」或「图文」。\n\n"
            f"原始错误：{e}"
        ) from e
