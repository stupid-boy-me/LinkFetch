# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ydl_datas, ydl_binaries, ydl_hidden = collect_all('yt_dlp')
f2_datas, f2_binaries, f2_hidden = collect_all('f2')
pw_datas, pw_binaries, pw_hidden = collect_all('playwright')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=ydl_binaries + f2_binaries + pw_binaries,
    datas=ydl_datas + f2_datas + pw_datas + [('assets', 'assets')],
    hiddenimports=['yt_dlp', 'f2', 'playwright', 'httpx'] + ydl_hidden + f2_hidden + pw_hidden,
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
    [],
    exclude_binaries=True,
    name='LinkFetch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/linkfetch.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LinkFetch',
)
