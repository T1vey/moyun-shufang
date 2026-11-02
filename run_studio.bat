@echo off
chcp 65001 >nul 2>&1
title SO-101 Integrated Console
echo ========================================
echo   SO-101 Integrated Console
echo   Drawing / Hand Follow / Servo Debug
echo ========================================
echo.

set PYTHON=C:\Users\gongj\AppData\Local\Programs\Python\Python312\python.exe
set SCRIPTS=%~dp0
set PYTHONIOENCODING=utf-8

echo Launching arm_studio.py...
echo.

"%PYTHON%" "%SCRIPTS%scripts\arm_studio.py" --target-drawing

echo.
echo Exited.
pause
