@echo off
cd /d "%~dp0"
py -m max_chat_link_finder
if errorlevel 1 pause
