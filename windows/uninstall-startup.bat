@echo off
chcp 65001 >nul
title Go bo Antigravity Auto-Patcher khoi Windows Startup
echo ====================================================================
echo    GO BO ANTIGRAVITY AUTO-PATCHER KHOI STARTUP
echo ====================================================================
echo.
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DEST_LNK=%STARTUP_DIR%\antigravity-patcher.lnk"

if exist "%DEST_LNK%" (
    del /f /q "%DEST_LNK%" >nul
    echo [OK] Da xoa: %DEST_LNK%
) else (
    echo [INFO] Shortcut khong ton tai trong Startup.
)
echo.
echo Dang dong cac tien trinh patcher dang chay ngam...
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe' AND CommandLine LIKE '%patch-antigravity-server.py%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Hoan tat!
pause
