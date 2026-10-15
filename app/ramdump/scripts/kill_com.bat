@echo off
:: Kill all Python processes holding COM ports
echo Killing Python processes...
taskkill /F /IM python.exe >nul 2>&1
echo Done. COM ports should be free now.
