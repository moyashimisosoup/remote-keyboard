@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Remote Keyboard v0.1
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 remote_keys.py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python remote_keys.py
    ) else (
        echo Python 3 not found. Install Python 3, then try again.
    )
)
echo.
echo Receiver stopped. Press any key to close.
pause >nul
