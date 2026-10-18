@echo off
rem ============================================================================
rem  rt-thread-ros ai_services.bat -- launcher for humans ONLY.
rem
rem  Purpose : this file exists so a HUMAN can double-click one thing and get
rem            the helper services running. It is a thin wrapper: every action
rem            just calls a python entry point. AI sessions call those python
rem            entries directly and never go through this bat.
rem
rem  Services:
rem    flash guard  scripts\flash_guard\flash_guard.py   (daemon, runs pyocd
rem                                                       outside the sandbox)
rem    serial hub   scripts\serial_hub\serial_hub.py     (TCP 5555 / 5556)
rem
rem  Adding a service later: add a label, add a menu line, add the flag in the
rem  argument dispatch at :dispatch. Keep everything ASCII, keep CRLF endings.
rem
rem  Constraints (learned the hard way):
rem    * ASCII ONLY and CRLF ONLY. A .bat is parsed byte-by-byte by cmd.exe:
rem      UTF-8 Chinese text gets mangled, and LF-only line endings break
rem      goto/label parsing (it can loop forever).
rem    * Do not pin PYTHONIOENCODING here: the python scripts set it for their
rem      own children. We only switch this console to UTF-8 so Chinese output
rem      is readable.
rem ============================================================================
setlocal EnableExtensions

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
cd /d "%REPO%"

rem ---- adjustable knobs -------------------------------------------------------
set "HUB_COM=COM46"
set "HUB_BAUD=115200"
set "HUB_UI=tui"
if not defined HUB_COM_OVERRIDE goto :keep_knobs
set "HUB_COM=%HUB_COM_OVERRIDE%"
:keep_knobs
set "VENV_PY=E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe"
set "PY313=E:\software\InstallerEdition\DevTools\Python\Python313\python.exe"

rem ---- console: UTF-8 so the python scripts' Chinese output is readable -------
chcp 65001 >nul 2>nul
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONIOENCODING=utf-8"

call :probe_py
if not defined PY goto :no_python

if "%~1"=="" goto :menu
if /i "%~1"=="guard"        goto :svc_guard
if /i "%~1"=="hub"          goto :svc_hub_arg
if /i "%~1"=="both"         goto :svc_both
if /i "%~1"=="status"       goto :svc_status
if /i "%~1"=="build"        goto :svc_build
if /i "%~1"=="flash"        goto :svc_flash
if /i "%~1"=="build-flash"  goto :svc_build_flash
if /i "%~1"=="help"         goto :usage
if /i "%~1"=="-h"           goto :usage
if /i "%~1"=="--help"       goto :usage
echo [ERROR] unknown argument: %~1
goto :usage

:menu
echo.
echo ============================================================
echo  rt-thread-ros  ai_services
echo ============================================================
echo   1  build             compile firmware           (python)
echo   2  flash             download via flash guard   (needs 4 running)
echo   3  build + flash     compile then download
echo   4  flash guard       start daemon (AI flashing)
echo   5  serial hub        start serial hub (TCP 5555)
echo   6  guard + hub       start both
echo   7  status            guard / hub / port / firmware
echo   0  exit
echo ============================================================
choice /c 1234567890 /n /m "select> "
if errorlevel 10 goto :done
if errorlevel 9 goto :menu
if errorlevel 8 goto :menu
if errorlevel 7 goto :svc_status
if errorlevel 6 goto :svc_both
if errorlevel 5 goto :svc_hub
if errorlevel 4 goto :svc_guard
if errorlevel 3 goto :svc_build_flash
if errorlevel 2 goto :svc_flash
if errorlevel 1 goto :svc_build
goto :menu

rem ---- services --------------------------------------------------------------
:svc_guard
echo.
echo [guard] starting flash guard -- keep THIS window open.
"%PY%" "%REPO%\scripts\flash_guard\flash_guard.py" %2 %3 %4 %5
echo.
echo [guard] exited (code %ERRORLEVEL%)
goto :done

:svc_hub_arg
if not "%~2"=="" set "HUB_COM=%~2"
if not "%~3"=="" set "HUB_BAUD=%~3"
:svc_hub
call :probe_serial
if not defined HUB_PY goto :no_pyserial
echo.
echo [hub] %HUB_COM% @ %HUB_BAUD%  ui=%HUB_UI%  data=127.0.0.1:5555  control=5556
"%HUB_PY%" "%REPO%\scripts\serial_hub\serial_hub.py" --com %HUB_COM% --baud %HUB_BAUD% --ui %HUB_UI%
echo.
echo [hub] exited (code %ERRORLEVEL%)
goto :done

:svc_both
call :probe_serial
if not defined HUB_PY goto :no_pyserial
start "rt-thread-ros serial hub %HUB_COM%" cmd /k call "%REPO%\ai_services.bat" hub %HUB_COM% %HUB_BAUD%
timeout /t 2 /nobreak >nul
goto :svc_guard

:svc_status
echo.
"%PY%" "%REPO%\scripts\flash_guard\flash_guard.py" --status
echo.
echo ---- ports ----
netstat -ano | findstr /R /C:":5555 .*LISTENING" >nul && echo   5555 [ok] data   || echo   5555 [--] data
netstat -ano | findstr /R /C:":5556 .*LISTENING" >nul && echo   5556 [ok] control|| echo   5556 [--] control
echo.
echo ---- serial ----
call :probe_serial
if not defined HUB_PY goto :status_no_serial
"%HUB_PY%" "%REPO%\scripts\serial_hub\serial_hub.py" --list 2>nul
goto :status_firmware
:status_no_serial
echo   (this machine has no python with pyserial -- serial hub cannot start)
:status_firmware
echo.
echo ---- firmware ----
"%PY%" "%REPO%\scripts\firmware\build.py" status
echo.
goto :done

:svc_build
echo.
"%PY%" "%REPO%\scripts\firmware\build.py" build
echo.
echo [build] exit code %ERRORLEVEL%
goto :done

:svc_flash
echo.
echo [flash] asking the flash guard to program the board ...
"%PY%" "%REPO%\scripts\flash_guard\flash_guard.py" --request flash --wait
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="3" echo [flash] the guard is NOT running -- start menu option 4 first.
echo [flash] exit code %RC%
goto :done

:svc_build_flash
echo.
"%PY%" "%REPO%\scripts\firmware\build.py" build
if errorlevel 1 goto :build_failed
echo.
echo [build] ok -- now flashing via guard ...
"%PY%" "%REPO%\scripts\flash_guard\flash_guard.py" --request flash --wait
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" echo [flash] the guard is NOT running -- start menu option 4 first.
echo [flash] exit code %RC%
goto :done

:build_failed
echo.
echo [build] FAILED -- not flashing.
goto :done

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
"%~1" -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
goto :eof

:probe_serial
set "HUB_PY="
call :try_serial "python"
if defined HUB_PY goto :eof
call :try_serial "%PY313%"
goto :eof

:try_serial
"%~1" -c "import serial" >nul 2>nul
if not errorlevel 1 set "HUB_PY=%~1"
goto :eof

:usage
echo.
echo usage: ai_services.bat [command]
echo   (no arg)            interactive menu
echo   guard               start flash guard daemon
echo   hub [COMx] [baud]   start serial hub
echo   both                start hub in a new window, then guard here
echo   status              guard / hub / port / firmware status
echo   build               compile firmware
echo   flash               download via guard
echo   build-flash         compile then download
echo.
if not defined FLASH_GUARD_NOPAUSE pause
exit /b 1

:no_python
echo [ERROR] no usable python found. tried: python, %PY313%, %VENV_PY%
if not defined FLASH_GUARD_NOPAUSE pause
exit /b 1

:no_pyserial
echo [ERROR] that python has no pyserial: %HUB_PY%
echo         install it, or set PY313 in this file to one that has it.
if not defined FLASH_GUARD_NOPAUSE pause
exit /b 1

:done
if not defined FLASH_GUARD_NOPAUSE pause
endlocal
exit /b 0
