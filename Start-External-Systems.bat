@echo off
rem Double-click to start the Finance Portal (8201) and the IT Helpdesk (8202). Ctrl+C or close to stop.
title AgentsMind external systems
cd /d "%~dp0"
set PY=
if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
if not defined PY where py >nul 2>nul && (py -3.11 -c "" >nul 2>nul && set PY=py -3.11)
if not defined PY set PY=python
%PY% external_systems\main.py %*
if errorlevel 1 pause
