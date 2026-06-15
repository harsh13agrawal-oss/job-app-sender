@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Save Changes - Job Application Sender

echo ============================================================
echo   Save Changes
echo   Pushes your local code edits to GitHub.
echo   Streamlit Cloud auto-rebuilds in 1-2 minutes after this.
echo ============================================================
echo.

REM ---- Show what changed ----
echo Files you've changed since the last save:
echo ---
git status --short
echo ---
echo.

REM ---- Bail if there's nothing to save ----
for /f %%i in ('git status --porcelain ^| find /c /v ""') do set CHANGES=%%i
if "%CHANGES%"=="0" (
    echo No changes to save. Nothing to push.
    echo.
    pause
    exit /b 0
)

REM ---- Get a commit message ----
echo Describe your change in a few words (press Enter for default).
echo Example:  fix typo in finance template
set "MSG="
set /p MSG="Message: "
if "%MSG%"=="" set "MSG=Update"

echo.
echo [1/3] Staging changes...
git add .
if errorlevel 1 (
    echo ERROR: git add failed.
    pause
    exit /b 1
)

echo [2/3] Committing with message: "%MSG%"
git commit -m "%MSG%"
if errorlevel 1 (
    echo ERROR: git commit failed.
    pause
    exit /b 1
)

echo [3/3] Pushing to GitHub...
git push
if errorlevel 1 (
    echo.
    echo ERROR: git push failed. You may need to sign in to GitHub.
    echo If a popup appeared, complete it. Otherwise try running this again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Saved. Streamlit Cloud will rebuild in 1-2 minutes.
echo   Check progress at https://share.streamlit.io
echo ============================================================
echo.
pause
