@echo off
chcp 65001 >nul 2>&1
title SO-101 板端屏幕孪生
cd /d "%~dp0"
where py >nul 2>&1 && (py -3 display_server.py %*) || (python display_server.py %*)
pause
