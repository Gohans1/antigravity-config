@echo off
chcp 65001 >nul
title Cai dat Antigravity Auto-Patcher vao Windows Startup
echo ====================================================================
echo    CAI DAT TU DONG PATCH KHI KHOI DONG / UPDATE APP
echo ====================================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell; " ^
  "$Shortcut = $WshShell.CreateShortcut(\"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\antigravity-patcher.lnk\"); " ^
  "$Shortcut.TargetPath = 'C:\Users\ADMIN\scoop\apps\python\current\pythonw.exe'; " ^
  "$Shortcut.Arguments = 'C:\Users\ADMIN\antigravity-config\wsl\patch-antigravity-server.py --watch'; " ^
  "$Shortcut.WorkingDirectory = 'C:\Users\ADMIN\antigravity-config'; " ^
  "$Shortcut.WindowStyle = 7; " ^
  "$Shortcut.Save();"
if errorlevel 1 (
    echo [ERROR] Khong the tao shortcut trong Startup folder.
    pause
    exit /b 1
)

echo [OK] Da tao shortcut antigravity-patcher.lnk trong Windows Startup.
echo [OK] Khoi chay ngay lap tuc o che do ngam qua pythonw...
start "" "C:\Users\ADMIN\scoop\apps\python\current\pythonw.exe" "C:\Users\ADMIN\antigravity-config\wsl\patch-antigravity-server.py" --watch
echo.
echo ====================================================================
echo Hoan tat! Antigravity gio se tu dong patch moi khi:
echo 1. Windows khoi dong / user dang nhap
echo 2. Antigravity cap nhat phien ban moi (tu dong nhan dien va patch lai)
echo ====================================================================
pause
