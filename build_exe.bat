@echo off
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=.venv\bin\python.exe
if not exist "%PY%" set PY=python

echo Using: %PY%

if not exist ".venv\Scripts\python.exe" if not exist ".venv\bin\python.exe" (
  echo [1/5] Creating venv ...
  python -m venv .venv
  set PY=.venv\Scripts\python.exe
  if not exist "%PY%" set PY=.venv\bin\python.exe
)

echo [2/5] Installing ALL runtime + build dependencies ...
"%PY%" -m pip install -U pip
"%PY%" -m pip install -r requirements.txt

echo [3/5] Verifying bundled deps (ffmpeg / yt-dlp / playwright / ...) ...
"%PY%" -c "from linkfetch.deps_check import summary_text; print(summary_text())"
if errorlevel 1 (
  echo Dependency check failed.
  exit /b 1
)

echo [4/5] Building ONE-FILE exe (all Python deps + ffmpeg inside) ...
"%PY%" -m PyInstaller --noconfirm --clean linkfetch.spec
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo [5/5] Done.
echo.
echo Distribute ONLY: dist\LinkFetch.exe
echo Bundled: Python runtime, yt-dlp, f2, ffmpeg, playwright driver, httpx, ...
echo System still needed: Windows 10/11 + Microsoft Edge (Douyin/XHS fallback)
echo.
if exist "dist\LinkFetch.exe" (
  dir dist\LinkFetch.exe
  explorer dist
)
endlocal
