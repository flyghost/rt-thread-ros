@echo off
REM Thin wrapper for the ramdump toolchain (all logic lives in python).
REM Usage: ramdump.bat <subcommand> [args...]
REM   build|flash|clean|menuconfig   -> run_rtros.py build ...
REM   dump|recv|analyze|hub          -> run_rtros.py <sub> ...
REM   list|probe|loopback            -> ramdump test scripts
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE%..") do set "REPO=%%~fI"
set "PYSRC=%REPO%\scripts\src"
if not defined PYTHONPYCACHEPREFIX set "PYTHONPYCACHEPREFIX=%REPO%\out\pycache"
set "PYTHONPATH=%PYSRC%"
set "PY=python"
"%PY%" --version >nul 2>nul || (echo [ERROR] python not found in PATH & exit /b 1)
if "%~1"=="" goto :usage
set "SUB=%~1"
shift
:dispatch
if /i "%SUB%"=="build"      ( "%PY%" "%HERE%run_rtros.py" build %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="flash"      ( "%PY%" "%HERE%run_rtros.py" build flash %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="clean"      ( "%PY%" "%HERE%run_rtros.py" build clean %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="menuconfig" ( "%PY%" "%HERE%run_rtros.py" build menuconfig %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="dump"       ( "%PY%" "%HERE%run_rtros.py" dump %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="recv"       ( "%PY%" "%HERE%run_rtros.py" recv %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="analyze"    ( "%PY%" "%HERE%run_rtros.py" analyze %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="hub"        ( "%PY%" "%HERE%run_rtros.py" hub %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="list"       ( "%PY%" "%PYSRC%\rtros\ramdump\test\test_serial.py" --list %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="probe"      ( "%PY%" "%PYSRC%\rtros\ramdump\test\test_serial.py" --probe %* & exit /b %ERRORLEVEL% )
if /i "%SUB%"=="loopback"   ( "%PY%" "%PYSRC%\rtros\ramdump\test\test_usb_loopback.py" %* & exit /b %ERRORLEVEL% )
echo [ERROR] unknown subcommand: %SUB%
:usage
echo Usage: ramdump.bat [build^|flash^|clean^|menuconfig^|dump^|recv^|list^|probe^|loopback^|analyze^|hub] [args]
echo Example:
echo   ramdump.bat build --flash
echo   ramdump.bat dump --com COM46
exit /b 2
