@echo off
rem Double-click: starts AgentsMind AND a free public https link (Cloudflare Quick Tunnel, no account needed).
rem The link is shown in this window and saved in data\public_url.txt. It works while this window is open.
cd /d "%~dp0"
call Start-AgentsMind.bat --public
