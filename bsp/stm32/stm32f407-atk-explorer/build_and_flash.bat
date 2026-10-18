@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  RT-Thread STM32F407 ATK Explorer - Build & Flash Script
::  Run from any terminal in: bsp\stm32\stm32f407-atk-explorer\
::
::  Usage:
::    build_and_flash.bat              Build + Flash (default)
::    build_and_flash.bat build        Build only
::    build_and_flash.bat clean        Clean build artifacts
::    build_and_flash.bat menuconfig   Run RT-Thread menuconfig
::    build_and_flash.bat verbose      Build + Flash + full cmd lines
:: ============================================================

:: ############################################################
:: #            CONFIGURATION  (modify below for porting)      #
:: #                                                          #
:: #  Each variable can be overridden via environment variable #
:: #  or by editing the default value directly below.          #
:: #  Variables with defaults derived from ENV_ROOT will only  #
:: #  use ENV_ROOT as fallback if not explicitly set.          #
:: ############################################################

:: ---- RT-Thread Env Tools root directory ----
if not defined ENV_ROOT (
    set "ENV_ROOT=E:\software\EnvEdition\rt-thread-env\env-windows"
)

:: ---- ARM GCC Toolchain ----
if not defined RTT_EXEC_PATH (
    set "RTT_EXEC_PATH=%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin"
)
if not defined RTT_CC (
    set "RTT_CC=gcc"
)

:: ---- Python (for venv activation) ----
if not defined VENV (
    set "VENV=%ENV_ROOT%\.venv"
)
if not defined PYTHON (
    set "PYTHON=%ENV_ROOT%\tools\python-3.11.9-amd64\python.exe"
)

:: ---- Python bytecode cache: keep __pycache__ out of the source tree ----
if not defined PYTHONPYCACHEPREFIX (
    for %%I in ("%~dp0..\..\..") do set "PYTHONPYCACHEPREFIX=%%~fI\out\pycache"
)

:: ---- PATH additions (Unix tools, git) ----
if not defined PATH_GIT (
    set "PATH_GIT=%ENV_ROOT%\tools\git-2.41.0-32-bit\cmd"
)
if not defined PATH_TOOLS_BIN (
    set "PATH_TOOLS_BIN=%ENV_ROOT%\tools\bin"
)
if not defined PATH_QEMU (
    set "PATH_QEMU=%ENV_ROOT%\tools\qemu\qemu64"
)

:: ---- PyOCD flash tool ----
if not defined PYOCD_DIR (
    set "PYOCD_DIR=%~dp0..\..\..\tools\pyocd\0.1.3"
)
if not defined PYOCD_TARGET (
    set "PYOCD_TARGET=STM32F407VE"
)
if not defined PYOCD_FLASH_OPTS (
    set "PYOCD_FLASH_OPTS=--erase=auto --frequency=1000000"
)

:: ---- Build settings ----
if not defined SCONS_JOBS (
    set "SCONS_JOBS=20"
)
if not defined TARGET_BIN (
    set "TARGET_BIN=rtthread.bin"
)
if not defined TARGET_ELF (
    set "TARGET_ELF=rt-thread.elf"
)
if not defined TARGET_MAP (
    set "TARGET_MAP=rt-thread.map"
)

:: ############################################################
:: #            END OF CONFIGURATION                           #
:: ############################################################

:: ---- PATH Setup ----
call :safe_add_path "%PATH_GIT%"
call :safe_add_path "%PATH_TOOLS_BIN%"
call :safe_add_path "%RTT_EXEC_PATH%"
call :safe_add_path "%PATH_QEMU%"

:: ---- Activate Python VENV ----
if not exist "%VENV%\Scripts\activate.bat" (
    echo [ERROR] Python VENV not found: %VENV%
    exit /b 1
)
call "%VENV%\Scripts\activate.bat" >nul 2>&1

:: ---- Switch to BSP directory ----
cd /d "%~dp0"

:: ---- Resolve PyOCD absolute path ----
for %%A in ("%PYOCD_DIR%") do set "PYOCD_DIR=%%~fA"
if not defined PYOCD_EXE (
    set "PYOCD_EXE=pyocd.exe"
)

:: ---- Parse mode argument ----
set "MODE=%~1"
if "%MODE%"=="" set "MODE=flash"
if /i "%MODE%"=="-h"       goto :help
if /i "%MODE%"=="--help"   goto :help
if /i "%MODE%"=="/?"       goto :help
if /i "%MODE%"=="help"     goto :help

:: ---- Verbose flag ----
set "SCONS_EXTRA="
if /i "%~2"=="verbose"     set "SCONS_EXTRA=--verbose"

:: ---- Display Banner ----
echo.
echo ================================================================
echo   RT-Thread STM32F407 ATK Explorer
echo ================================================================
echo   BSP Directory  : %CD%
echo   ENV_ROOT       : %ENV_ROOT%
echo   RTT_EXEC_PATH  : %RTT_EXEC_PATH%
echo   Toolchain      : arm-none-eabi-gcc
echo   SCons Jobs     : %SCONS_JOBS%
echo   Mode           : %MODE%
echo   PyOCD          : %PYOCD_DIR%
echo ================================================================

:: ---- Check toolchain ----
where arm-none-eabi-gcc >nul 2>&1
if errorlevel 1 (
    echo [ERROR] arm-none-eabi-gcc not found in PATH!
    pause
    exit /b 1
)
arm-none-eabi-gcc --version 2>nul | findstr /i "gcc"
echo ================================================================

:: ---- Dispatch to mode handler ----
if /i "%MODE%"=="menuconfig" goto :do_menuconfig
if /i "%MODE%"=="clean"      goto :do_clean
if /i "%MODE%"=="build"      goto :do_build
if /i "%MODE%"=="flash"      goto :do_build
echo [ERROR] Unknown mode: %MODE%
goto :help

:: ############################################################
:: #  BUILD
:: ############################################################
:do_build
echo.
echo [BUILD] Compiling with scons -j%SCONS_JOBS% %SCONS_EXTRA%...
echo.

scons -j%SCONS_JOBS% %SCONS_EXTRA%
set "BUILD_RESULT=%ERRORLEVEL%"

if %BUILD_RESULT% NEQ 0 (
    echo.
    echo ================================================================
    echo  [ERROR] Build FAILED!  error code: %BUILD_RESULT%
    echo ================================================================
    pause
    exit /b %BUILD_RESULT%
)

echo.
echo [BUILD] Compilation successful!
echo [BUILD] Output: %TARGET_BIN%

if exist "%TARGET_BIN%" (
    for %%F in ("%TARGET_BIN%") do echo [BUILD] Size: %%~zF bytes
)

:: Decide whether to flash
if /i "%MODE%"=="build" goto :done

:: ############################################################
:: #  FLASH
:: ############################################################
:do_flash
echo.
echo [FLASH] ================================================================
echo [FLASH] Downloading %TARGET_BIN% to %PYOCD_TARGET% ...
echo [FLASH] ================================================================
echo.

if not exist "%PYOCD_DIR%\%PYOCD_EXE%" (
    echo [ERROR] %PYOCD_EXE% not found: %PYOCD_DIR%\%PYOCD_EXE%
    pause
    exit /b 1
)

if not exist "%TARGET_BIN%" (
    echo [ERROR] Binary not found: %TARGET_BIN%
    pause
    exit /b 1
)

:: Use pyocd.exe directly (avoid pyocd.bat encoding issues with Chinese comments)
:: Convert rtthread.bin to absolute path for pyocd
for %%F in ("%TARGET_BIN%") do set "BIN_ABS=%%~fF"
echo [FLASH] Binary: !BIN_ABS!

pushd "%PYOCD_DIR%"
%PYOCD_EXE% flash --target=%PYOCD_TARGET% %PYOCD_FLASH_OPTS% "!BIN_ABS!"
set "FLASH_RESULT=%ERRORLEVEL%"
popd

if %FLASH_RESULT% NEQ 0 (
    echo.
    echo ================================================================
    echo  [ERROR] Flash FAILED!  error code: %FLASH_RESULT%
    echo ================================================================
    pause
    exit /b %FLASH_RESULT%
)

echo.
echo ================================================================
echo  Build ^& Flash COMPLETED SUCCESSFULLY!
echo ================================================================
goto :done

:: ############################################################
:: #  MENUCONFIG
:: ############################################################
:do_menuconfig
echo.
echo [MENUCONFIG] Launching...
menuconfig
goto :done

:: ############################################################
:: #  CLEAN
:: ############################################################
:do_clean
echo.
echo [CLEAN] Removing build artifacts...
if exist "build" (
    rmdir /s /q "build"
    echo [CLEAN] build/ removed.
)
for %%F in ("%TARGET_ELF%" "%TARGET_BIN%" "%TARGET_MAP%") do (
    if exist "%%F" (
        del /q "%%F"
        echo [CLEAN] %%F removed.
    )
)
echo [CLEAN] Done.
goto :done

:: ############################################################
:: #  HELP
:: ############################################################
:help
echo.
echo Usage: build_and_flash.bat [mode] [verbose]
echo.
echo Modes:
echo   flash       Build + Flash (default)
echo   build       Build only
echo   clean       Clean build artifacts
echo   menuconfig  Launch RT-Thread menuconfig
echo.
echo Options:
echo   verbose     Print full gcc command lines
echo.
echo Examples:
echo   build_and_flash.bat              Build and flash
echo   build_and_flash.bat build        Build only
echo   build_and_flash.bat clean        Clean
echo   build_and_flash.bat verbose      Build + flash + verbose
goto :done

:: ############################################################
:: #  DONE
:: ############################################################
:done
endlocal
exit /b 0

:: ############################################################
:: #  Helper: add path if not already present
:: ############################################################
:safe_add_path
set "new_path=%~1"
for %%A in ("%new_path%") do set "new_path=%%~fA"
echo %PATH% | findstr /i /c:"%new_path%;" >nul
if errorlevel 1 (
    set "PATH=%new_path%;%PATH%"
) else (
    set "PATH=%new_path%;!PATH:%new_path%;=!"
)
goto:eof
