@echo off
chcp 65001 >nul
title Antigravity Language Server Patcher (Windows)
echo ====================================================================
echo    ANTIGRAVITY AUTO-PATCHER - CHẠY TRỰC TIẾP TRÊN WINDOWS
echo ====================================================================
echo.
python "%~dp0..\wsl\patch-antigravity-server.py" %*
echo.
echo ====================================================================
pause
