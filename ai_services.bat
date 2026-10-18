@echo off
rem ===========================================================================
rem  rt-thread-ros AI services  --  started BY A HUMAN, outside the DSH sandbox
rem
rem  Purpose:
rem    Some jobs the AI cannot do from inside its sandbox -- pyocd needs to
rem    unpack a DLL into a temp dir, and a COM port can only be owned by one
rem    process. So a human opens this window and it owns those things for the
rem    AI. This is also where FUTURE services go; it is a launcher, not a tool.
rem
rem  Services it starts today:
rem    guard   flash guard -- the AI drops request files into the repo, this
rem            window runs pyocd / scons for it and writes the result back
rem    hub     serial hub -- one process owns the COM port; the AI (TCP 5555)
rem            and you (--ui tui) share it at the same time
rem
rem  Adding a service later (keep the shape identical):
rem    1) the new tool lives under scripts\<name>\, driven by files or a fixed CLI
rem    2) add a :<name> label here, same structure as :guard and :hub
rem    3) add one line to the :menu block and one to the usage block above
rem    4) still no Chinese in this file (codepage) and still CRLF endings
rem
rem  Why the guard must live outside the sandbox:
rem    scripts\pyocd\0.1.3\pyocd.exe is a PyInstaller onefile bundle, so it must
rem    unpack VCRUNTIME140.dll into a temp dir. The confined file sandbox
rem    (workspace-write) cannot write outside the workspace, so it always dies
rem    with "VCRUNTIME140.dll could not be extracted! / fopen: Permission denied".
rem    Escalating to danger-full-access does not help either (it took the job
rem    runner down with 0xC0000142). So: AI stays inside the wall, this window
rem    performs the hardware actions. It is NOT a remote shell -- the guard only
rem    rebuilds argv for a fixed whitelist and rejects shell metacharacters.
rem
rem  NOTE: this file is deliberately ASCII-only, with CRLF line endings.
rem    Chinese text in a .bat must match the console codepage (GBK here), and
rem    LF-only endings make cmd mis-parse goto/labels into an infinite loop.
rem    Both failure modes were hit while building this.
rem
rem  Usage:
rem    ai_services.bat                     menu
rem    ai_services.bat guard               start the guard in this window
rem    ai_services.bat hub [COMx] [baud]   start the serial hub in this window
rem    ai_services.bat both [COMx] [baud]  guard here + hub in a new window
rem    ai_services.bat status              guard alive? hub listening? ports?
rem ===========================================================================
setlocal EnableExtensions

rem ---- pin the temp dir INSIDE the repo -------------------------------------
rem  Both this window and every child (pyocd.exe is a PyInstaller onefile bundle
rem  that must unpack VCRUNTIME140.dll before it can run) need a writable temp.
rem  Never trust the inherited TEMP: a stale per-session path makes pyocd die with
rem  "[nnnn] INTERNAL ERROR: cannot create temporary directory!" and exit -1.
rem  The repo root is the one place we know is writable, so put it there.
set "REPO=%~dp0"
set "TEMP=%REPO%out\tmp"
set "TMP=%REPO%out\tmp"
set "TMPDIR=%REPO%out\tmp"
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>nul
cd /d "%~dp0"


set "GUARD=%REPO%scripts\flash_guard\flash_guard.py"
set "HUB=%REPO%scripts\serial_hub\serial_hub.py"
set "VENV_PY=E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe"
set "PY313=E:\software\InstallerEdition\DevTools\Python\Python313\python.exe"

rem ---- board defaults: CH340 -> USART1. Change these two lines for a new board
set "HUB_COM=COM46"
set "HUB_BAUD=115200"

rem ---- hub UI mode: tui (interactive on the console) | stream | none
rem      headless / scripted run:  set HUB_UI=none  then launch this script
if not defined HUB_UI set "HUB_UI=tui"

rem ---- do NOT set PYTHONIOENCODING: guard/hub console output would go mojibake.
rem      The guard pins UTF-8 for its own children instead.
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"

rem ---- pick an interpreter: guard needs stdlib only, hub also needs pyserial
set "PY="
call :probe_py "python"
if not defined PY call :probe_py "%PY313%"
if not defined PY call :probe_py "%VENV_PY%"
if not defined PY (
  echo [x] no usable Python found. Install one or fix PY313 in this script.
  goto :die
)

if "%~1"=="" goto :menu
if /i "%~1"=="guard"  goto :guard
if /i "%~1"=="hub"    goto :hub
if /i "%~1"=="both"   goto :both
if /i "%~1"=="status" goto :status
echo [x] unknown argument: %~1
echo     usage: ai_services.bat [guard ^| hub [COMx] [baud] ^| both [COMx] [baud] ^| status]
goto :die

rem ===========================================================================
:menu
cls
echo ==================================================================
echo   rt-thread-ros AI services  (outside-the-sandbox window)
echo ==================================================================
echo.
echo   1   flash guard       pyocd / scons proxy for the AI
echo   2   serial hub        %HUB_COM% @ %HUB_BAUD%  -^>  TCP 127.0.0.1:5555
echo   3   both              guard here + hub in a new window
echo   4   status            guard alive? hub listening? ports?
echo   0   exit
echo.
echo   not %HUB_COM%?  ai_services.bat hub COM7
echo.
choice /c 12340 /n /m "select [1-4,0]: "
if errorlevel 5 goto :done
if errorlevel 4 goto :status
if errorlevel 3 goto :both
if errorlevel 2 goto :hub
goto :guard

rem ===========================================================================
:guard
if not exist "%GUARD%" (
  echo [x] missing %GUARD%
  goto :die
)
title rt-thread-ros flash guard
echo [*] guard starting -- keep this window open (Ctrl+C to stop)
echo     mailbox: %REPO%out\guard   (the AI writes req_NNNN.json here)
echo.
"%PY%" "%GUARD%"
set "RC=%ERRORLEVEL%"
echo.
echo [*] guard exited (code=%RC%)
goto :pause_die

rem ===========================================================================
:hub
if not "%~2"=="" set "HUB_COM=%~2"
if not "%~3"=="" set "HUB_BAUD=%~3"
call :resolve_hub
if not exist "%HUB%" (
  echo [x] missing %HUB%
  goto :die
)
title rt-thread-ros serial hub  %HUB_COM% @ %HUB_BAUD%
echo [*] serial hub starting -- keep this window open (Ctrl+C to stop)
echo     data 127.0.0.1:5555   control 5556   telnet 5557
echo     logs %REPO%out\log
echo.
if /i "%HUB_COM%"=="auto" (
  "%HUB_PY%" "%HUB%" --baud %HUB_BAUD% --ui %HUB_UI%
) else (
  "%HUB_PY%" "%HUB%" --com %HUB_COM% --baud %HUB_BAUD% --ui %HUB_UI%
)
set "RC=%ERRORLEVEL%"
echo.
echo [*] serial hub exited (code=%RC%)
goto :pause_die

rem ===========================================================================
:both
if not "%~2"=="" set "HUB_COM=%~2"
if not "%~3"=="" set "HUB_BAUD=%~3"
echo [*] starting serial hub in a new window (%HUB_COM% @ %HUB_BAUD%)
start "rt-thread-ros serial hub %HUB_COM%" cmd /k call "%~f0" hub %HUB_COM% %HUB_BAUD%
timeout /t 2 >nul
goto :guard

rem ===========================================================================
:status
cls
echo === flash guard ==================================================
"%PY%" "%GUARD%" --status
echo.
echo === serial hub =================================================
netstat -ano | findstr /R /C:":5555 .*LISTENING" >nul 2>nul && echo [ok] 5555 listening (hub is up) || echo [--] 5555 not listening
netstat -ano | findstr /R /C:":5556 .*LISTENING" >nul 2>nul && echo [ok] 5556 listening || echo [--] 5556 not listening
echo.
echo === serial ports ===============================================
call :resolve_hub
if defined HUB_PY (
  "%HUB_PY%" "%HUB%" --list
) else (
  echo [x] no Python with pyserial, cannot list ports
  echo     fix: %PY313% -m pip install pyserial
)
echo.
echo === firmware ===================================================
if exist "%REPO%bsp\stm32\stm32f407-atk-explorer\rtthread.bin" (
  for %%F in ("%REPO%bsp\stm32\stm32f407-atk-explorer\rtthread.bin") do echo [ok] %%~F   %%~zF bytes   %%~tF
) else (
  echo [--] no rtthread.bin yet -- run scons first
)
goto :pause_die

rem ===========================================================================
:resolve_hub
if defined HUB_PY exit /b 0
call :probe_serial "python"
if not defined HUB_PY call :probe_serial "%PY313%"
if not defined HUB_PY call :probe_serial "%VENV_PY%"
if defined HUB_PY exit /b 0
echo [x] no Python can import serial (serial_hub needs pyserial)
exit /b 1

:probe_py
if defined PY exit /b 0
%~1 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0

:probe_serial
if defined HUB_PY exit /b 0
%~1 -c "import serial" >nul 2>nul
if not errorlevel 1 set "HUB_PY=%~1"
exit /b 0

rem ===========================================================================
:pause_die
echo.
if defined FLASH_GUARD_NOPAUSE goto :done
pause
goto :done

:die
echo.
if defined FLASH_GUARD_NOPAUSE goto :die_done
pause
:die_done
endlocal
exit /b 1

:done
endlocal
exit /b 0
