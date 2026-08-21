"""Edge (Playwright) session helpers for Douyin / Xiaohongshu."""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Callable, Optional

from linkfetch.cookies_util import write_netscape_cookies
from linkfetch.temp_cookies import register_temp_cookie


LogCallback = Callable[[str], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


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


def session_cookies_dir(base_dir: str = "") -> str:
    """Prefer user-configured download dir; fallback to Downloads/LinkFetch."""
    if base_dir and base_dir.strip():
        path = os.path.abspath(base_dir.strip())
    else:
        path = os.path.join(os.path.expanduser("~"), "Downloads", "LinkFetch")
    os.makedirs(path, exist_ok=True)
    return path


def session_cookies_path(site: str, base_dir: str = "") -> str:
    safe = (site or "session").strip().lower()
    if safe not in ("xhs", "douyin", "bilibili"):
        safe = "session"
    return os.path.join(session_cookies_dir(base_dir), f"cookies_{safe}.txt")


def edge_profile_dir(site: str, base_dir: str = "") -> str:
    """Persistent Edge profile used by QR login + later listing."""
    safe = (site or "session").strip().lower()
    if safe not in ("xhs", "douyin", "bilibili"):
        safe = "session"
    path = os.path.join(session_cookies_dir(base_dir), f"edge_profile_{safe}")
    os.makedirs(path, exist_ok=True)
    return path


def _launch_persistent_edge(
    site: str,
    base_dir: str = "",
    *,
    headless: bool = False,
):
    """Launch Edge with a dedicated persistent profile (keeps login + local tokens)."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    profile = edge_profile_dir(site, base_dir)
    context = pw.chromium.launch_persistent_context(
        user_data_dir=profile,
        channel="msedge",
        headless=headless,
        locale="zh-CN",
        viewport={"width": 1280, "height": 860},
        user_agent=_UA,
        args=["--disable-blink-features=AutomationControlled"],
    )
    try:
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
    except Exception:
        pass
    return pw, context, profile


def _cookie_map(cookies: list[dict[str, Any]]) -> dict[str, str]:
    return {str(c.get("name") or ""): str(c.get("value") or "") for c in cookies if c.get("name")}


def _xhs_logged_in(page, cookies: list[dict[str, Any]]) -> bool:
    cmap = _cookie_map(cookies)
    # web_session is set after QR / phone login
    if len(cmap.get("web_session") or "") < 8:
        return False
    url = (page.url or "").lower()
    if "/login" in url:
        return False
    try:
        ok = page.evaluate(
            """() => {
              try {
                const s = window.__INITIAL_STATE__;
                const login = s && s.user && s.user.loggedIn;
                if (login && login._value !== undefined) return !!login._value;
                return !!login;
              } catch (e) { return false; }
            }"""
        )
        if ok:
            return True
    except Exception:
        pass
    # Fallback: leave login page with web_session present
    return "xiaohongshu.com" in url and "/login" not in url


def _douyin_logged_in(page, cookies: list[dict[str, Any]]) -> bool:
    cmap = _cookie_map(cookies)
    if not any(cmap.get(k) for k in ("sessionid", "sessionid_ss", "sid_tt", "uid_tt")):
        return False
    url = (page.url or "").lower()
    return "douyin.com" in url and "passport" not in url


def interactive_qr_login(
    site: str = "xhs",
    *,
    timeout_sec: int = 300,
    save_dir: str = "",
    log: Optional[LogCallback] = None,
) -> str:
    """
    Open a visible Edge window (persistent profile) for QR login.
    Saves Netscape cookies under save_dir and keeps Edge profile for later listing.
    """
    log = log or (lambda _m: None)
    site = (site or "xhs").strip().lower()
    if site in ("xiaohongshu", "小红书"):
        site = "xhs"
    if site in ("抖音",):
        site = "douyin"

    if site == "douyin":
        start_url = "https://www.douyin.com/"
        check = _douyin_logged_in
        title_hint = "抖音"
    else:
        site = "xhs"
        start_url = "https://www.xiaohongshu.com/explore"
        check = _xhs_logged_in
        title_hint = "小红书"

    out_path = session_cookies_path(site, save_dir)
    profile = edge_profile_dir(site, save_dir)
    log(f"扫码登录：正在打开 Edge（{title_hint}），请用手机 App 扫码…")
    log(f"扫码登录：Cookie → {out_path}")
    log(f"扫码登录：登录档案 → {profile}")
    log(f"扫码登录：最长等待 {timeout_sec} 秒")

    pw, context, _profile = _launch_persistent_edge(site, save_dir, headless=False)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_timeout(1500)
            for sel in ("text=登录", "text=手机号登录"):
                loc = page.locator(sel).first
                if loc.count() > 0:
                    try:
                        loc.click(timeout=1500)
                        break
                    except Exception:
                        pass
        except Exception:
            pass

        deadline = time.time() + max(60, int(timeout_sec))
        last_msg = 0.0
        while time.time() < deadline:
            if page.is_closed():
                raise RuntimeError("登录窗口已关闭，未完成扫码")
            cookies = context.cookies()
            if check(page, cookies):
                # Stabilize: wait a bit so local tokens finish writing
                page.wait_for_timeout(2500)
                cookies = context.cookies()
                write_netscape_cookies(out_path, cookies)
                try:
                    context.storage_state(path=out_path.replace(".txt", "_state.json"))
                except Exception:
                    pass
                log(f"扫码登录：成功，已保存 {len(cookies)} 条 Cookie → {out_path}")
                return out_path
            now = time.time()
            if now - last_msg > 8:
                remain = int(deadline - now)
                log(f"扫码登录：等待中…剩余约 {remain}s（请在弹出的 Edge 窗口扫码）")
                last_msg = now
            page.wait_for_timeout(1000)

        raise RuntimeError(
            f"扫码登录超时（{timeout_sec}s）。\n"
            "请重试，并确认手机 App 已确认登录。"
        )
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def collect_site_cookies(
    start_url: str,
    *,
    wait_ms: int = 5000,
    user_agent: str = _UA,
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
        register_temp_cookie(path)
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
            user_agent=_UA,
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )
        if extra_cookie_header:
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
        register_temp_cookie(cookies_path)
    finally:
        browser.close()
        pw.stop()

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
