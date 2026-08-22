@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
py -m playwright install chromium
py -m max_chat_link_finder
if errorlevel 1 pause
