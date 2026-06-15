@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Job Application Sender

echo ============================================================
echo   Job Application Sender
echo ============================================================
echo.

REM ---- Step 1: ensure virtual environment ----
if not exist ".venv\Scripts\activate.bat" (
    echo [1/3] First-time setup: creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Could not create virtual environment.
        echo Make sure Python 3.10+ is installed and on PATH.
        echo Test by running:  python --version
        echo.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    echo [2/3] Installing dependencies (~1 minute)...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: pip install failed. Scroll up for details.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment found.
    call ".venv\Scripts\activate.bat"
    echo [2/3] Dependencies already installed.
)

REM ---- Step 2: check if port 8501 is already in use ----
netstat -ano | findstr "LISTENING" | findstr ":8501" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo ============================================================
    echo   The app is ALREADY RUNNING on http://localhost:8501
    echo   Opening it in your browser now...
    echo ============================================================
    echo.
    start "" http://localhost:8501
    echo Close any existing "Job Application Sender" console window
    echo before you double-click this file again.
    echo.
    pause
    exit /b 0
)

REM ---- Step 3: launch streamlit ----
echo [3/3] Starting Streamlit server...
echo.
echo ============================================================
echo   App URL:  http://localhost:8501
echo   Your browser will open in 5 seconds.
echo   KEEP THIS WINDOW OPEN while using the app.
echo   Close it (or press Ctrl+C) to stop the app.
echo ============================================================
echo.

REM Schedule the browser to open in 5 seconds, in a hidden background process.
REM Using PowerShell avoids cmd nested-quote issues entirely.
start "" /B powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:8501'"

streamlit run app.py --server.headless=true

echo.
echo ============================================================
echo   Streamlit has exited (code %errorlevel%).
echo ============================================================
pause
