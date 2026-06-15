$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $projectDir
$Host.UI.RawUI.WindowTitle = 'Job Application Sender'

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  Job Application Sender' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

# Step 1: ensure venv exists
if (-not (Test-Path '.venv\Scripts\Activate.ps1')) {
    Write-Host '[1/3] First-time setup: creating virtual environment...' -ForegroundColor Cyan
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'ERROR: Could not create venv. Is Python 3.10+ installed and on PATH?' -ForegroundColor Red
        Read-Host 'Press Enter to close'
        exit 1
    }
    & '.venv\Scripts\Activate.ps1'
    Write-Host '[2/3] Installing dependencies (~1 minute)...' -ForegroundColor Cyan
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'ERROR: pip install failed. Scroll up for details.' -ForegroundColor Red
        Read-Host 'Press Enter to close'
        exit 1
    }
} else {
    Write-Host '[1/3] Virtual environment found.' -ForegroundColor Cyan
    & '.venv\Scripts\Activate.ps1'
    Write-Host '[2/3] Dependencies already installed.' -ForegroundColor Cyan
}

# Step 2: port-conflict check
$listening = @(Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue).Count
if ($listening -gt 0) {
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Yellow
    Write-Host '  The app is ALREADY RUNNING on http://localhost:8501' -ForegroundColor Yellow
    Write-Host '  Opening it in your browser now...' -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Yellow
    Start-Process 'http://localhost:8501'
    Write-Host ''
    Write-Host 'Close the other Job Application Sender window before relaunching.'
    Write-Host ''
    Read-Host 'Press Enter to close this window'
    exit 0
}

# Step 3: launch
Write-Host '[3/3] Starting Streamlit server...' -ForegroundColor Cyan
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  App URL:  http://localhost:8501' -ForegroundColor Green
Write-Host '  Browser will open automatically in 5 seconds.' -ForegroundColor Green
Write-Host '  KEEP THIS WINDOW OPEN while using the app.' -ForegroundColor Green
Write-Host '  Close it or press Ctrl+C to stop the app.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

Start-Job -ScriptBlock { Start-Sleep -Seconds 5; Start-Process 'http://localhost:8501' } | Out-Null

streamlit run app.py --server.headless=true

Write-Host ''
Write-Host 'Streamlit has exited.' -ForegroundColor Yellow
Read-Host 'Press Enter to close this window'
