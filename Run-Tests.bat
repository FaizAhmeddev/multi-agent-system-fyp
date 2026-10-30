@echo off
rem Double-click: runs every test and writes logs\test-report.txt
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (".venv\Scripts\python.exe" scripts\run_tests.py) else (python scripts\run_tests.py)
