"""LinkFetch desktop GUI — modes: single / images / batch (+ drag-drop)."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from tkinter import (
    BooleanVar,
    Frame,
    Label,
    StringVar,
    filedialog,
    messagebox,
    simpledialog,
    ttk,
)
from typing import Optional

from linkfetch import __app_name__, __version__
from linkfetch import theme as T
from linkfetch.batch_channel import BatchItem, BatchList, extract_batch_list
from linkfetch.downloader import (
    Downloader,
    FORMAT_PREF_1080,
    FormatOption,
    MediaInfo,
    extract_share_url,
    looks_like_url,
)


# Temporarily disabled — set True to restore password-gated VIP mode UI.
VIP_MODE_ENABLED = False


try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD

    _DND = True
except Exception:
    from tkinter import Tk as _Tk

    class TkinterDnD:  # type: ignore
        Tk = _Tk

    DND_FILES = DND_TEXT = ""
    _DND = False


SITE_HINTS = {
    "single": "【单链接】粘贴/拖入一条分享文案或链接后解析下载。",
    "images": "【图文】仅小红书图集笔记；解析后勾选图片保存。",
    "batch": "【合集主页】B站/抖音/小红书。小红书主页可先点「扫码登录」再用手机扫码，然后解析。",
}
if VIP_MODE_ENABLED:
    SITE_HINTS["vip"] = (
        "【会员内容】需密码解锁。仅下载你登录账号已有权限的大会员/付费内容，必须提供已登录 cookies。"
    )


def _asset_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    here = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(here, *parts)


def is_douyin_url(url: str) -> bool:
    from linkfetch.platforms import is_douyin_url as _is

    return _is(url)


def is_xhs_url(url: str) -> bool:
    from linkfetch.platforms import is_xhs_url as _is

    return _is(url)


def friendly_cookie_error(err: BaseException, url: str = "") -> str:
    text = str(err)
    if is_douyin_url(url) or "[Douyin]" in text or "Fresh cookies" in text:
        return (
            "抖音解析/下载失败。\n\n"
            "已启用专用通道（f2 签名 + Edge 拦截）。若仍失败：\n"
            "1. 确认链接在浏览器能正常播放；\n"
            "2. 导出已登录抖音的 cookies.txt；\n"
            "3. 本机需已安装 Microsoft Edge。\n\n"
            f"原始错误：{text}"
        )
    if "扫码登录" in text or "edge_profile" in text or "笔记列表" in text:
        return text
    if is_xhs_url(url) or "XiaoHongShu" in text or "xiaohongshu" in text.lower():
        return (
            "小红书解析/下载失败。\n\n"
            "主页批量请先点「扫码登录」；单条可用带 xsec_token 的完整链接。\n\n"
            f"原始错误：{text}"
        )
    if "DPAPI" in text or "decrypt" in text.lower() or "10927" in text:
        return (
            "读取 Chrome/Edge Cookie 失败。\n"
            "请导出 Netscape cookies.txt，或改用 Firefox。\n\n"
            f"原始错误：{text}"
        )
    if "ffmpeg" in text.lower():
        return (
            "合并音视频需要 ffmpeg，但当前未找到。\n\n"
            "请使用最新版 LinkFetch.exe（已内置 ffmpeg），\n"
            "或本机安装 ffmpeg 并加入 PATH 后重试。\n\n"
            f"原始错误：{text}"
        )
    return text


class LinkFetchApp:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title(f"{__app_name__} v{__version__}")
        self.root.geometry("1180x780")
        self.root.minsize(980, 680)
        self.root.configure(bg=T.BG)

        self._photo_icon = None
        self._set_window_icon()

        self._thumb_photos: list = []  # keep PhotoImage refs
        self._thumb_labels: dict[int, Label] = {}
        self.media: Optional[MediaInfo] = None
        self.batch: Optional[BatchList] = None
        self.image_checks: list[BooleanVar] = []
        self.batch_checks: list[BooleanVar] = []
        self.downloader: Optional[Downloader] = None
        self._worker: Optional[threading.Thread] = None
        self._cancel = False
        self._vip_unlocked = False

        default_dir = os.path.join(os.path.expanduser("~"), "Downloads", "LinkFetch")
        os.makedirs(default_dir, exist_ok=True)

        self.mode_var = StringVar(value="single")
        self.url_var = StringVar()
        self.outdir_var = StringVar(value=default_dir)
        self.cookie_browser_var = StringVar(value="自动")
        self.cookies_file_var = StringVar(value="")
        self.want_video = BooleanVar(value=True)
        self.want_audio = BooleanVar(value=False)
        self.want_subs = BooleanVar(value=True)
        self.playlist_var = BooleanVar(value=False)  # 单链接模式默认不整页批量
        self.format_var = StringVar(value="（请先解析）")
        self.format_map: dict[str, FormatOption] = {}
        self.status_var = StringVar(value="就绪")
        self.hint_var = StringVar(value=SITE_HINTS["single"])

        self._build_ui()
        self._setup_dnd()

    def _set_window_icon(self) -> None:
        ico = _asset_path("assets", "linkfetch.ico")
        png = _asset_path("assets", "linkfetch_icon.png")
        try:
            if os.path.isfile(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass
        try:
            if os.path.isfile(png):
                from tkinter import PhotoImage

                self._photo_icon = PhotoImage(file=png)
                self.root.iconphoto(True, self._photo_icon)
        except Exception:
            pass

    def _accent_button(self, parent, text, command, *, bg=T.RED, hover=T.RED_HOVER, fg="#FFFFFF", font=T.FONT_BTN, padx=16, pady=7):
        from tkinter import Button

        btn = Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=font,
            cursor="hand2",
            padx=padx,
            pady=pady,
            highlightthickness=0,
        )

        def on_enter(_e):
            if str(btn["state"]) != "disabled":
                btn.configure(bg=hover)

        def on_leave(_e):
            if str(btn["state"]) != "disabled":
                btn.configure(bg=bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def _ghost_button(self, parent, text, command):
        return self._accent_button(
            parent, text, command, bg=T.CHIP, hover=T.BORDER, fg=T.TEXT, font=T.FONT_BTN_SM, padx=12, pady=7
        )

    def _card(self, parent) -> Frame:
        wrap = Frame(parent, bg=T.BORDER, padx=1, pady=1)
        inner = Frame(wrap, bg=T.CARD, padx=16, pady=14)
        inner.pack(fill="both", expand=True)
        wrap._inner = inner  # type: ignore[attr-defined]
        return wrap

    def _section_title(self, parent, title: str, more: str = "") -> Frame:
        row = Frame(parent, bg=T.CARD)
        row.pack(fill="x", pady=(0, 10))
        Label(row, text=title, bg=T.CARD, fg=T.TEXT, font=T.FONT_SECTION).pack(side="left")
        if more:
            Label(row, text=more, bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(side="right")
        return row

    def _configure_ttk(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=T.BG)
        style.configure("TLabel", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.configure("TRadiobutton", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.configure("TEntry", fieldbackground="#FFFFFF", foreground=T.TEXT, padding=8)
        style.configure("TCombobox", fieldbackground="#FFFFFF", foreground=T.TEXT, padding=5)
        style.configure(
            "XHS.Horizontal.TProgressbar",
            troughcolor=T.TRACK,
            background=T.RED,
            bordercolor=T.BORDER,
            lightcolor=T.RED,
            darkcolor=T.RED_DARK,
            thickness=10,
        )
        style.configure("TCheckbutton", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.map("TCheckbutton", background=[("active", T.CARD)])
        style.configure("Card.TCheckbutton", background=T.CHIP, foreground=T.TEXT, font=T.FONT_UI)
        style.map("Card.TCheckbutton", background=[("active", T.CHIP), ("selected", T.CHIP)])
        style.map("TRadiobutton", background=[("active", T.CARD)])

    def _build_ui(self) -> None:
        from tkinter import Canvas, Scrollbar

        self._configure_ttk()
        shell = Frame(self.root, bg=T.BG)
        shell.pack(fill="both", expand=True)

        # —— left sidebar (B站风格导航) ——
        side = Frame(shell, bg=T.SIDEBAR, width=100)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        Frame(shell, bg=T.BORDER, width=1).pack(side="left", fill="y")

        side_top = Frame(side, bg=T.SIDEBAR, padx=8, pady=14)
        side_top.pack(fill="x")
        Label(side_top, text="LF", bg=T.RED, fg="#FFFFFF", font=T.FONT_UI_BOLD, width=3).pack()
        Label(side_top, text="LinkFetch", bg=T.SIDEBAR, fg=T.TEXT, font=T.FONT_SIDE).pack(pady=(8, 0))

        nav = Frame(side, bg=T.SIDEBAR, padx=8, pady=10)
        nav.pack(fill="both", expand=True)
        self._mode_btns: dict[str, object] = {}
        mode_items = [
            ("single", "单链接"),
            ("images", "图文"),
            ("batch", "合集主页"),
        ]
        if VIP_MODE_ENABLED:
            mode_items.append(("vip", "会员内容"))
        for key, label in mode_items:
            btn = self._accent_button(
                nav,
                label,
                lambda k=key: self._select_mode(k),
                bg=T.CHIP,
                hover=T.RED_SOFT,
                fg=T.TEXT_SEC,
                font=T.FONT_SIDE,
                padx=6,
                pady=12,
            )
            btn.pack(fill="x", pady=4)
            self._mode_btns[key] = btn

        side_bot = Frame(side, bg=T.SIDEBAR, padx=8, pady=12)
        side_bot.pack(side="bottom", fill="x")
        Label(side_bot, text=f"v{__version__}", bg=T.SIDEBAR, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack()

        # —— right main column ——
        main = Frame(shell, bg=T.BG)
        main.pack(side="left", fill="both", expand=True)

        # top bar
        top = Frame(main, bg=T.TOPBAR, height=64)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        Frame(main, bg=T.BORDER, height=1).pack(side="top", fill="x")
        top_inner = Frame(top, bg=T.TOPBAR, padx=20, pady=10)
        top_inner.pack(fill="both", expand=True)
        Label(top_inner, text="LinkFetch", bg=T.TOPBAR, fg=T.TEXT, font=T.FONT_TITLE).pack(side="left")
        Label(
            top_inner,
            text="  B站 · 抖音 · 小红书",
            bg=T.TOPBAR,
            fg=T.TEXT_MUTED,
            font=T.FONT_SUB,
        ).pack(side="left", pady=(8, 0))
        self.page_title_var = StringVar(value="单链接下载")
        Label(top_inner, textvariable=self.page_title_var, bg=T.TOPBAR, fg=T.RED, font=T.FONT_UI_BOLD).pack(
            side="right"
        )

        # bottom dock
        dock = Frame(main, bg=T.CARD, padx=20, pady=12)
        dock.pack(side="bottom", fill="x")
        Frame(main, bg=T.BORDER, height=1).pack(side="bottom", fill="x")
        Label(dock, textvariable=self.status_var, bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB, anchor="w").pack(
            fill="x"
        )
        self.progress = ttk.Progressbar(dock, mode="determinate", maximum=100, style="XHS.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(6, 10))
        actions = Frame(dock, bg=T.CARD)
        actions.pack(fill="x")
        self.btn_download = self._accent_button(actions, "开始下载", self.on_download, padx=24, pady=8)
        self.btn_download.pack(side="left")
        self.btn_cancel = self._ghost_button(actions, "取消", self.on_cancel)
        self.btn_cancel.configure(state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        self._ghost_button(actions, "打开目录", self.on_open_dir).pack(side="left")
        self._ghost_button(
            actions,
            "支持站点",
            lambda: webbrowser.open("https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"),
        ).pack(side="right")

        # —— main body (no outer scroll canvas — avoids huge empty gaps) ——
        body = Frame(main, bg=T.BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)
        self._body = body
        self._body_canvas = None  # kept for older wheel handler

        # hint strip (compact)
        hint_card = self._card(body)
        hint_card.pack(fill="x", pady=(0, 8))
        hc = hint_card._inner  # type: ignore[attr-defined]
        Label(
            hc,
            textvariable=self.hint_var,
            bg=T.CARD,
            fg=T.TEXT_SEC,
            font=T.FONT_UI,
            wraplength=1000,
            justify="left",
        ).pack(anchor="w")

        # URL bar
        url_card = self._card(body)
        url_card.pack(fill="x", pady=(0, 8))
        ui = url_card._inner  # type: ignore[attr-defined]
        self._section_title(ui, "粘贴链接", "支持拖拽分享文案到窗口")
        search_wrap = Frame(ui, bg=T.CHIP, padx=2, pady=2)
        search_wrap.pack(fill="x")
        search_inner = Frame(search_wrap, bg="#FFFFFF", padx=10, pady=6)
        search_inner.pack(fill="x")
        Label(search_inner, text="⌕", bg="#FFFFFF", fg=T.TEXT_MUTED, font=("Segoe UI", 12)).pack(
            side="left", padx=(0, 6)
        )
        self.url_entry = ttk.Entry(search_inner, textvariable=self.url_var, font=T.FONT_UI)
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.btn_parse = self._accent_button(
            search_inner, "解析", self.on_parse, font=T.FONT_BTN_SM, padx=16, pady=6
        )
        self.btn_parse.pack(side="left", padx=(8, 0))
        self._ghost_button(search_inner, "粘贴", self.on_paste).pack(side="left", padx=(6, 0))

        # —— 下载设置（上）紧凑横排 ——
        opt_card = self._card(body)
        opt_card.pack(fill="x", pady=(0, 8))
        self.opt = opt_card._inner  # type: ignore[attr-defined]
        head_opt = Frame(self.opt, bg=T.CARD)
        head_opt.pack(fill="x", pady=(0, 8))
        Label(head_opt, text="下载设置", bg=T.CARD, fg=T.TEXT, font=T.FONT_SECTION).pack(side="left")
        Label(head_opt, text="Cookie / 目录", bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(side="right")

        row1 = Frame(self.opt, bg=T.CARD)
        row1.pack(fill="x", pady=(0, 6))
        Label(row1, text="下载目录", bg=T.CARD, fg=T.TEXT_SEC, font=T.FONT_SUB, width=8, anchor="w").pack(
            side="left"
        )
        ttk.Entry(row1, textvariable=self.outdir_var).pack(side="left", fill="x", expand=True, padx=(4, 8))
        self._ghost_button(row1, "浏览", self.on_browse).pack(side="left")

        row2 = Frame(self.opt, bg=T.CARD)
        row2.pack(fill="x", pady=(0, 6))
        Label(row2, text="Cookie", bg=T.CARD, fg=T.TEXT_SEC, font=T.FONT_SUB, width=8, anchor="w").pack(
            side="left"
        )
        ttk.Entry(row2, textvariable=self.cookies_file_var).pack(side="left", fill="x", expand=True, padx=(4, 8))
        self._ghost_button(row2, "选择", self.on_browse_cookies).pack(side="left", padx=(0, 6))
        self._ghost_button(row2, "扫码登录", self.on_qr_login).pack(side="left", padx=(0, 8))
        Label(row2, text="来源", bg=T.CARD, fg=T.TEXT_SEC, font=T.FONT_SUB).pack(side="left")
        ttk.Combobox(
            row2,
            textvariable=self.cookie_browser_var,
            values=["自动", "无", "firefox", "chrome", "edge", "brave"],
            width=10,
            state="readonly",
            font=T.FONT_UI,
        ).pack(side="left", padx=(4, 0))

        self.single_opts = Frame(self.opt, bg=T.CARD)
        self.single_opts.pack(fill="x", pady=(4, 0))
        Label(self.single_opts, text="输出", bg=T.CARD, fg=T.TEXT_SEC, font=T.FONT_SUB, width=8, anchor="w").pack(
            side="left"
        )
        self.chk_video = ttk.Checkbutton(self.single_opts, text="视频", variable=self.want_video)
        self.chk_video.pack(side="left", padx=(0, 12))
        self.chk_audio = ttk.Checkbutton(self.single_opts, text="另存纯音频", variable=self.want_audio)
        self.chk_audio.pack(side="left", padx=(0, 12))
        self.chk_subs = ttk.Checkbutton(self.single_opts, text="字幕", variable=self.want_subs)
        self.chk_subs.pack(side="left")
        self.opt_hint = Label(self.single_opts, text="", bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB)
        self.opt_hint.pack(side="left", padx=(12, 0))

        # tiny platform strip (optional, no expand)
        feat = Frame(body, bg=T.BG)
        feat.pack(fill="x", pady=(0, 8))
        self.feat_row = feat
        for title, desc, badge in (
            ("B站", "合集 / 清晰度", "✓"),
            ("抖音", "主页 / 合集", "✓"),
            ("小红书", "主页笔记", "✓"),
        ):
            tile = Frame(feat, bg=T.CARD, padx=10, pady=6)
            tile.pack(side="left", padx=(0, 8))
            Label(tile, text=f"{title}  {badge}", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI_BOLD).pack(side="left")
            Label(tile, text=f"  {desc}", bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(side="left")

        # —— 解析结果（下）占满剩余高度 ——
        mid_card = self._card(body)
        mid_card.pack(fill="both", expand=True)
        mid = mid_card._inner  # type: ignore[attr-defined]
        self._section_title(mid, "解析结果", "解析后在此选择清晰度或条目")
        self.info_label = Label(
            mid,
            text="尚未解析。把链接粘贴到上方，点「解析」开始。",
            bg=T.CARD,
            fg=T.TEXT_SEC,
            font=T.FONT_UI,
            justify="left",
            wraplength=900,
            anchor="nw",
        )
        self.info_label.pack(anchor="w", fill="x", pady=(0, 6))

        self.empty_panel = Frame(mid, bg=T.CHIP, padx=14, pady=14)
        self.empty_panel.pack(fill="both", expand=True)
        Label(self.empty_panel, text="工作区空闲", bg=T.CHIP, fg=T.TEXT, font=T.FONT_HERO).pack(anchor="w")
        Label(
            self.empty_panel,
            text="解析成功后，这里显示标题、清晰度或可勾选笔记列表。",
            bg=T.CHIP,
            fg=T.TEXT_MUTED,
            font=T.FONT_SUB,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        self.fmt_row = Frame(mid, bg=T.CARD)
        Label(self.fmt_row, text="清晰度", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI_BOLD).pack(side="left")
        self.format_box = ttk.Combobox(self.fmt_row, textvariable=self.format_var, state="disabled", font=T.FONT_UI)
        self.format_box.pack(side="left", fill="x", expand=True, padx=(10, 0))

        self.select_bar = Frame(mid, bg=T.CARD)
        self._ghost_button(self.select_bar, "全选", lambda: self._set_all_checks(True)).pack(side="left")
        self._ghost_button(self.select_bar, "全不选", lambda: self._set_all_checks(False)).pack(
            side="left", padx=(6, 0)
        )
        Label(self.select_bar, text="｜", bg=T.CARD, fg=T.BORDER, font=T.FONT_UI).pack(side="left", padx=8)
        self._ghost_button(self.select_bar, "全部", lambda: self._select_batch_by_type("all")).pack(side="left")
        self._ghost_button(self.select_bar, "图文", lambda: self._select_batch_by_type("image")).pack(
            side="left", padx=(6, 0)
        )
        self._ghost_button(self.select_bar, "视频", lambda: self._select_batch_by_type("video")).pack(
            side="left", padx=(6, 0)
        )
        self.filter_hint = Label(self.select_bar, text="", bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB)
        self.filter_hint.pack(side="left", padx=(10, 0))

        list_wrap = Frame(mid, bg=T.CARD)
        self._list_canvas = Canvas(list_wrap, bg=T.CARD, highlightthickness=0)
        sb = Scrollbar(list_wrap, orient="vertical", command=self._list_canvas.yview)
        self.check_host = Frame(self._list_canvas, bg=T.CARD)
        self.check_host.bind(
            "<Configure>",
            lambda e: self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all")),
        )
        self._list_window = self._list_canvas.create_window((0, 0), window=self.check_host, anchor="nw")
        self._list_canvas.configure(yscrollcommand=sb.set)
        self._list_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._list_canvas.bind(
            "<Configure>",
            lambda e: self._list_canvas.itemconfigure(self._list_window, width=e.width),
        )
        for w in (self._list_canvas, self.check_host, list_wrap, sb):
            w.bind("<MouseWheel>", self._on_list_mousewheel)
        self.list_wrap = list_wrap
        self._thumb_photos: list = []
        self._thumb_labels: dict[int, Label] = {}

        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self.on_mode_change()

    def _widget_under_list(self, widget) -> bool:
        w = widget
        while w is not None:
            if w in (self.list_wrap, self._list_canvas, self.check_host):
                return True
            w = getattr(w, "master", None)
        return False

    def _on_list_mousewheel(self, event):
        if not self.list_wrap.winfo_ismapped():
            return
        self._list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_global_mousewheel(self, event):
        """When note list is shown, wheel only moves the list."""
        if self.list_wrap.winfo_ismapped():
            self._list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

    def _refresh_list_scrollregion(self) -> None:
        self.check_host.update_idletasks()
        bbox = self._list_canvas.bbox("all")
        if bbox:
            self._list_canvas.configure(scrollregion=bbox)

    def _setup_dnd(self) -> None:
        if not _DND:
            self.status_var.set("就绪（当前环境不支持拖拽，可用粘贴）")
            return

        def on_drop(event) -> None:
            data = (event.data or "").strip()
            if not data:
                return
            # file drop: {path} or path
            if data.startswith("{") and data.endswith("}"):
                data = data[1:-1]
            paths = self.root.tk.splitlist(data)
            text = data
            if paths and os.path.isfile(paths[0]):
                try:
                    with open(paths[0], "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except Exception:
                    text = paths[0]
            url = extract_share_url(text) or text.strip()
            self.url_var.set(url)
            self.status_var.set("已拖入内容，正在解析…")
            self.on_parse()

        for w in (self.root, self.url_entry):
            try:
                w.drop_target_register(DND_TEXT, DND_FILES)
                w.dnd_bind("<<Drop>>", on_drop)
            except Exception:
                pass

    def _select_mode(self, mode: str) -> None:
        if mode == "vip":
            if not VIP_MODE_ENABLED:
                return
            if not self._ensure_vip_unlocked():
                return
        self.mode_var.set(mode)
        self.on_mode_change()

    def _ensure_vip_unlocked(self) -> bool:
        """Password gate for VIP mode. First run sets password; later verifies."""
        if not VIP_MODE_ENABLED:
            return False
        if self._vip_unlocked:
            return True
        from linkfetch import vip_gate

        if not vip_gate.has_password():
            messagebox.showinfo(
                "设置会员功能密码",
                "首次使用「会员内容」请设置专属密码。\n"
                "仅用于本机解锁该功能；下载仍需你自己的登录 Cookie。",
            )
            p1 = simpledialog.askstring("设置密码", "请输入新密码（至少 4 位）：", show="*", parent=self.root)
            if not p1:
                return False
            p2 = simpledialog.askstring("确认密码", "请再输入一次：", show="*", parent=self.root)
            if p1 != p2:
                messagebox.showerror("错误", "两次密码不一致。")
                return False
            try:
                vip_gate.set_password(p1)
            except ValueError as e:
                messagebox.showerror("错误", str(e))
                return False
            self._vip_unlocked = True
            messagebox.showinfo("已解锁", "会员内容功能已解锁（本次会话有效）。")
            return True

        pwd = simpledialog.askstring("会员内容", "请输入会员功能密码：", show="*", parent=self.root)
        if pwd is None:
            return False
        if not vip_gate.verify_password(pwd):
            messagebox.showerror("错误", "密码错误，无法进入会员内容模式。")
            return False
        self._vip_unlocked = True
        return True

    def _refresh_mode_buttons(self) -> None:
        cur = self.mode_var.get()
        titles = {
            "single": "单链接下载",
            "images": "图文笔记",
            "batch": "合集 / 主页",
            "vip": "会员内容",
        }
        if hasattr(self, "page_title_var"):
            self.page_title_var.set(titles.get(cur, "LinkFetch"))
        for key, btn in getattr(self, "_mode_btns", {}).items():
            if key == cur:
                btn.configure(
                    bg=T.RED,
                    fg="#FFFFFF",
                    activebackground=T.RED_HOVER,
                    activeforeground="#FFFFFF",
                )
                btn.bind(
                    "<Enter>",
                    lambda e, b=btn: b.configure(bg=T.RED_HOVER) if str(b["state"]) != "disabled" else None,
                )
                btn.bind(
                    "<Leave>",
                    lambda e, b=btn: b.configure(bg=T.RED) if str(b["state"]) != "disabled" else None,
                )
            else:
                btn.configure(
                    bg=T.CHIP,
                    fg=T.TEXT_SEC,
                    activebackground=T.RED_SOFT,
                    activeforeground=T.TEXT,
                )
                btn.bind(
                    "<Enter>",
                    lambda e, b=btn: b.configure(bg=T.RED_SOFT) if str(b["state"]) != "disabled" else None,
                )
                btn.bind(
                    "<Leave>",
                    lambda e, b=btn: b.configure(bg=T.CHIP) if str(b["state"]) != "disabled" else None,
                )

    def _show_empty_workspace(self, show: bool) -> None:
        if not hasattr(self, "empty_panel"):
            return
        if show:
            self.empty_panel.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.empty_panel.pack_forget()

    def on_mode_change(self) -> None:
        mode = self.mode_var.get()
        self._refresh_mode_buttons()
        self.hint_var.set(SITE_HINTS.get(mode, ""))
        self.media = None
        self.batch = None
        self._clear_checks()
        self.info_label.configure(
            text="尚未解析。把链接粘贴到上方，点「解析」开始。",
            fg=T.TEXT_SEC,
        )
        self.format_var.set("（请先解析）")
        self.format_box.configure(values=[], state="disabled")
        self._show_empty_workspace(True)

        if mode in ("single", "vip") and (mode != "vip" or VIP_MODE_ENABLED):
            self.single_opts.pack(fill="x", pady=(4, 0))
            self.fmt_row.pack(fill="x", pady=(8, 0))
            self.select_bar.pack_forget()
            self.list_wrap.pack_forget()
            if hasattr(self, "feat_row") and not self.feat_row.winfo_ismapped():
                self.feat_row.pack(fill="x", pady=(0, 8))
            if mode == "vip" and VIP_MODE_ENABLED:
                self.want_subs.set(True)
                self.chk_subs.configure(state="normal")
                self.opt_hint.configure(text="需已登录 Cookie（大会员账号）")
            else:
                self.opt_hint.configure(text="")
                self._refresh_channel_option_states()
        else:
            self.single_opts.pack_forget()
            self.fmt_row.pack_forget()
            self.select_bar.pack(fill="x", pady=(6, 0))
            self.list_wrap.pack(fill="both", expand=True, pady=(6, 0))
            if hasattr(self, "feat_row") and not self.feat_row.winfo_ismapped():
                self.feat_row.pack(fill="x", pady=(0, 8))
            if hasattr(self, "filter_hint"):
                self.filter_hint.configure(text="")

    def _clear_checks(self) -> None:
        for child in self.check_host.winfo_children():
            child.destroy()
        self.image_checks = []
        self.batch_checks = []
        self._thumb_photos = []
        self._thumb_labels = {}

    def _set_all_checks(self, value: bool) -> None:
        checks = self.image_checks if self.mode_var.get() == "images" else self.batch_checks
        for v in checks:
            v.set(value)
        if hasattr(self, "filter_hint"):
            self.filter_hint.configure(text="已全选" if value else "已全不选")

    def _note_is_video(self, item: BatchItem) -> bool:
        return str((item.extra or {}).get("type") or "").lower() == "video"

    def _select_batch_by_type(self, kind: str) -> None:
        """kind: all | image | video — auto check matching notes."""
        if not self.batch or not self.batch_checks:
            return
        selected = 0
        for item, var in zip(self.batch.items, self.batch_checks):
            is_video = self._note_is_video(item)
            if kind == "all":
                on = True
            elif kind == "video":
                on = is_video
            else:  # image / 图文
                on = not is_video
            var.set(on)
            if on:
                selected += 1
        labels = {"all": "全部", "image": "图文", "video": "视频"}
        if hasattr(self, "filter_hint"):
            self.filter_hint.configure(
                text=f"已按「{labels.get(kind, kind)}」勾选 {selected}/{len(self.batch.items)} 条"
            )
        self.status_var.set(f"已按{labels.get(kind, kind)}筛选勾选：{selected} 条")

    @staticmethod
    def _fmt_count(raw: str) -> str:
        s = (raw or "0").strip().replace(",", "")
        try:
            n = float(s)
        except ValueError:
            return raw or "0"
        if n >= 100_000_000:
            return f"{n/100_000_000:.1f}亿".replace(".0亿", "亿")
        if n >= 10_000:
            return f"{n/10_000:.1f}万".replace(".0万", "万")
        if n >= 1000:
            return str(int(n))
        return str(int(n)) if n == int(n) else s

    def _bind_card_wheel(self, *widgets) -> None:
        for w in widgets:
            try:
                w.bind("<MouseWheel>", self._on_list_mousewheel)
            except Exception:
                pass

    def _populate_image_checks(self, media: MediaInfo) -> None:
        self._clear_checks()
        images = list((media.raw or {}).get("image_urls") or [])
        self.image_checks = []
        for i, u in enumerate(images):
            var = BooleanVar(value=True)
            self.image_checks.append(var)
            cb = ttk.Checkbutton(
                self.check_host,
                text=f"图片 {i+1}  ·  {u[:70]}{'…' if len(u)>70 else ''}",
                variable=var,
            )
            cb.pack(anchor="w", pady=2)
            cb.bind("<MouseWheel>", self._on_list_mousewheel)
        self._refresh_list_scrollregion()
        self._list_canvas.yview_moveto(0)

    def _populate_batch_checks(self, batch: BatchList) -> None:
        self._clear_checks()
        self.batch_checks = []
        rich = batch.platform == "xhs" or any((it.extra or {}).get("cover_url") for it in batch.items)
        for item in batch.items:
            var = BooleanVar(value=True)
            self.batch_checks.append(var)
            if rich:
                self._add_note_card(item, var)
            else:
                title = item.title if len(item.title) <= 60 else item.title[:60] + "…"
                cb = ttk.Checkbutton(
                    self.check_host,
                    text=f"[{item.index+1}] {title}",
                    variable=var,
                )
                cb.pack(anchor="w", pady=2)
                cb.bind("<MouseWheel>", self._on_list_mousewheel)
        self._refresh_list_scrollregion()
        self._list_canvas.yview_moveto(0)
        if rich:
            self._load_batch_thumbnails(batch)

    def _add_note_card(self, item: BatchItem, var: BooleanVar) -> None:
        extra = item.extra or {}
        card = Frame(self.check_host, bg=T.CHIP, padx=6, pady=6)
        card.pack(fill="x", pady=2)

        # grid: checkbox | thumb | text — no floating gap
        card.columnconfigure(2, weight=1)

        cb_wrap = Frame(card, bg=T.CHIP, width=28)
        cb_wrap.grid(row=0, column=0, sticky="n", padx=(0, 4), pady=2)
        cb_wrap.grid_propagate(False)
        cb = ttk.Checkbutton(cb_wrap, variable=var, style="Card.TCheckbutton")
        cb.pack(anchor="n")

        thumb_box = Frame(card, bg="#DEDDE2", width=64, height=84)
        thumb_box.grid(row=0, column=1, sticky="nw", padx=(0, 8))
        thumb_box.grid_propagate(False)
        thumb = Label(thumb_box, text="", bg="#DEDDE2", fg=T.TEXT_MUTED, font=T.FONT_SUB)
        thumb.place(relx=0.5, rely=0.5, anchor="center")
        self._thumb_labels[item.index] = thumb

        body = Frame(card, bg=T.CHIP)
        body.grid(row=0, column=2, sticky="nwe")

        ntype = str(extra.get("type") or "")
        is_video = ntype.lower() == "video"
        type_label = "视频" if is_video else "图文"
        title = (item.title or "无标题").strip()
        if len(title) > 36:
            title = title[:36] + "…"

        Label(
            body,
            text=f"[{item.index+1}] · {type_label}  {title}",
            bg=T.CHIP,
            fg=T.TEXT,
            font=T.FONT_UI_BOLD,
            anchor="w",
            justify="left",
        ).pack(anchor="w")

        pub = str(extra.get("published_at") or "")
        if pub:
            Label(body, text=f"发布 {pub}", bg=T.CHIP, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(
                anchor="w", pady=(2, 0)
            )

        stats = Frame(body, bg=T.CHIP)
        stats.pack(anchor="w", pady=(4, 0))
        liked = self._fmt_count(str(extra.get("liked_count") or "0"))
        collected = self._fmt_count(str(extra.get("collected_count") or "0"))
        commented = self._fmt_count(str(extra.get("comment_count") or "0"))
        for text in (f"赞 {liked}", f"藏 {collected}", f"评 {commented}"):
            Label(
                stats,
                text=text,
                bg=T.RED_SOFT,
                fg=T.RED_DARK,
                font=T.FONT_SUB,
                padx=5,
                pady=0,
            ).pack(side="left", padx=(0, 4))

        self._bind_card_wheel(card, cb_wrap, cb, thumb_box, thumb, body, stats)
        for child in body.winfo_children():
            self._bind_card_wheel(child)
        for child in stats.winfo_children():
            self._bind_card_wheel(child)

    def _load_batch_thumbnails(self, batch: BatchList) -> None:
        """Download cover thumbs in background; update UI on main thread."""

        def work() -> None:
            try:
                import io

                import httpx
                from PIL import Image, ImageTk
            except Exception:
                return

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
                ),
                "Referer": "https://www.xiaohongshu.com/",
            }
            with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
                for item in batch.items:
                    url = str((item.extra or {}).get("cover_url") or "")
                    if not url:
                        continue
                    idx = item.index
                    try:
                        r = client.get(url)
                        if r.status_code >= 400:
                            continue
                        img = Image.open(io.BytesIO(r.content)).convert("RGB")
                        img.thumbnail((72, 96))
                        # build PhotoImage on main thread
                        raw = io.BytesIO()
                        img.save(raw, format="PNG")
                        data = raw.getvalue()

                        def apply(i=idx, png=data) -> None:
                            lab = self._thumb_labels.get(i)
                            if not lab or not lab.winfo_exists():
                                return
                            try:
                                from PIL import Image as _Im, ImageTk as _ImTk

                                photo = _ImTk.PhotoImage(image=_Im.open(io.BytesIO(png)))
                                self._thumb_photos.append(photo)
                                lab.configure(image=photo, text="")
                            except Exception:
                                lab.configure(text="图")

                        self.root.after(0, apply)
                    except Exception:
                        continue
            self.root.after(0, self._refresh_list_scrollregion)

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()

    def log(self, msg: str) -> None:
        short = (msg or "").strip().replace("\n", " ")
        if short and any(k in short for k in ("解析", "下载", "完成", "失败", "取消", "提取", "图文", "合集")):
            self.root.after(0, lambda: self.status_var.set(short[:120]))

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_parse.configure(state=state)
        self.btn_download.configure(state=state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    def _make_downloader(self) -> Downloader:
        browser = self.cookie_browser_var.get().strip()
        auto = browser in ("", "自动", "auto")
        cookies_from_browser = "" if browser in ("", "无", "自动", "auto") else browser
        return Downloader(
            outdir=self.outdir_var.get().strip() or os.getcwd(),
            cookies_from_browser=cookies_from_browser,
            cookies_file=self.cookies_file_var.get().strip(),
            auto_cookies=auto,
            log_cb=self.log,
        )

    def _resolve_input_url(self) -> str:
        text = (self.url_var.get() or "").strip()
        if not text:
            return ""
        url = extract_share_url(text)
        if not url and looks_like_url(text):
            url = text.split()[0].strip()
        if url:
            if url != text:
                self.log(f"已从分享文案提取链接：{url}")
            self.url_var.set(url)
        return url

    def on_paste(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except Exception:
            return
        if not text:
            return
        url = extract_share_url(text) or text
        self.url_var.set(url)
        if url != text:
            self.log(f"已从剪贴板提取链接：{url}")

    def on_browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.outdir_var.get())
        if path:
            self.outdir_var.set(path)

    def on_browse_cookies(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 cookies.txt",
            filetypes=[("Cookie 文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self.cookies_file_var.set(path)
            self.cookie_browser_var.set("自动")

    def on_qr_login(self) -> None:
        """Open Edge for QR login; save cookies for later parse/download."""
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("提示", "当前有任务进行中，请稍后再扫码登录。")
            return

        from tkinter import simpledialog

        from linkfetch.edge_session import interactive_qr_login
        from linkfetch.platforms import is_douyin_url, is_xhs_url

        url = (self.url_var.get() or "").strip()
        default = "小红书"
        if is_douyin_url(url):
            default = "抖音"
        elif is_xhs_url(url):
            default = "小红书"

        choice = simpledialog.askstring(
            "扫码登录",
            "输入平台：小红书 或 抖音\n"
            "将弹出 Edge 窗口，请用手机 App 扫码；成功后自动保存 Cookie。",
            initialvalue=default,
            parent=self.root,
        )
        if not choice:
            return
        c = choice.strip()
        if c in ("抖音", "douyin", "Douyin"):
            site = "douyin"
        else:
            site = "xhs"

        self.set_busy(True)
        self.status_var.set(f"扫码登录中（{c}）…请在 Edge 窗口操作")
        self.log(f"开始扫码登录：{site}")

        def work() -> None:
            try:
                save_dir = self.outdir_var.get().strip() or os.path.join(
                    os.path.expanduser("~"), "Downloads", "LinkFetch"
                )
                path = interactive_qr_login(
                    site,
                    timeout_sec=300,
                    save_dir=save_dir,
                    log=self.log,
                )

                def ok() -> None:
                    self.cookies_file_var.set(path)
                    self.cookie_browser_var.set("无")  # 优先用刚扫码保存的文件
                    self.set_busy(False)
                    self.status_var.set("扫码登录成功，Cookie 已填入")
                    messagebox.showinfo(
                        "扫码成功",
                        f"已保存登录 Cookie：\n{path}\n\n"
                        f"同时写入登录档案（解析主页必需）：\n"
                        f"{os.path.join(save_dir, 'edge_profile_xhs')}\n\n"
                        "请再点「解析」拉取笔记列表。",
                    )

                self.root.after(0, ok)
            except Exception as e:
                def fail() -> None:
                    self.set_busy(False)
                    self.status_var.set("扫码登录失败")
                    messagebox.showerror("扫码登录失败", str(e))

                self.root.after(0, fail)

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def on_open_dir(self) -> None:
        path = self.outdir_var.get()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def on_cancel(self) -> None:
        self._cancel = True
        if self.downloader:
            self.downloader.cancel()
        self.status_var.set("正在取消…")

    def _refresh_channel_option_states(self, url: str = "") -> None:
        """Gray out options that dedicated Douyin/XHS channels do not support."""
        if VIP_MODE_ENABLED and self.mode_var.get() == "vip":
            self.chk_subs.configure(state="normal")
            self.opt_hint.configure(text="需已登录 Cookie（大会员账号）")
            return
        if self.mode_var.get() != "single":
            return
        u = url or (self.media.url if self.media else "") or self.url_var.get()
        channel = (self.media.raw or {}).get("channel") if self.media else ""
        dedicated = bool(
            is_douyin_url(u)
            or is_xhs_url(u)
            or channel in ("douyin", "xhs", "xhs_images")
            or (self.media and "Douyin" in (self.media.extractor or ""))
            or (self.media and "XiaoHongShu" in (self.media.extractor or ""))
        )
        if dedicated:
            self.want_subs.set(False)
            self.chk_subs.configure(state="disabled")
            self.opt_hint.configure(text="抖音/小红书专用通道不支持字幕")
        else:
            self.chk_subs.configure(state="normal")
            self.opt_hint.configure(text="")

    def _vip_cookies_ready(self) -> bool:
        cfile = self.cookies_file_var.get().strip()
        if cfile and os.path.isfile(cfile):
            return True
        browser = self.cookie_browser_var.get().strip().lower()
        return browser in ("firefox", "chrome", "edge", "brave")

    def on_parse(self) -> None:
        url = self._resolve_input_url()
        if not url:
            messagebox.showwarning("提示", "未识别到有效链接。")
            return
        if self._worker and self._worker.is_alive():
            return

        mode = self.mode_var.get()
        if VIP_MODE_ENABLED and mode == "vip":
            if not self._vip_unlocked and not self._ensure_vip_unlocked():
                return
            if not self._vip_cookies_ready():
                messagebox.showwarning(
                    "会员内容",
                    "请先选择已登录账号的 Cookie 文件，或指定浏览器 Cookie 来源。\n"
                    "只能下载该账号已有权限的内容。",
                )
                return

        self._cancel = False
        self.set_busy(True)
        self.status_var.set("解析中…")
        self.progress["value"] = 0

        def work() -> None:
            try:
                if mode == "images":
                    if not is_xhs_url(url):
                        raise RuntimeError("图文笔记模式仅支持小红书链接。")
                    from linkfetch.xhs_channel import extract_xhs_images

                    info = extract_xhs_images(
                        url,
                        cookies_file=self.cookies_file_var.get().strip(),
                        log=self.log,
                        cancel_flag=lambda: self._cancel,
                    )
                    self.root.after(0, lambda: self._apply_images(info))
                elif mode == "batch":
                    browser = self.cookie_browser_var.get().strip()
                    # 「自动」传 auto，让各平台自己探测浏览器 Cookie
                    cb = "auto" if browser in ("", "自动", "auto") else (
                        "" if browser in ("无",) else browser
                    )
                    batch = extract_batch_list(
                        url,
                        cookies_file=self.cookies_file_var.get().strip(),
                        cookies_from_browser=cb,
                        log=self.log,
                    )
                    self.root.after(0, lambda: self._apply_batch(batch))
                else:
                    # single + vip share extract path; vip forces cookie usage via UI
                    dl = self._make_downloader()
                    self.downloader = dl
                    info = dl.extract(url, process_playlist=False)
                    self.root.after(0, lambda: self._apply_single(info))
            except Exception as e:
                tip = friendly_cookie_error(e, url)
                self.root.after(0, lambda: messagebox.showerror("解析失败", tip))
                self.root.after(0, lambda: self.status_var.set("解析失败"))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _apply_single(self, info: MediaInfo) -> None:
        self.media = info
        self.batch = None
        self._show_empty_workspace(False)
        dur = f"{int(info.duration)}s" if info.duration else "未知"
        vip_tag = (
            " · 会员模式" if (VIP_MODE_ENABLED and self.mode_var.get() == "vip") else ""
        )
        self.info_label.configure(
            text=f"标题：{info.title}\n平台：{info.extractor or '未知'} · 时长：{dur}{vip_tag}",
            fg=T.TEXT,
        )
        formats = [f for f in info.formats if not f.is_audio_only] or info.formats
        if self.want_audio.get() and not self.want_video.get():
            formats = [f for f in info.formats if f.is_audio_only] or formats
        self.format_map = {f.label: f for f in formats}
        labels = [f.label for f in formats] or ["（无可用格式）"]
        self.format_box.configure(values=labels, state="readonly")
        # Prefer an explicit ≥1080p option when listed
        pick = labels[0]
        for f in formats:
            if f.height and f.height >= 1080 and not f.is_audio_only:
                pick = f.label
                break
            if "1080" in (f.label or "") and not f.is_audio_only:
                pick = f.label
                break
        self.format_var.set(pick)
        real_heights = [
            f.height or 0
            for f in info.formats
            if (not f.is_audio_only)
            and f.format_id not in (FORMAT_PREF_1080, "bv*+ba/b")
            and (f.height or 0) > 0
        ]
        max_h = max(real_heights) if real_heights else 0
        if max_h and max_h < 1080:
            self.status_var.set(
                f"解析成功（最高约 {max_h}p）。要 1080P 请导入已登录/大会员 Cookie 后重新解析。"
            )
        else:
            self.status_var.set(f"解析成功：{info.title[:40]}")
        self._refresh_channel_option_states(info.url)

    def _apply_images(self, info: MediaInfo) -> None:
        self.media = info
        self.batch = None
        self._show_empty_workspace(False)
        n = len((info.raw or {}).get("image_urls") or [])
        self.info_label.configure(text=f"图文：{info.title}\n共 {n} 张图片（请勾选后下载）", fg=T.TEXT)
        self._populate_image_checks(info)
        self.status_var.set(f"图文解析成功：{n} 张")

    def _apply_batch(self, batch: BatchList) -> None:
        self.batch = batch
        self.media = None
        self._show_empty_workspace(False)
        if hasattr(self, "feat_row"):
            self.feat_row.pack_forget()
        n_video = sum(1 for it in batch.items if self._note_is_video(it))
        n_image = len(batch.items) - n_video
        self.info_label.configure(
            text=(
                f"列表：{batch.title}　"
                f"平台：{batch.platform} · 共 {len(batch.items)} 条"
                f"（图文 {n_image} / 视频 {n_video}）"
            ),
            fg=T.TEXT,
        )
        self._populate_batch_checks(batch)
        if hasattr(self, "filter_hint"):
            self.filter_hint.configure(text="点「图文/视频」可一键勾选对应类型")
        self.status_var.set(f"列表解析成功：{len(batch.items)} 条")

    def _download_jobs_single(self) -> list[tuple[str, bool, bool]]:
        label = self.format_var.get()
        fmt = self.format_map.get(label)
        base_id = fmt.format_id if fmt else FORMAT_PREF_1080
        jobs: list[tuple[str, bool, bool]] = []
        if self.want_video.get():
            fid = FORMAT_PREF_1080 if (fmt and fmt.is_audio_only) else base_id
            jobs.append((fid, False, self.want_subs.get()))
        if self.want_audio.get() and not self.want_video.get():
            jobs.append(("ba/b", True, False))
        elif self.want_audio.get() and self.want_video.get():
            jobs.append(("ba/b", True, False))
        if not jobs:
            jobs.append((FORMAT_PREF_1080, False, self.want_subs.get()))
        return jobs

    def on_download(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        mode = self.mode_var.get()
        self._cancel = False

        if mode == "images":
            if not self.media or (self.media.raw or {}).get("channel") != "xhs_images":
                messagebox.showwarning("提示", "请先在「图文笔记」模式解析。")
                return
            idxs = [i for i, v in enumerate(self.image_checks) if v.get()]
            if not idxs:
                messagebox.showwarning("提示", "请至少勾选一张图片。")
                return
            self._run_images_download(idxs)
            return

        if mode == "batch":
            if not self.batch:
                messagebox.showwarning("提示", "请先在「合集/主页」模式解析。")
                return
            items = [it for it, v in zip(self.batch.items, self.batch_checks) if v.get()]
            if not items:
                messagebox.showwarning("提示", "请至少勾选一条。")
                return
            self._run_batch_download(items)
            return

        # single (+ optional vip)
        if VIP_MODE_ENABLED and mode == "vip":
            if not self._vip_unlocked and not self._ensure_vip_unlocked():
                return
            if not self._vip_cookies_ready():
                messagebox.showwarning(
                    "会员内容",
                    "请先提供已登录账号的 Cookie 文件或浏览器来源。",
                )
                return

        url = self._resolve_input_url()
        if not self.media and not url:
            messagebox.showwarning("提示", "请先解析链接。")
            return
        if not (self.want_video.get() or self.want_audio.get()):
            messagebox.showwarning("提示", "请至少勾选视频或另存纯音频。")
            return
        self._run_single_download(url)

    def _run_single_download(self, url: str) -> None:
        jobs = self._download_jobs_single()
        sub_langs = (self.media.subtitles[:6] if self.media else None) or ["zh-Hans", "zh-CN", "zh", "en"]
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set("准备下载…")

        def work() -> None:
            try:
                dl = self._make_downloader()
                self.downloader = dl

                def on_progress(d: dict) -> None:
                    self._progress_hook(d)

                target = self.media.url if self.media else url
                for i, (fid, audio_only, write_subs) in enumerate(jobs, 1):
                    if self._cancel:
                        raise KeyboardInterrupt()
                    self.root.after(0, lambda i=i: self.status_var.set(f"单链接任务 {i}/{len(jobs)}…"))
                    dl.download(
                        target,
                        fid,
                        audio_only=audio_only,
                        write_subs=write_subs,
                        sub_langs=sub_langs,
                        playlist=False,
                        progress_cb=on_progress,
                        media=self.media,
                    )
                self.root.after(0, lambda: self.status_var.set("下载完成"))
                self.root.after(0, lambda: messagebox.showinfo("完成", f"下载完成！\n{dl.outdir}"))
            except KeyboardInterrupt:
                self.root.after(0, lambda: self.status_var.set("已取消"))
            except Exception as e:
                tip = friendly_cookie_error(e, url)
                self.root.after(0, lambda: messagebox.showerror("下载失败", tip))
                self.root.after(0, lambda: self.status_var.set("下载失败"))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _run_images_download(self, idxs: list[int]) -> None:
        assert self.media is not None
        media = self.media
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set("下载图片…")

        def work() -> None:
            try:
                from linkfetch.xhs_channel import download_xhs_images

                folder = download_xhs_images(
                    media,
                    self.outdir_var.get().strip() or os.getcwd(),
                    selected_indices=idxs,
                    progress_cb=self._progress_hook,
                    cancel_flag=lambda: self._cancel,
                    log=self.log,
                )
                self.root.after(0, lambda: self.status_var.set("图片下载完成"))
                self.root.after(0, lambda: messagebox.showinfo("完成", f"已保存到：\n{folder}"))
            except KeyboardInterrupt:
                self.root.after(0, lambda: self.status_var.set("已取消"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("下载失败", str(e)))
                self.root.after(0, lambda: self.status_var.set("下载失败"))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _run_batch_download(self, items: list[BatchItem]) -> None:
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set("批量下载…")
        total = len(items)

        def work() -> None:
            try:
                dl = self._make_downloader()
                self.downloader = dl
                ok = 0
                failures: list[str] = []
                for i, item in enumerate(items, 1):
                    if self._cancel:
                        raise KeyboardInterrupt()
                    title_short = (item.title or item.url)[:30]
                    self.root.after(
                        0,
                        lambda i=i, t=title_short: self.status_var.set(f"批量 {i}/{total}：{t}"),
                    )
                    self.root.after(0, lambda i=i, t=total: self.progress.configure(value=i / t * 100))
                    try:
                        dl.download(
                            item.url,
                            FORMAT_PREF_1080,
                            audio_only=False,
                            write_subs=False,
                            playlist=False,
                            progress_cb=None,
                            media=None,
                        )
                        ok += 1
                    except Exception as e:
                        reason = str(e).strip().replace("\n", " ")
                        if len(reason) > 120:
                            reason = reason[:117] + "…"
                        failures.append(f"· {item.title[:40] or item.url}\n  {reason}")
                        self.log(f"跳过失败项：{item.title} ({e})")
                summary = f"完成 {ok}/{total} 条\n目录：{dl.outdir}"
                if failures:
                    shown = failures[:12]
                    more = f"\n…另有 {len(failures) - 12} 条失败" if len(failures) > 12 else ""
                    summary += "\n\n失败明细：\n" + "\n".join(shown) + more
                self.root.after(0, lambda: self.status_var.set(f"批量完成 {ok}/{total}"))
                self.root.after(0, lambda s=summary: messagebox.showinfo("批量结果", s))
            except KeyboardInterrupt:
                self.root.after(0, lambda: self.status_var.set("已取消"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("下载失败", str(e)))
                self.root.after(0, lambda: self.status_var.set("下载失败"))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _progress_hook(self, d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0.0
            self.root.after(0, lambda: self.progress.configure(value=min(pct, 100)))
            self.root.after(0, lambda: self.status_var.set(f"下载中 {pct:.1f}%"))
        elif status == "finished":
            self.root.after(0, lambda: self.progress.configure(value=100))


def run() -> None:
    LinkFetchApp().run()
