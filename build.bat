@echo off
cd /d "%~dp0"
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "MAX Chat Link Finder" max_chat_link_finder_app.py
if errorlevel 1 pause
