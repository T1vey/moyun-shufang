@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\run_tcb705.py --simulation --profile robots\tcb705\profile.demo.json --data-dir build\tcb705\demo_ui
) else (
  python scripts\run_tcb705.py --simulation --profile robots\tcb705\profile.demo.json --data-dir build\tcb705\demo_ui
)
pause
