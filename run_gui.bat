@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] The program is not set up yet.
  echo Please double-click  setup.bat  first ^(only needed once^).
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m web_crawler.gui
if errorlevel 1 (
  echo.
  echo The program closed with an error. Take a screenshot of the messages
  echo above and send it for support.
  pause
)
