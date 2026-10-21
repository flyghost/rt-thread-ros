@echo off
REM Thin wrapper for the ramdump toolchain (all logic lives in python).
REM Usage: ramdump.bat <subcommand> [args...]
REM   build|flash|build-flash|clean|menuconfig|status -> run.py build ...
REM   dump|recv|analyze|hub                           -> run.py <sub> ...
REM   list|probe|loopback                             -> ramdump test scripts
setlocal EnableDelayedExpansion
set "HERE=%~dp0"
set "RUNPY=%HERE%toolbelt\tools\run.py"
set "SRC=%HERE%toolbelt\src"
REM The standalone test scripts import toolbelt.*, so the package root must be importable.
set "PYTHONPATH=%SRC%"
if not defined PYTHONPYCACHEPREFIX set "PYTHONPYCACHEPREFIX=%HERE%..\out\pycache"
set "PY=python"
"%PY%" --version >nul 2>nul || (echo [ERROR] python not found in PATH & exit /b 1)
if "%~1"=="" goto :usage
set "SUB=%~1"
shift
set "ARGS="
:collect
if "%~1"=="" goto :dispatch
set "ARGS=!ARGS! %1"
shift
goto :collect

:dispatch
if /i "%SUB%"=="build"       ( call :via_build build       & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="flash"       ( call :via_build flash       & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="build-flash" ( call :via_build build-flash & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="clean"       ( call :via_build clean       & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="menuconfig"  ( call :via_build menuconfig  & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="status"      ( call :via_build status      & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="dump"        ( "%PY%" -X utf8 "%RUNPY%" dump !ARGS!    & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="recv"        ( "%PY%" -X utf8 "%RUNPY%" recv !ARGS!    & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="analyze"     ( "%PY%" -X utf8 "%RUNPY%" analyze !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="hub"         ( "%PY%" -X utf8 "%RUNPY%" hub !ARGS!     & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="list"        ( "%PY%" -X utf8 "%SRC%\toolbelt\ramdump\test\test_serial.py" --list !ARGS!    & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="probe"       ( "%PY%" -X utf8 "%SRC%\toolbelt\ramdump\test\test_serial.py" --probe !ARGS!   & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="loopback"    ( "%PY%" -X utf8 "%SRC%\toolbelt\ramdump\test\test_usb_loopback.py" !ARGS!      & exit /b !ERRORLEVEL! )
goto :unknown

REM Build family: inject the manifest projection (paths/toolchain/chip) as real
REM command line arguments, then append the user args so they win on conflicts.
:via_build
set "TB_ARGS="
REM NOTE: the command inside the backticks must NOT start with a quote, or cmd
REM treats the whole string as a file name ("The filename, directory name, or
REM volume label syntax is incorrect.") and the capture silently stays empty.
for /f "usebackq delims=" %%A in (`%PY% -X utf8 "%RUNPY%" paths --format argv`) do set "TB_ARGS=%%A"
"%PY%" -X utf8 "%RUNPY%" build !TB_ARGS! %1 !ARGS!
exit /b %ERRORLEVEL%

:unknown
echo [ERROR] unknown subcommand: %SUB%
:usage
echo Usage: ramdump.bat [build^|flash^|build-flash^|clean^|menuconfig^|status^|dump^|recv^|analyze^|hub^|list^|probe^|loopback] [args]
echo Examples:
echo   ramdump.bat status
echo   ramdump.bat build-flash
echo   ramdump.bat dump --com COM3
echo   ramdump.bat list
exit /b 2
