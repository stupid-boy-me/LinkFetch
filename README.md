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

- Windows 10/11
- Python 3.10+（推荐官网 Windows 安装包）
- 已安装 **Microsoft Edge**（抖音/小红书备用拦截依赖它，无需再下 Chromium）
- 建议安装 [ffmpeg](https://ffmpeg.org/) 并加入 PATH（合并音视频、抽音频需要）

## 安装与运行

```bash
cd E:\AI\LinkFetch
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python main.py
```

## 打包成 exe

```bash
build_exe.bat
```

生成：`dist\LinkFetch\LinkFetch.exe`（可连同 `_internal` 文件夹一起分发）。

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
