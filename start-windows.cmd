@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 desktop_app.py
    exit /b
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw desktop_app.py
    exit /b
)
echo Python 3 with Tkinter was not found. Install official Python 3, then try again.
pause
