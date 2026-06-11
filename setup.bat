@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   TruePeopleSearch Scraper - one-time setup
echo ============================================================
echo.

REM --- Find a compatible Python (3.10 - 3.13). 3.14+ is too new: a required
REM     dependency (greenlet) has no installer for it and would need a C++
REM     compiler to build from source. ---
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PYEXE (
      py -%%V -c "import sys" >nul 2>nul && set "PYEXE=py -%%V"
    )
  )
)

REM Fall back to plain 'python' only if it is in the 3.10-3.13 range.
if not defined PYEXE (
  for /f "delims=" %%P in ('python -c "import sys;print(1 if (3,10)<=sys.version_info<(3,14) else 0)" 2^>nul') do set "PYOK=%%P"
  if "!PYOK!"=="1" set "PYEXE=python"
)

if not defined PYEXE (
  echo [ERROR] No compatible Python was found.
  echo.
  echo This tool needs Python 3.10, 3.11, 3.12, or 3.13.
  echo Python 3.14 is currently too new ^(a dependency has no installer for it^).
  echo.
  echo Please install Python 3.12 from:
  echo    https://www.python.org/downloads/
  echo tick "Add python.exe to PATH" during install, then run setup.bat again.
  echo.
  pause
  exit /b 1
)

echo Using Python: !PYEXE!
!PYEXE! --version
echo.

REM Start clean if a previous (possibly broken) environment exists.
if exist ".venv" (
  echo Removing previous environment...
  rmdir /s /q ".venv"
)

echo Creating a private environment (.venv)...
!PYEXE! -m venv .venv
if errorlevel 1 (
  echo [ERROR] Could not create the environment. & pause & exit /b 1
)

echo Installing the program and its dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install .
if errorlevel 1 (
  echo [ERROR] Dependency installation failed. & pause & exit /b 1
)

echo Installing the Chromium browser used for scraping...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo [ERROR] Browser installation failed. & pause & exit /b 1
)

echo.
echo ============================================================
echo   Setup complete!
echo.
echo   Run the scraper from this folder, for example:
echo     .venv\Scripts\python.exe -m web_crawler --input input.csv ^
echo         --proxy p.webshare.io:80 --skip-vpn-check --start 1 --end 5
echo.
echo   See  python -m web_crawler --help  for all options.
echo ============================================================
pause
