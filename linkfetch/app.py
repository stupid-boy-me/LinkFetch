"""LinkFetch desktop GUI — Xiaohongshu-inspired red/white layout."""

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
    Tk,
    filedialog,
    messagebox,
    ttk,
)
from typing import Optional

from linkfetch import __app_name__, __version__
from linkfetch import theme as T
from linkfetch.downloader import (
    Downloader,
    FormatOption,
    MediaInfo,
    extract_share_url,
    looks_like_url,
)


SITE_HINT = "粘贴整段分享文案即可，自动识别抖音 / 小红书 / B站链接。"


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
            "2. 导出已登录抖音的 cookies.txt 放到软件目录；\n"
            "3. 本机需已安装 Microsoft Edge（拦截备用通道）。\n\n"
            f"原始错误：{text}"
        )
    if is_xhs_url(url) or "XiaoHongShu" in text or "xiaohongshu" in text.lower():
        return (
            "小红书解析/下载失败。\n\n"
            "建议：\n"
            "1. 使用带 xsec_token 的完整分享链接；\n"
            "2. 导出已登录小红书的 cookies.txt；\n"
            "3. 确认本机已安装 Edge（用于自动访客会话）。\n\n"
            f"原始错误：{text}"
        )
    if "DPAPI" in text or "decrypt" in text.lower() or "10927" in text:
        return (
            "读取 Chrome/Edge Cookie 失败（Windows DPAPI / 应用绑定加密）。\n\n"
            "请任选一种办法：\n"
            "1. 【推荐】用浏览器扩展导出 Netscape 格式 cookies.txt，"
            "放到软件目录或下载目录，Cookie 来源保持「自动」；\n"
            "2. Cookie 来源改选 firefox（先在 Firefox 打开并登录站点）；\n"
            "3. 完全退出 Chrome/Edge 后再试（有时仍会失败）。\n\n"
            f"原始错误：{text}"
        )
    return text


class LinkFetchApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title(f"{__app_name__} v{__version__}")
        self.root.geometry("880x620")
        self.root.minsize(720, 520)
        self.root.configure(bg=T.BG)

        self._photo_icon = None
        self._set_window_icon()

        self.media: Optional[MediaInfo] = None
        self.downloader: Optional[Downloader] = None
        self._worker: Optional[threading.Thread] = None

        default_dir = os.path.join(os.path.expanduser("~"), "Downloads", "LinkFetch")
        os.makedirs(default_dir, exist_ok=True)

        self.url_var = StringVar()
        self.outdir_var = StringVar(value=default_dir)
        self.cookie_browser_var = StringVar(value="自动")
        self.cookies_file_var = StringVar(value="")
        self.want_video = BooleanVar(value=True)
        self.want_audio = BooleanVar(value=False)  # 默认不另存纯音频；视频本身已含音轨
        self.want_subs = BooleanVar(value=True)
        self.playlist_var = BooleanVar(value=True)
        self.format_var = StringVar(value="（请先解析）")
        self.format_map: dict[str, FormatOption] = {}
        self.status_var = StringVar(value="就绪")

        self._build_ui()

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

    def _accent_button(
        self,
        parent,
        text: str,
        command,
        *,
        bg: str = T.RED,
        hover: str = T.RED_HOVER,
        fg: str = "#FFFFFF",
        font=T.FONT_BTN,
        padx: int = 16,
        pady: int = 7,
    ):
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

        def on_enter(_e) -> None:
            if str(btn["state"]) != "disabled":
                btn.configure(bg=hover)

        def on_leave(_e) -> None:
            if str(btn["state"]) != "disabled":
                btn.configure(bg=bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def _ghost_button(self, parent, text: str, command):
        return self._accent_button(
            parent,
            text,
            command,
            bg="#F0F0F0",
            hover="#E5E5E5",
            fg=T.TEXT,
            font=T.FONT_BTN_SM,
            padx=12,
            pady=7,
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

    def _build_ui(self) -> None:
        self._configure_ttk()

        shell = Frame(self.root, bg=T.BG)
        shell.pack(fill="both", expand=True)

        # —— 固定底栏：进度条 + 操作按钮（大/小窗口都在）——
        dock = Frame(shell, bg=T.CARD, padx=16, pady=12)
        dock.pack(side="bottom", fill="x")
        Frame(shell, bg=T.BORDER, height=1).pack(side="bottom", fill="x")

        Label(
            dock,
            textvariable=self.status_var,
            bg=T.CARD,
            fg=T.TEXT_MUTED,
            font=T.FONT_SUB,
            anchor="w",
        ).pack(fill="x")
        self.progress = ttk.Progressbar(
            dock,
            mode="determinate",
            maximum=100,
            style="XHS.Horizontal.TProgressbar",
        )
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
            lambda: webbrowser.open(
                "https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"
            ),
        ).pack(side="right")

        # —— 顶栏：小红书红 ——
        head = Frame(shell, bg=T.RED, height=72)
        head.pack(side="top", fill="x")
        head.pack_propagate(False)
        head_inner = Frame(head, bg=T.RED, padx=18, pady=12)
        head_inner.pack(fill="both", expand=True)
        Label(
            head_inner,
            text="LinkFetch",
            bg=T.RED,
            fg="#FFFFFF",
            font=T.FONT_TITLE,
        ).pack(side="left", anchor="w")
        Label(
            head_inner,
            text="  支持 B站 · 抖音 · 小红书",
            bg=T.RED,
            fg="#FFE4E8",
            font=T.FONT_SUB,
        ).pack(side="left", anchor="s", pady=(0, 4))
        Label(
            head_inner,
            text=f"v{__version__}",
            bg=T.RED,
            fg="#FFFFFF",
            font=T.FONT_UI_BOLD,
        ).pack(side="right", anchor="e")

        # —— 中间可伸缩内容 ——
        body = Frame(shell, bg=T.BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        Label(body, text=SITE_HINT, bg=T.BG, fg=T.TEXT_MUTED, font=T.FONT_SUB).pack(
            anchor="w", pady=(0, 8)
        )

        # 链接
        url_card = self._card(body)
        url_card.pack(fill="x", pady=(0, 8))
        url_inner = url_card._inner  # type: ignore[attr-defined]
        Label(
            url_inner,
            text="链接 / 分享文案",
            bg=T.CARD,
            fg=T.RED,
            font=T.FONT_UI_BOLD,
        ).pack(anchor="w")
        url_row = Frame(url_inner, bg=T.CARD)
        url_row.pack(fill="x", pady=(8, 0))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=T.FONT_UI)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=3)
        self.btn_parse = self._accent_button(
            url_row, "解析", self.on_parse, font=T.FONT_BTN_SM, padx=14, pady=6
        )
        self.btn_parse.pack(side="left", padx=(0, 6))
        self._ghost_button(url_row, "粘贴", self.on_paste).pack(side="left")

        # 选项
        opt_card = self._card(body)
        opt_card.pack(fill="x", pady=(0, 8))
        opt = opt_card._inner  # type: ignore[attr-defined]
        Label(opt, text="下载选项", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        Label(opt, text="下载目录", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Entry(opt, textvariable=self.outdir_var).grid(row=1, column=1, sticky="we", padx=8)
        self._ghost_button(opt, "浏览", self.on_browse).grid(row=1, column=2)

        Label(opt, text="Cookie 文件", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(
            row=2, column=0, sticky="w", pady=8
        )
        ttk.Entry(opt, textvariable=self.cookies_file_var).grid(
            row=2, column=1, sticky="we", padx=8, pady=8
        )
        self._ghost_button(opt, "选择", self.on_browse_cookies).grid(row=2, column=2, pady=8)

        Label(opt, text="Cookie 来源", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(
            row=3, column=0, sticky="w"
        )
        ttk.Combobox(
            opt,
            textvariable=self.cookie_browser_var,
            values=["自动", "无", "firefox", "chrome", "edge", "brave"],
            width=14,
            state="readonly",
            font=T.FONT_UI,
        ).grid(row=3, column=1, sticky="w", padx=8)

        Label(opt, text="默认下载", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI).grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        defs = Frame(opt, bg=T.CARD)
        defs.grid(row=4, column=1, columnspan=2, sticky="w", padx=8, pady=(10, 0))
        ttk.Checkbutton(defs, text="视频", variable=self.want_video).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(defs, text="另存纯音频(.m4a)", variable=self.want_audio).pack(
            side="left", padx=(0, 12)
        )
        ttk.Checkbutton(defs, text="字幕", variable=self.want_subs).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(defs, text="播放列表批量", variable=self.playlist_var).pack(side="left")
        Label(
            opt,
            text="说明：勾选「视频」会下载含音轨的 mp4；只有勾选「另存纯音频」才会多出一个 .m4a",
            bg=T.CARD,
            fg=T.TEXT_MUTED,
            font=T.FONT_SUB,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        opt.columnconfigure(1, weight=1)

        # 结果
        mid_card = self._card(body)
        mid_card.pack(fill="both", expand=True)
        mid = mid_card._inner  # type: ignore[attr-defined]
        Label(mid, text="解析结果", bg=T.CARD, fg=T.RED, font=T.FONT_UI_BOLD).pack(anchor="w")
        self.info_label = Label(
            mid,
            text="尚未解析。粘贴链接或分享文案后点击「解析」。",
            bg=T.CARD,
            fg=T.TEXT,
            font=T.FONT_UI,
            justify="left",
            wraplength=780,
            anchor="w",
        )
        self.info_label.pack(anchor="w", fill="x", pady=(8, 0))

        fmt_row = Frame(mid, bg=T.CARD)
        fmt_row.pack(fill="x", pady=(14, 0))
        Label(fmt_row, text="清晰度", bg=T.CARD, fg=T.TEXT, font=T.FONT_UI_BOLD).pack(side="left")
        self.format_box = ttk.Combobox(
            fmt_row,
            textvariable=self.format_var,
            state="disabled",
            font=T.FONT_UI,
        )
        self.format_box.pack(side="left", fill="x", expand=True, padx=(10, 0))

    def run(self) -> None:
        self.root.mainloop()

    def log(self, msg: str) -> None:
        # 主界面不展示日志；仅更新状态行关键信息
        short = (msg or "").strip().replace("\n", " ")
        if not short:
            return
        if any(k in short for k in ("解析", "下载", "完成", "失败", "取消", "提取链接")):
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
        cookies_file = self.cookies_file_var.get().strip()
        return Downloader(
            outdir=self.outdir_var.get().strip() or os.getcwd(),
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            auto_cookies=auto,
            log_cb=self.log,
        )

    def _resolve_input_url(self, raw: str = "") -> str:
        text = (raw or self.url_var.get() or "").strip()
        if not text:
            return ""
        url = extract_share_url(text)
        if not url and looks_like_url(text):
            url = text.split()[0].strip()
        if url and url != text:
            self.url_var.set(url)
            self.log(f"已从分享文案提取链接：{url}")
        elif url:
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
        if self.downloader:
            self.downloader.cancel()
            self.status_var.set("正在取消…")

    def on_parse(self) -> None:
        url = self._resolve_input_url()
        if not url:
            messagebox.showwarning(
                "提示",
                "未识别到有效链接。\n可直接粘贴抖音 / 小红书 / B站分享的整段文字。",
            )
            return
        if self._worker and self._worker.is_alive():
            return

        self.set_busy(True)
        self.status_var.set(f"解析中…")
        self.progress["value"] = 0

        def work() -> None:
            try:
                dl = self._make_downloader()
                self.downloader = dl
                info = dl.extract(url, process_playlist=self.playlist_var.get())
                self.root.after(0, lambda: self._apply_info(info))
            except Exception as e:
                tip = friendly_cookie_error(e, url)
                self.root.after(0, lambda: messagebox.showerror("解析失败", tip))
                self.root.after(0, lambda: self.status_var.set("解析失败"))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _apply_info(self, info: MediaInfo) -> None:
        self.media = info
        if info.is_playlist:
            text = (
                f"播放列表：{info.title}\n"
                f"平台：{info.extractor or '未知'} · 条目约 {info.playlist_count} 个"
            )
        else:
            dur = f"{int(info.duration)}s" if info.duration else "未知"
            subs = ", ".join(info.subtitles[:8]) or "无"
            text = (
                f"标题：{info.title}\n"
                f"平台：{info.extractor or '未知'} · 时长：{dur} · 字幕：{subs}"
            )
        self.info_label.configure(text=text)

        formats = [f for f in info.formats if not f.is_audio_only] or info.formats
        # 若默认只要音频，优先音频格式
        if self.want_audio.get() and not self.want_video.get():
            formats = [f for f in info.formats if f.is_audio_only] or formats

        self.format_map = {f.label: f for f in formats}
        labels = [f.label for f in formats] or ["（无可用格式）"]
        self.format_box.configure(values=labels, state="readonly")
        self.format_var.set(labels[0])
        self.status_var.set(f"解析成功：{info.title[:40]}")

    def _download_jobs(self) -> list[tuple[str, bool, bool]]:
        """Returns list of (format_id, audio_only, write_subs)."""
        label = self.format_var.get()
        fmt = self.format_map.get(label)
        base_id = fmt.format_id if fmt else "bv*+ba/b"
        want_v = self.want_video.get()
        want_a = self.want_audio.get()
        want_s = self.want_subs.get()
        jobs: list[tuple[str, bool, bool]] = []

        if want_v:
            fid = base_id
            if fmt and fmt.is_audio_only:
                fid = "bv*+ba/b"
            jobs.append((fid, False, want_s))
        if want_a and not want_v:
            jobs.append(("ba/b", True, False))
        elif want_a and want_v:
            # 额外再导出一份纯音频
            jobs.append(("ba/b", True, False))
        if not jobs:
            jobs.append(("bv*+ba/b", False, want_s))
        return jobs

    def on_download(self) -> None:
        url = self._resolve_input_url()
        if not self.media and not url:
            messagebox.showwarning("提示", "请先解析，或粘贴含链接的分享文案。")
            return
        if self._worker and self._worker.is_alive():
            return
        if not (self.want_video.get() or self.want_audio.get()):
            messagebox.showwarning("提示", "请至少勾选「视频」或「音频」。")
            return

        playlist = bool(self.media and self.media.is_playlist and self.playlist_var.get())
        sub_langs = (self.media.subtitles[:6] if self.media else None) or [
            "zh-Hans",
            "zh-CN",
            "zh",
            "en",
        ]
        jobs = self._download_jobs()

        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set("准备下载…")

        def work() -> None:
            try:
                dl = self._make_downloader()
                self.downloader = dl

                def on_progress(d: dict) -> None:
                    status = d.get("status")
                    if status == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        done = d.get("downloaded_bytes") or 0
                        pct = (done / total * 100) if total else 0.0
                        speed = d.get("speed") or 0
                        eta = d.get("eta")
                        speed_s = f"{speed/1024/1024:.2f} MB/s" if speed else "—"
                        eta_s = f"{eta}s" if eta is not None else "—"
                        self.root.after(0, lambda: self.progress.configure(value=min(pct, 100)))
                        self.root.after(
                            0,
                            lambda: self.status_var.set(
                                f"下载中 {pct:.1f}% · {speed_s} · ETA {eta_s}"
                            ),
                        )
                    elif status == "finished":
                        self.root.after(0, lambda: self.progress.configure(value=100))
                        self.root.after(0, lambda: self.status_var.set("处理中…"))

                target = self.media.url if self.media else url
                for i, (format_id, audio_only, write_subs) in enumerate(jobs, 1):
                    self.root.after(
                        0,
                        lambda i=i: self.status_var.set(f"任务 {i}/{len(jobs)}…"),
                    )
                    dl.download(
                        target,
                        format_id,
                        audio_only=audio_only,
                        write_subs=write_subs,
                        sub_langs=sub_langs,
                        playlist=playlist,
                        progress_cb=on_progress,
                        media=self.media,
                    )
                self.root.after(0, lambda: self.status_var.set("下载完成"))
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "完成", f"下载完成！\n文件保存在：\n{dl.outdir}"
                    ),
                )
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


def run() -> None:
    LinkFetchApp().run()
