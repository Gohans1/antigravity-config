@echo off
chcp 65001 >nul
title Hoan tac che do hoi duyet lenh
echo ====================================================================
echo    HOAN TAC VE CHE DO AN TOAN (HOI DUYET LENH)
echo ====================================================================
echo.
cd /d "%~dp0"
bun scripts\disable_auto_exec.mjs
echo.
echo ====================================================================
echo Hoan tat! Hay khoi dong lai Antigravity.
echo.
pause