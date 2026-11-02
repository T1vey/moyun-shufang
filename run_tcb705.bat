@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\run_tcb705.py --simulation
) else (
  python scripts\run_tcb705.py --simulation
)
pause
