@echo off
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >nul
echo.
echo  Starting Office Automation Agents Pro...
echo  Folder: %CD%
echo.
python main.py
if errorlevel 1 (
  echo.
  echo  Failed. Try: pip install -r requirements.txt
  echo  Then edit .env with your Gmail and OpenAI keys.
  pause
)
