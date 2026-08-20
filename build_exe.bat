@echo off
setlocal
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=.venv\bin\python.exe
if not exist "%PY%" set PY=python

echo Using: %PY%

if not exist ".venv\Scripts\python.exe" if not exist ".venv\bin\python.exe" (
  echo [1/4] Creating venv ...
  python -m venv .venv
  set PY=.venv\Scripts\python.exe
  if not exist "%PY%" set PY=.venv\bin\python.exe
)

echo [2/4] Installing dependencies ...
"%PY%" -m pip install -U pip
"%PY%" -m pip install -r requirements.txt

echo [3/4] Building exe with PyInstaller ...
"%PY%" -m PyInstaller --noconfirm linkfetch.spec

echo [4/4] Done.
echo Output: dist\LinkFetch\LinkFetch.exe
if exist "dist\LinkFetch" explorer dist\LinkFetch
endlocal
