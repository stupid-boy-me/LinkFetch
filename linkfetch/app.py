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
    ttk,
)
from typing import Optional

from linkfetch import __app_name__, __version__
from linkfetch import theme as T
from linkfetch.batch_channel import BatchItem, BatchList, extract_batch_list
from linkfetch.downloader import (
    Downloader,
    FormatOption,
    MediaInfo,
    extract_share_url,
    looks_like_url,
)


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
    "images": "【图文笔记】仅用于小红书图集；解析后可勾选要保存的图片。",
    "batch": "【合集/主页】B站合集·空间或可识别列表页；解析后勾选条目再下载。",
}


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
    if is_xhs_url(url) or "XiaoHongShu" in text or "xiaohongshu" in text.lower():
        return (
            "小红书解析/下载失败。\n\n"
            "建议使用带 xsec_token 的完整链接，或导出 cookies.txt。\n\n"
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
        self.root.geometry("900x680")
        self.root.minsize(760, 560)
        self.root.configure(bg=T.BG)

        self._photo_icon = None
        self._set_window_icon()

        self.media: Optional[MediaInfo] = None
        self.batch: Optional[BatchList] = None
        self.image_checks: list[BooleanVar] = []
        self.batch_checks: list[BooleanVar] = []
        self.downloader: Optional[Downloader] = None
        self._worker: Optional[threading.Thread] = None
        self._cancel = False

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
            parent, text, command, bg="#F0F0F0", hover="#E5E5E5", fg=T.TEXT, font=T.FONT_BTN_SM, padx=12, pady=7
        )

    def _card(self, parent) -> Frame:
        wrap = Frame(parent, bg=T.BORDER, padx=1, pady=1)
        inner = Frame(wrap, bg=T.CARD, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        wrap._inner = inner  # type: ignore[attr-defined]
        return wrap

    def _configure_ttk(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=T.BG)
        style.configure("TLabel", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.configure("TRadiobutton", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.configure("TEntry", fieldbackground="#FFFFFF", foreground=T.TEXT, padding=6)
        style.configure("TCombobox", fieldbackground="#FFFFFF", foreground=T.TEXT, padding=4)
        style.configure(
            "XHS.Horizontal.TProgressbar",
            troughcolor=T.TRACK,
            background=T.RED,
            bordercolor=T.BORDER,
            lightcolor=T.RED,
            darkcolor=T.RED_DARK,
            thickness=16,
        )
        style.configure("TCheckbutton", background=T.CARD, foreground=T.TEXT, font=T.FONT_UI)
        style.map("TCheckbutton", background=[("active", T.CARD)])
        style.map("TRadiobutton", background=[("active", T.CARD)])

    def _build_ui(self) -> None:
        self._configure_ttk()
        shell = Frame(self.root, bg=T.BG)
        shell.pack(fill="both", expand=True)

        # bottom dock
        dock = Frame(shell, bg=T.CARD, padx=16, pady=12)
        dock.pack(side="bottom", fill="x")
        Frame(shell, bg=T.BORDER, height=1).pack(side="bottom", fill="x")
        Label(dock, textvariable=self.status_var, bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB, anchor="w").pack(fill="x")
        self.progress = ttk.Progressbar(dock, mode="determinate", maximum=100, style="XHS.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(6, 10))
        actions = Frame(dock, bg=T.CARD)
        actions.pack(fill="x")
        self.btn_download = self._accent_button(actions, "开始下载", self.on_download, padx=22)
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

        # header
        head = Frame(shell, bg=T.RED, height=72)
        head.pack(side="top", fill="x")
        head.pack_propagate(False)
        hi = Frame(head, bg=T.RED, padx=18, pady=12)
        hi.pack(fill="both", expand=True)
        Label(hi, text="LinkFetch", bg=T.RED, fg="#FFFFFF", font=T.FONT_TITLE).pack(side="left", anchor="w")
        Label(hi, text="  支持 B站 · 抖音 · 小红书", bg=T.RED, fg="#FFE4E8", font=T.FONT_SUB).pack(
            side="left", anchor="s", pady=(0, 4)
        )
        Label(hi, text=f"v{__version__}", bg=T.RED, fg="#FFFFFF", font=T.FONT_UI_BOLD).pack(side="right")

        body = Frame(shell, bg=T.BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        # mode switch (separated features)
        mode_card = self._card(body)
        mode_card.pack(fill="x", pady=(0, 8))
        mc = mode_card._inner  # type: ignore[attr-defined]
        Label(mc, text="功能模式（互不混用）", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).pack(anchor="w")
        row = Frame(mc, bg=T.CARD)
        row.pack(anchor="w", pady=(8, 0))
        self._mode_btns: dict[str, object] = {}
        for key, label in (
            ("single", "单链接"),
            ("images", "图文笔记（小红书）"),
            ("batch", "合集/主页（勾选下载）"),
        ):
            btn = self._accent_button(
                row,
                label,
                lambda k=key: self._select_mode(k),
                bg="#F0F0F0",
                hover="#E5E5E5",
                fg=T.TEXT,
                font=T.FONT_BTN_SM,
                padx=14,
                pady=8,
            )
            btn.pack(side="left", padx=(0, 8))
            self._mode_btns[key] = btn
        Label(mc, textvariable=self.hint_var, bg=T.CARD, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(
            anchor="w", pady=(8, 0)
        )

        # url
        url_card = self._card(body)
        url_card.pack(fill="x", pady=(0, 8))
        ui = url_card._inner  # type: ignore[attr-defined]
        Label(ui, text="链接 / 分享文案（可拖拽到此窗口）", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).pack(anchor="w")
        url_row = Frame(ui, bg=T.CARD)
        url_row.pack(fill="x", pady=(8, 0))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=T.FONT_UI)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=3)
        self.btn_parse = self._accent_button(url_row, "解析", self.on_parse, font=T.FONT_BTN_SM, padx=14, pady=6)
        self.btn_parse.pack(side="left", padx=(0, 6))
        self._ghost_button(url_row, "粘贴", self.on_paste).pack(side="left")

        # options
        opt_card = self._card(body)
        opt_card.pack(fill="x", pady=(0, 8))
        self.opt = opt_card._inner  # type: ignore[attr-defined]
        Label(self.opt, text="下载选项", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        Label(self.opt, text="下载目录", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(row=1, column=0, sticky="w")
        ttk.Entry(self.opt, textvariable=self.outdir_var).grid(row=1, column=1, sticky="we", padx=8)
        self._ghost_button(self.opt, "浏览", self.on_browse).grid(row=1, column=2)
        Label(self.opt, text="Cookie 文件", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(
            row=2, column=0, sticky="w", pady=8
        )
        ttk.Entry(self.opt, textvariable=self.cookies_file_var).grid(row=2, column=1, sticky="we", padx=8, pady=8)
        self._ghost_button(self.opt, "选择", self.on_browse_cookies).grid(row=2, column=2, pady=8)
        Label(self.opt, text="Cookie 来源", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(row=3, column=0, sticky="w")
        ttk.Combobox(
            self.opt,
            textvariable=self.cookie_browser_var,
            values=["自动", "无", "firefox", "chrome", "edge", "brave"],
            width=14,
            state="readonly",
            font=T.FONT_UI,
        ).grid(row=3, column=1, sticky="w", padx=8)

        self.single_opts = Frame(self.opt, bg=T.CARD)
        self.single_opts.grid(row=4, column=0, columnspan=3, sticky="we", pady=(10, 0))
        Label(self.single_opts, text="单链接附加", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).pack(side="left")
        ttk.Checkbutton(self.single_opts, text="视频", variable=self.want_video).pack(side="left", padx=(12, 8))
        ttk.Checkbutton(self.single_opts, text="另存纯音频", variable=self.want_audio).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(self.single_opts, text="字幕", variable=self.want_subs).pack(side="left")
        self.opt.columnconfigure(1, weight=1)

        # result area
        mid_card = self._card(body)
        mid_card.pack(fill="both", expand=True)
        mid = mid_card._inner  # type: ignore[attr-defined]
        Label(mid, text="解析结果", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).pack(anchor="w")
        self.info_label = Label(
            mid,
            text="尚未解析。",
            bg=T.CARD,
            fg=T.TEXT,
            font=T.FONT_UI,
            justify="left",
            wraplength=800,
            anchor="w",
        )
        self.info_label.pack(anchor="w", fill="x", pady=(8, 0))

        # single format row
        self.fmt_row = Frame(mid, bg=T.CARD)
        self.fmt_row.pack(fill="x", pady=(12, 0))
        Label(self.fmt_row, text="清晰度", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI_BOLD).pack(side="left")
        self.format_box = ttk.Combobox(self.fmt_row, textvariable=self.format_var, state="disabled", font=T.FONT_UI)
        self.format_box.pack(side="left", fill="x", expand=True, padx=(10, 0))

        # selectable list (images / batch)
        self.select_bar = Frame(mid, bg=T.CARD)
        self.select_bar.pack(fill="x", pady=(10, 0))
        self._ghost_button(self.select_bar, "全选", lambda: self._set_all_checks(True)).pack(side="left")
        self._ghost_button(self.select_bar, "全不选", lambda: self._set_all_checks(False)).pack(side="left", padx=8)

        list_wrap = Frame(mid, bg=T.CARD)
        list_wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.check_canvas = ttk.Frame(list_wrap)  # scrollable host
        # Use a simple Listbox companion + check frame via Canvas
        from tkinter import Canvas, Scrollbar

        self._list_canvas = Canvas(list_wrap, bg=T.CARD, highlightthickness=0, height=160)
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

        self.select_bar.pack_forget()
        self._list_canvas.master.pack_forget()  # hide list_wrap initially — fix: pack_forget list_wrap
        self.list_wrap = list_wrap
        self.list_wrap.pack_forget()

        self.on_mode_change()

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
        self.mode_var.set(mode)
        self.on_mode_change()

    def _refresh_mode_buttons(self) -> None:
        cur = self.mode_var.get()
        for key, btn in getattr(self, "_mode_btns", {}).items():
            if key == cur:
                btn.configure(bg=T.RED, fg="#FFFFFF", activebackground=T.RED_HOVER, activeforeground="#FFFFFF")
                # keep hover colors consistent for selected
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=T.RED_HOVER) if str(b["state"]) != "disabled" else None)
                btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=T.RED) if str(b["state"]) != "disabled" else None)
            else:
                btn.configure(bg="#F0F0F0", fg=T.TEXT, activebackground="#E5E5E5", activeforeground=T.TEXT)
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#E5E5E5") if str(b["state"]) != "disabled" else None)
                btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#F0F0F0") if str(b["state"]) != "disabled" else None)

    def on_mode_change(self) -> None:
        mode = self.mode_var.get()
        self._refresh_mode_buttons()
        self.hint_var.set(SITE_HINTS.get(mode, ""))
        self.media = None
        self.batch = None
        self._clear_checks()
        self.info_label.configure(text="尚未解析。切换模式后请重新解析。")
        self.format_var.set("（请先解析）")
        self.format_box.configure(values=[], state="disabled")

        if mode == "single":
            self.single_opts.grid()
            self.fmt_row.pack(fill="x", pady=(12, 0))
            self.select_bar.pack_forget()
            self.list_wrap.pack_forget()
        else:
            self.single_opts.grid_remove()
            self.fmt_row.pack_forget()
            self.select_bar.pack(fill="x", pady=(10, 0))
            self.list_wrap.pack(fill="both", expand=True, pady=(8, 0))

    def _clear_checks(self) -> None:
        for child in self.check_host.winfo_children():
            child.destroy()
        self.image_checks = []
        self.batch_checks = []

    def _set_all_checks(self, value: bool) -> None:
        checks = self.image_checks if self.mode_var.get() == "images" else self.batch_checks
        for v in checks:
            v.set(value)

    def _populate_image_checks(self, media: MediaInfo) -> None:
        self._clear_checks()
        images = list((media.raw or {}).get("image_urls") or [])
        self.image_checks = []
        for i, u in enumerate(images):
            var = BooleanVar(value=True)
            self.image_checks.append(var)
            ttk.Checkbutton(
                self.check_host,
                text=f"图片 {i+1}  ·  {u[:70]}{'…' if len(u)>70 else ''}",
                variable=var,
            ).pack(anchor="w", pady=2)

    def _populate_batch_checks(self, batch: BatchList) -> None:
        self._clear_checks()
        self.batch_checks = []
        for item in batch.items:
            var = BooleanVar(value=True)
            self.batch_checks.append(var)
            title = item.title if len(item.title) <= 60 else item.title[:60] + "…"
            ttk.Checkbutton(
                self.check_host,
                text=f"[{item.index+1}] {title}",
                variable=var,
            ).pack(anchor="w", pady=2)

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

    def on_open_dir(self) -> None:
        path = self.outdir_var.get()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def on_cancel(self) -> None:
        self._cancel = True
        if self.downloader:
            self.downloader.cancel()
        self.status_var.set("正在取消…")

    def on_parse(self) -> None:
        url = self._resolve_input_url()
        if not url:
            messagebox.showwarning("提示", "未识别到有效链接。")
            return
        if self._worker and self._worker.is_alive():
            return

        mode = self.mode_var.get()
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
                    cb = "" if browser in ("", "无", "自动", "auto") else browser
                    batch = extract_batch_list(
                        url,
                        cookies_file=self.cookies_file_var.get().strip(),
                        cookies_from_browser=cb,
                        log=self.log,
                    )
                    self.root.after(0, lambda: self._apply_batch(batch))
                else:
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
        dur = f"{int(info.duration)}s" if info.duration else "未知"
        self.info_label.configure(
            text=f"标题：{info.title}\n平台：{info.extractor or '未知'} · 时长：{dur}"
        )
        formats = [f for f in info.formats if not f.is_audio_only] or info.formats
        if self.want_audio.get() and not self.want_video.get():
            formats = [f for f in info.formats if f.is_audio_only] or formats
        self.format_map = {f.label: f for f in formats}
        labels = [f.label for f in formats] or ["（无可用格式）"]
        self.format_box.configure(values=labels, state="readonly")
        self.format_var.set(labels[0])
        self.status_var.set(f"解析成功：{info.title[:40]}")

    def _apply_images(self, info: MediaInfo) -> None:
        self.media = info
        self.batch = None
        n = len((info.raw or {}).get("image_urls") or [])
        self.info_label.configure(text=f"图文：{info.title}\n共 {n} 张图片（请勾选后下载）")
        self._populate_image_checks(info)
        self.status_var.set(f"图文解析成功：{n} 张")

    def _apply_batch(self, batch: BatchList) -> None:
        self.batch = batch
        self.media = None
        self.info_label.configure(
            text=f"列表：{batch.title}\n平台：{batch.platform} · 共 {len(batch.items)} 条（请勾选后下载）"
        )
        self._populate_batch_checks(batch)
        self.status_var.set(f"列表解析成功：{len(batch.items)} 条")

    def _download_jobs_single(self) -> list[tuple[str, bool, bool]]:
        label = self.format_var.get()
        fmt = self.format_map.get(label)
        base_id = fmt.format_id if fmt else "bv*+ba/b"
        jobs: list[tuple[str, bool, bool]] = []
        if self.want_video.get():
            fid = "bv*+ba/b" if (fmt and fmt.is_audio_only) else base_id
            jobs.append((fid, False, self.want_subs.get()))
        if self.want_audio.get() and not self.want_video.get():
            jobs.append(("ba/b", True, False))
        elif self.want_audio.get() and self.want_video.get():
            jobs.append(("ba/b", True, False))
        if not jobs:
            jobs.append(("bv*+ba/b", False, self.want_subs.get()))
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

        # single
        url = self._resolve_input_url()
        if not self.media and not url:
            messagebox.showwarning("提示", "请先解析单链接。")
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
                for i, item in enumerate(items, 1):
                    if self._cancel:
                        raise KeyboardInterrupt()
                    self.root.after(
                        0,
                        lambda i=i: self.status_var.set(f"批量 {i}/{total}：{item.title[:30]}"),
                    )
                    self.root.after(0, lambda i=i, t=total: self.progress.configure(value=i / t * 100))
                    try:
                        dl.download(
                            item.url,
                            "bv*+ba/b",
                            audio_only=False,
                            write_subs=False,
                            playlist=False,
                            progress_cb=None,
                            media=None,
                        )
                        ok += 1
                    except Exception as e:
                        self.log(f"跳过失败项：{item.title} ({e})")
                self.root.after(0, lambda: self.status_var.set(f"批量完成 {ok}/{total}"))
                self.root.after(
                    0,
                    lambda: messagebox.showinfo("完成", f"完成 {ok}/{total} 条\n目录：{dl.outdir}"),
                )
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
