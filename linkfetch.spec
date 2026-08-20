# -*- mode: python ; coding: utf-8 -*-
# One-file build: all runtime deps (Python + ffmpeg + playwright driver) inside LinkFetch.exe

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Packages that ship data/binaries or need full collection for frozen exe
COLLECT_PACKAGES = [
    "yt_dlp",
    "f2",
    "playwright",
    "tkinterdnd2",
    "imageio_ffmpeg",
    "httpx",
    "certifi",
    "curl_cffi",
    "mutagen",
    "brotli",
    "browser_cookie3",
    "Cryptodome",
    "cryptography",
    "greenlet",
]

datas = [("assets", "assets")]
binaries = []
hiddenimports = [
    "yt_dlp",
    "f2",
    "playwright",
    "playwright.sync_api",
    "httpx",
    "tkinterdnd2",
    "imageio_ffmpeg",
    "browser_cookie3",
    "mutagen",
    "brotli",
    "curl_cffi",
    "Cryptodome",
    "certifi",
    "websockets",
]

for pkg in COLLECT_PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LinkFetch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["ffmpeg", "node", "playwright"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/linkfetch.ico",
)
