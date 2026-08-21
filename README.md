# LinkFetch

Windows 桌面视频 / 图文下载器（Python 3.12 + yt-dlp + f2 + Playwright/Edge + tkinter）。

当前版本：**v1.7.3**

## 功能概览

三种工作模式（左侧导航）：

| 模式 | 用途 |
|------|------|
| **单链接** | 粘贴一条分享文案或链接 → 解析标题 / 清晰度 → 下载视频、纯音频、字幕 |
| **图文** | 仅小红书图集笔记 → 勾选图片保存 |
| **合集主页** | B站合集/空间、抖音主页/`collection`、小红书作者主页 → 勾选后批量下载 |

其它能力：

- 拖拽分享文案到窗口自动提取链接
- Cookie：文件 / 浏览器自动探测 / **扫码登录**（小红书、抖音）
- 合集列表卡片展示：封面、标题、发布时间、赞/藏/评
- 一键筛选勾选：全部 / 图文 / 视频
- 下载目录可配置；进度条与取消

## 平台通道

| 平台 | 通道 |
|------|------|
| B站 / YouTube / 通用 | yt-dlp |
| 抖音 | **f2** 签名 API + Edge 拦截备用；合集用 f2 拉作品列表 |
| 小红书 | Edge 会话 + yt-dlp / 媒体拦截；**主页列表需扫码登录**（写入下载目录下的 `edge_profile_xhs`） |

### 小红书合集主页用法

1. 下载目录设为例如 `C:\Users\你\Downloads\LinkFetch`
2. 点击 **扫码登录** → 选小红书 → 手机 App 扫码
3. 粘贴作者主页短链（如 `xhslink.cn/...`）→ **合集主页** → 解析
4. 用「全部 / 图文 / 视频」勾选后下载

扫码会生成：

- `cookies_xhs.txt`（Cookie 文件）
- `edge_profile_xhs/`（登录档案，主页列表必需；约数十～上百 MB，可删后重扫）

## 环境

### 发给别人的 exe（推荐）

对方**不需要**装 Python / ffmpeg / pip。只需：

- Windows 10/11
- 本机有 **Microsoft Edge**（抖音/小红书通道会用到）

### 源码开发

- Python 3.10+（推荐 3.12）
- `pip install -r requirements.txt`
- Microsoft Edge

## 安装与运行（开发）

```bash
cd LinkFetch
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m playwright install
python main.py
```

## 打包成 exe

```bash
build_exe.bat
```

生成：`dist\LinkFetch.exe`（单文件分发）。

已打进包的大致包括：Python 运行时、yt-dlp、f2、httpx、Playwright、ffmpeg、Pillow、tkinterdnd2 等。

对方仍需：Windows 10/11 + Microsoft Edge。首次启动单文件解压会稍慢。

## 使用提示

1. **B站**：合集/空间链接走合集主页；单条走单链接。大会员清晰度需自备已登录 Cookie。
2. **抖音**：短链或 `douyin.com/video/...` / `user/...` / `collection/...`。
3. **小红书**：单条尽量用带 `xsec_token` 的完整链接；主页批量务必先扫码登录。
4. Windows 上直接读 Chrome/Edge Cookie 常因 DPAPI 失败——优先用「扫码登录」或导出 Netscape `cookies.txt`。
5. 请仅下载你有权获取的内容，并遵守平台条款与版权法规。

## 目录结构

```text
LinkFetch/
  main.py
  linkfetch/
    app.py              # 主界面
    batch_channel.py    # 合集/主页列表
    downloader.py       # yt-dlp 通用下载
    douyin_channel.py   # 抖音通道
    xhs_channel.py      # 小红书通道
    edge_session.py     # Edge / 扫码登录
    platforms.py        # 链接识别
    ...
  requirements.txt
  linkfetch.spec
  build_exe.bat
  README.md
```

## 体积说明

- 源码很小；`LinkFetch.exe` 因内置依赖体积较大（约数百 MB）属正常。
- 本机下载目录会积累视频与 `edge_profile_xhs` 缓存；档案异常时可删除后重新扫码。

## 许可与声明

本项目仅供学习与个人合规使用。请勿用于未授权批量抓取或侵犯版权的用途。
