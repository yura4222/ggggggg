@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements-dev.txt || goto :error
py -m unittest discover -s tests -v || goto :error
py -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all playwright --name "MAX Chat Link Finder" max_chat_link_finder_app.py || goto :error
set PLAYWRIGHT_BROWSERS_PATH=dist\browser
py -m playwright install chromium || goto :error
echo Application created in dist (EXE and bundled Chromium).
exit /b 0
:error
echo Build failed.
pause
exit /b 1
