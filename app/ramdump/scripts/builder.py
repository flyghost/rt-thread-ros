"""
Build (scons) and flash (pyocd) for STM32F407 ATK Explorer.

Usage:
    from builder import build_and_flash
    build_and_flash()                  # current console
    build_and_flash(new_console=True)  # pop up a separate cmd window
"""

import shutil
import subprocess
import sys

from config import (
    BSP_DIR, PROJECT_ROOT,
    PYOCD_TARGET, TARGET_BIN, TARGET_ELF, TARGET_MAP,
    OUT_BIN_DIR,
)


def build_and_flash(new_console: bool = False) -> bool:
    """Build via build_and_flash.bat, then flash via pyocd.

    Args:
        new_console: If True, spawn a separate cmd window for build/flash
                     so you can watch the output in real time.

    Returns:
        True on success, False on failure.
    """
    bat = BSP_DIR / "build_and_flash.bat"
    if not bat.exists():
        print(f"[ERROR] Build script not found: {bat}")
        return False

    popen_kwargs = {}
    creationflags = 0
    if new_console and sys.platform == "win32":
        creationflags |= subprocess.CREATE_NEW_CONSOLE

    # ---- Build ----
    print("=" * 60)
    print(f"[BUILD] Running {bat.name} build ...")
    print("=" * 60)
    result = subprocess.run(
        [str(bat), "build"],
        cwd=str(BSP_DIR),
        shell=True,
        creationflags=creationflags,
    )
    print("=" * 60)
    if result.returncode != 0:
        print(f"[BUILD] FAILED (code {result.returncode})")
        return False
    if not TARGET_BIN.exists():
        print(f"[BUILD] ERROR: {TARGET_BIN} not produced")
        return False

    # ---- Flash ----
    pyocd_exe = PROJECT_ROOT / "bsp" / "PyOCD" / "0.1.3" / "pyocd.exe"
    if not pyocd_exe.exists():
        print(f"[FLASH] ERROR: pyocd not found at {pyocd_exe}")
        return False

    print("=" * 60)
    print(f"[FLASH] Target: {PYOCD_TARGET}")
    print(f"[FLASH] Binary: {TARGET_BIN} ({TARGET_BIN.stat().st_size:,} bytes)")
    print("=" * 60)

    result = subprocess.run(
        [str(pyocd_exe), "flash", "--target", PYOCD_TARGET,
         "--erase=auto", "--frequency=1000000", str(TARGET_BIN)],
        cwd=str(pyocd_exe.parent),
        creationflags=creationflags,
    )
    print("=" * 60)
    if result.returncode != 0:
        print(f"[FLASH] FAILED (code {result.returncode})")
        return False

    # ---- Copy artifacts to out/bin/ ----
    OUT_BIN_DIR.mkdir(parents=True, exist_ok=True)
    for src in [TARGET_BIN, TARGET_ELF, TARGET_MAP]:
        if src.exists():
            shutil.copy2(src, OUT_BIN_DIR / src.name)
            print(f"[BUILD] Copied {src.name} → {OUT_BIN_DIR / src.name}")

    print("[BUILD+FLASH] OK")
    return True

if __name__ == "__main__":
    import sys
    ok = build_and_flash(new_console=("--new-console" in sys.argv))
    sys.exit(0 if ok else 1)
