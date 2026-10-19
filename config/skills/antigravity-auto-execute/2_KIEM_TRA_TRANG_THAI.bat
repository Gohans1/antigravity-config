@echo off
chcp 65001 >nul
title Kiem tra trang thai Antigravity Auto-Execution
echo ====================================================================
echo    KIEM TRA TRANG THAI ANTIGRAVITY AUTO-EXECUTION
echo ====================================================================
echo.
cd /d "%~dp0"
bun scripts\status.mjs
echo.
echo ====================================================================
pause