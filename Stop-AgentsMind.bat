@echo off
rem Stops AgentsMind and the external systems if they are still running (for example after a crash).
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
%PY% main.py --stop
for /f %%p in ('type data\external.pids 2^>nul') do taskkill /T /F /PID %%p >nul 2>nul
del data\external.pids >nul 2>nul
echo Done.
timeout /t 3 >nul
