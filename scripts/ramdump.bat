@echo off
REM Thin wrapper for the ramdump toolchain (all logic lives in python).
REM Usage: ramdump.bat <subcommand> [args...]
REM   build|flash|clean|menuconfig   -> tools\run.py build ...
REM   dump|recv|analyze|hub          -> tools\run.py <sub> ...
REM   list|probe|loopback            -> ramdump test scripts
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE%..") do set "REPO=%%~fI"
set "PYSRC=%REPO%\scripts\src"
if not defined PYTHONPYCACHEPREFIX set "PYTHONPYCACHEPREFIX=%REPO%\out\pycache"
set "RUNPY=%SCRIPTS%toolbelt\tools\run.py"
set "PY=python"
"%PY%" --version >nul 2>nul || (echo [ERROR] python not found in PATH & exit /b 1)
if "%~1"=="" goto :usage
set "SUB=%~1"
shift
:dispatch
if /i "%SUB%"=="build"      ( "%HERE%toolbelt\tools\run.py" build %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="flash"      ( "%HERE%toolbelt\tools\run.py" build flash %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="clean"      ( "%HERE%toolbelt\tools\run.py" build clean %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="menuconfig" ( "%HERE%toolbelt\tools\run.py" build menuconfig %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="dump"       ( "%HERE%toolbelt\tools\run.py" dump %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="recv"       ( "%HERE%toolbelt\tools\run.py" recv %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="analyze"    ( "%HERE%toolbelt\tools\run.py" analyze %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="hub"        ( "%HERE%toolbelt\tools\run.py" hub %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="list"       ( "%PY%" "%PYSRC%\toolbelt\ramdump\test\test_serial.py" --list %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="probe"      ( "%PY%" "%PYSRC%\toolbelt\ramdump\test\test_serial.py" --probe %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="loopback"   ( "%PY%" "%PYSRC%\toolbelt\ramdump\test\test_usb_loopback.py" %* & exit /b %ERRORLEVEL% )
echo [ERROR] unknown subcommand: %SUB%
:usage
echo Usage: ramdump.bat [build^|flash^|clean^|menuconfig^|dump^|recv^|list^|probe^|loopback^|analyze^|hub] [args]
echo Example:
echo   ramdump.bat build --flash
echo   ramdump.bat dump --com COM46
exit /b 2
