@echo off
setlocal
cd /d "%~dp0"
python -m demo.web --open
if errorlevel 1 (
  echo.
  echo Unable to start. Install Python 3.10+ and OpenSSL, then retry.
  pause
)
