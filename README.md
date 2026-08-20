# LinkFetch

简洁的桌面视频下载器（Python + yt-dlp + 抖音/小红书专用通道 + tkinter）。

## 功能（第一版 A+B）

- 粘贴链接 → 解析标题 / 清晰度 / 字幕 / 音频
- 一键下载视频、仅音频、字幕
- 播放列表批量下载（通用站点）
- 选择下载目录、进度显示、取消
- Cookie 自动探测（cookies.txt / Firefox / Edge / Chrome）

### 平台通道

| 平台 | 通道 |
|------|------|
| B站 / YouTube / 通用 | yt-dlp |
| 抖音 | **f2 签名 API**（访客 ttwid/msToken）+ 系统 Edge 拦截备用 |
| 小红书 | Edge 自动访客会话 + **yt-dlp** + Edge 媒体拦截备用 |

## 环境

### 发给别人的 exe（推荐）

对方**不需要**装 Python / ffmpeg / pip 依赖。只需：

- Windows 10/11
- 本机有 **Microsoft Edge**（抖音/小红书备用通道用系统 Edge，不随包附带浏览器）

### 源码开发

- Python 3.10+
- `pip install -r requirements.txt`（含 ffmpeg 二进制、yt-dlp 扩展等）
- Microsoft Edge

## 安装与运行（开发）

```bash
cd E:\AI\LinkFetch
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python main.py
```

## 打包成 exe（单文件，可直接发给别人）

```bash
build_exe.bat
```

生成：**`dist\LinkFetch.exe`**（一个文件即可分发）。

**已打进 exe 的依赖（对方不用再装）：**
- Python 运行时、yt-dlp、f2、httpx、playwright 驱动
- ffmpeg（合并音视频）
- mutagen / brotli / curl_cffi 等 yt-dlp 常用扩展
- tkinterdnd2（拖拽）等

**对方仍需自备：**
- Windows 10/11
- Microsoft Edge（仅抖音/小红书备用通道）
- 首次启动会稍慢（单文件解压到临时目录）

## 使用提示

1. **B站 / YouTube**：多数情况可直接解析。
2. **抖音**：粘贴 `v.douyin.com` 或 `www.douyin.com/video/...` 即可；一般无需登录。失败时放 `cookies.txt`。
3. **小红书**：尽量用带 `xsec_token` 的完整分享链接；程序会自动用 Edge 拿访客 `web_session`。
4. Chrome/Edge 直接读 Cookie 在 Windows 上常因 DPAPI 失败——用扩展导出 Netscape `cookies.txt` 更稳。
5. 请仅下载你有权获取的内容，并遵守平台条款与版权法规。

## 目录结构

```text
LinkFetch/
  main.py
  linkfetch/
    app.py
    downloader.py
    douyin_channel.py
    xhs_channel.py
    edge_session.py
    ...
  requirements.txt
  linkfetch.spec
  build_exe.bat
  README.md
```
