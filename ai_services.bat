@echo off
rem ============================================================================
rem  rt-thread-ros ai_services.bat -- launcher for humans ONLY (thin shell).
rem
rem  The command table lives in scripts\ai_services.py (the SERVICES tuple).
rem  This file only picks a usable python and forwards every argument verbatim.
rem  To add/remove/rename a service, edit that python file -- not this bat.
rem
rem  Usage (double-click with no argument = interactive menu):
rem    ai_services.bat                  interactive menu
rem    ai_services.bat status           run one entry by name or key
rem    ai_services.bat --list           print the command table
rem    ai_services.bat hub COM5 9600    extra args are forwarded verbatim
rem
rem  Constraints (learned the hard way): ASCII ONLY + CRLF ONLY. cmd.exe parses a
rem  .bat byte by byte: UTF-8 Chinese text gets mangled, and LF-only line endings
rem  break goto/label parsing (it can loop forever).
rem ============================================================================
setlocal
set "REPO=%~dp0"
cd /d "%REPO%"

set "VENV_PY=E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe"
set "PY313=E:\software\InstallerEdition\DevTools\Python\Python313\python.exe"

rem console to UTF-8 so python's Chinese output is readable; do not pin the
rem child's encoding beyond this (scripts set what their own children need)
chcp 65001 >nul
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONIOENCODING=utf-8"

call :probe_py
if not defined PY goto :no_python

"%PY%" "%REPO%scripts\ai_services.py" %*
set "RC=%ERRORLEVEL%"

if "%~1"=="" if not defined AI_SERVICES_NOPAUSE (
    echo.
    echo [done] exit code %RC% -- press any key to close
    pause >nul
)
exit /b %RC%

rem ---- helpers ---------------------------------------------------------------
:probe_py
set "PY="
call :try_py "python"
if defined PY goto :eof
call :try_py "%PY313%"
if defined PY goto :eof
call :try_py "%VENV_PY%"
goto :eof

:try_py
if "%~1"=="" goto :eof
if /i not "%~1"=="python" if not exist "%~1" goto :eof
"%~1" -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

:no_python
echo [ERROR] no usable python found. tried: python, %PY313%, %VENV_PY%
echo         install Python 3.11+ or edit PY313 / VENV_PY at the top of this file.
if not defined AI_SERVICES_NOPAUSE pause
exit /b 1
