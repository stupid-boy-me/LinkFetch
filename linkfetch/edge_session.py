"""Edge (Playwright) session helpers for Douyin / Xiaohongshu."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Callable, Optional

from linkfetch.cookies_util import write_netscape_cookies


LogCallback = Callable[[str], None]


def _launch_edge(headless: bool = True):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="msedge", headless=headless)
    return pw, browser


def edge_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            b.close()
        return True
    except Exception:
        return False


def collect_site_cookies(
    start_url: str,
    *,
    wait_ms: int = 5000,
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
    ),
    log: Optional[LogCallback] = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Visit start_url with system Edge, return (cookie dicts, netscape temp path).
    """
    log = log or (lambda _m: None)
    log(f"Edge 会话：访问 {start_url}")
    pw, browser = _launch_edge(headless=True)
    try:
        context = browser.new_context(
            user_agent=user_agent,
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        cookies = context.cookies()
        fd, path = tempfile.mkstemp(prefix="linkfetch_cookies_", suffix=".txt")
        os.close(fd)
        write_netscape_cookies(path, cookies)
        log(f"Edge 会话：已获取 {len(cookies)} 条 Cookie")
        return cookies, path
    finally:
        browser.close()
        pw.stop()


def intercept_media(
    url: str,
    *,
    url_predicates: list[Callable[[str], bool]],
    wait_ms: int = 10000,
    extra_cookie_header: str = "",
    log: Optional[LogCallback] = None,
) -> dict[str, Any]:
    """
    Open URL in Edge, intercept matching media/API responses.
    Returns dict with keys: title, media_urls, aweme (optional), cookies_path.
    """
    log = log or (lambda _m: None)
    log(f"Edge 拦截：打开 {url}")
    pw, browser = _launch_edge(headless=True)
    media_urls: list[str] = []
    aweme: Optional[dict[str, Any]] = None
    title = ""
    cookies_path = ""
    try:
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
            ),
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )
        if extra_cookie_header:
            # Playwright prefers cookie objects; header injection via extra headers
            context.set_extra_http_headers({"Cookie": extra_cookie_header})

        page = context.new_page()

        def on_response(resp) -> None:
            nonlocal aweme
            u = resp.url
            try:
                if any(pred(u) for pred in url_predicates):
                    if u not in media_urls:
                        media_urls.append(u)
                if "aweme/detail" in u or "aweme/v1/web/aweme/detail" in u:
                    data = resp.json()
                    detail = data.get("aweme_detail")
                    if isinstance(detail, dict):
                        aweme = detail
            except Exception:
                return

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        title = page.title() or ""
        cookies = context.cookies()
        fd, cookies_path = tempfile.mkstemp(prefix="linkfetch_cookies_", suffix=".txt")
        os.close(fd)
        write_netscape_cookies(cookies_path, cookies)
    finally:
        browser.close()
        pw.stop()

    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in media_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)

    return {
        "title": title,
        "media_urls": uniq,
        "aweme": aweme,
        "cookies_path": cookies_path,
    }
