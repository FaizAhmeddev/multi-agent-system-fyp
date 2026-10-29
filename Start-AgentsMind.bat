@echo off
rem Double-click to start AgentsMind (web app at http://127.0.0.1:8000). Close this window or press Ctrl+C to stop.
title AgentsMind
cd /d "%~dp0"
set PY=
where py >nul 2>nul && (py -3.11 -c "" >nul 2>nul && set PY=py -3.11)
if not defined PY where py >nul 2>nul && (py -3.12 -c "" >nul 2>nul && set PY=py -3.12)
if not defined PY if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
if not defined PY set PY=python
%PY% main.py %*
if errorlevel 1 (
  echo.
  echo AgentsMind stopped with an error. The messages above say why; details are in the logs folder.
  pause
)
