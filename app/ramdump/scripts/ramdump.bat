@echo off
setlocal enabledelayedexpansion
:: ramdump.bat — Ramdump Automation
::
:: Usage:
::   ramdump           build + flash + dump
::   ramdump build     build + flash only
::   ramdump dump      dump only (skip build)
::   ramdump flash     FLASH region only
::   ramdump sram      SRAM region only
::   ramdump ccm       CCM region only
::   ramdump clean     clean build artifacts

set "SCRIPTS=%~dp0"
set "BUILDER=%SCRIPTS%builder.py"
set "PYTHON=python"

:: Auto-detect COM port
for /f "tokens=*" %%i in ('%PYTHON% -c "import sys; sys.path.insert(0,r'%SCRIPTS%'); from serial_utils import find_ch340_port; print(find_ch340_port() or 'COM3')"') do set "COM=%%i"
if "%COM%"=="" set "COM=COM3"

:: Dispatch
if /i "%~1"==""          goto :full
if /i "%~1"=="full"      goto :full
if /i "%~1"=="build"     goto :build
if /i "%~1"=="dump"      goto :dump_all
if /i "%~1"=="flash"     goto :dump_flash
if /i "%~1"=="sram"      goto :dump_sram
if /i "%~1"=="ccm"       goto :dump_ccm
if /i "%~1"=="clean"     goto :clean
if /i "%~1"=="help"      goto :help
if /i "%~1"=="-h"        goto :help
echo [ERROR] Unknown: %~1
goto :help

:full
echo ================================================================
echo   RAMDUMP - Full Automation  (COM: %COM%)
echo ================================================================
call :do_build
if errorlevel 1 goto :end
echo Waiting 3s for board reboot...
timeout /t 3 /nobreak >nul
call :do_dump all
goto :end

:build
call :do_build
goto :end

:dump_all
call :do_dump all
goto :end

:dump_flash
call :do_dump flash
goto :end

:dump_sram
call :do_dump sram
goto :end

:dump_ccm
call :do_dump ccm
goto :end

:clean
echo [CLEAN] Removing build artifacts...
cd /d "%SCRIPTS%..\..\..\bsp\stm32\stm32f407-atk-explorer"
if exist build rmdir /s /q build
del /q rt-thread.elf rtthread.bin rt-thread.map 2>nul
echo [CLEAN] Done.
goto :end

:help
echo.
echo   ramdump.bat - Ramdump Automation
echo.
echo   Commands:
echo     full      build + flash + dump (default)
echo     build     build + flash only
echo     dump      dump only (skip build)
echo     flash     FLASH region only
echo     sram      SRAM region only
echo     ccm       CCM region only
echo     clean     clean build artifacts
echo.
goto :end

:: ============================================================
:: Internal functions
:: ============================================================

:do_build
echo [BUILD] Compiling + Flashing...
%PYTHON% "%BUILDER%"
exit /b %ERRORLEVEL%

:do_dump
set "REGION=%~1"
%PYTHON% -c "import sys,time; sys.path.insert(0,r'%SCRIPTS%');\
from serial_utils import open_serial, serial_send;\
from console import check_console, enter_ramdump_usb;\
from ymodem_receiver import ymodem_receive;\
from config import OUT_DUMP_DIR;\
from pathlib import Path;\
uart=open_serial(r'%COM%');\
if not check_console(uart): sys.exit(1);\
usb,port=enter_ramdump_usb(uart);\
if not usb: sys.exit(1);\
time.sleep(8);\
usb.write(b'\r\n'); time.sleep(0.5);\
r=usb.read(usb.in_waiting or 4096);\
if r: print(f'[USB] ready: {r[:100]!r}');\
cmd_map={'flash':'ramdump_flash','sram':'ramdump sram','ccm':'ramdump ccm','all':'ramdump'};\
cmd=cmd_map.get(r'%REGION%','ramdump');\
print(f'[USB] Sending {cmd}');\
usb.write((cmd+'\r\n').encode()); usb.flush();\
time.sleep(0.3);\
out=str(OUT_DUMP_DIR/time.strftime('%%Y%%m%%d_%%H%%M%%S'));\
print(f'[YMODEM] Receiving to {out}');\
saved=ymodem_receive(usb,out);\
usb.close();\
if saved:\
    print(f'[DONE] {len(saved)} file(s) saved to {out}');\
    [print(f'  {Path(f).name}  ({Path(f).stat().st_size:,} bytes)') for f in saved];\
else:\
    print('[DONE] No files received'); sys.exit(1);\
"
exit /b %ERRORLEVEL%

:end
endlocal
