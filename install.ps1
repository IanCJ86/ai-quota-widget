# install.ps1 - one-shot installer for ai-quota-widget (pure ASCII)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

Write-Host "== ai-quota-widget installer =="

# 1. check python
$py = $null
foreach ($name in @("pythonw.exe", "python.exe")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Host "ERROR: Python 3 not found on PATH."
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run this script."
    exit 1
}
Write-Host "Python found: $py"

# 2. copy files to Desktop\quota-widget
$dest = Join-Path $env:USERPROFILE "Desktop\quota-widget"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item (Join-Path $src "quota_monitor.py") $dest -Force
if (-not (Test-Path (Join-Path $dest "config.json"))) {
    Copy-Item (Join-Path $src "config.json") $dest -Force
    Write-Host "Created default config.json (edit it to set renewal dates / plan names)."
} else {
    Write-Host "Kept existing config.json"
}

# 3. generate start.bat
$bat = @"
@echo off
rem Launch the quota monitor widget without a console window.
set "PY=pythonw.exe"
where pythonw.exe >nul 2>nul || set "PY=python.exe"
start "" "%PY%" "%~dp0quota_monitor.py"
"@
Set-Content -Path (Join-Path $dest "start.bat") -Value $bat -Encoding ASCII

# 4. optional autostart
$ans = Read-Host "Start automatically at login? [y/N]"
if ($ans -match "^[yY]") {
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk = Join-Path $startup "ai-quota-widget.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = Join-Path $dest "start.bat"
    $sc.WorkingDirectory = $dest
    $sc.Save()
    Write-Host "Autostart shortcut created: $lnk"
}

Write-Host ""
Write-Host "Done. Installed to: $dest"
Write-Host "Next: edit config.json there (renewal dates / plan name), then double-click start.bat"
Write-Host "Verify: after ~20s, debug.txt in that folder should have no 'errors'."
