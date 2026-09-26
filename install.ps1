# install.ps1 - one-shot installer for ai-quota-widget (pure ASCII)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1
param(
    [string]$Destination = (Join-Path $env:USERPROFILE "Desktop\quota-widget"),
    [string]$PythonPath = "",
    [switch]$NoAutostartPrompt,
    [switch]$SkipDependencies
)
$ErrorActionPreference = "Stop"

Write-Host "== ai-quota-widget installer =="

# 1. check python
$py = $PythonPath
if (-not $py) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) {
    Write-Host "ERROR: Python 3 not found on PATH."
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run this script."
    exit 1
}
Write-Host "Python found: $py"
& $py -c "import sys, tkinter; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ with tkinter is required." }
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SkipDependencies) {
    & $py -m pip install --disable-pip-version-check -r (Join-Path $src "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed; no application files replaced." }
}
& $py -c "import PIL, pystray, sys; __import__('backports.zstd' if sys.version_info < (3, 14) else 'compression.zstd')"
if ($LASTEXITCODE -ne 0) { throw "Pillow/pystray/zstd missing. Run without -SkipDependencies." }
# Use the same interpreter for launch and dependency installation.
$resolvedPy = (& $py -c "import sys; print(sys.executable)").Trim()
$pyw = Join-Path (Split-Path -Parent $resolvedPy) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pyw)) { $pyw = $resolvedPy }

# 2. copy files to Desktop\quota-widget
$dest = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $dest | Out-Null
if ([IO.Path]::GetFullPath($src).TrimEnd('\') -ne $dest.TrimEnd('\')) {
    foreach ($file in @("quota_monitor.py", "monitor_runtime.py", "harness_stats.py", "requirements.txt", "README.md", "LICENSE")) {
        Copy-Item -LiteralPath (Join-Path $src $file) -Destination $dest -Force
    }
}
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
set "PY=$pyw"
start "" "%PY%" "%~dp0quota_monitor.py"
"@
# cmd.exe uses the Windows ANSI code page; preserve non-ASCII interpreter paths.
[IO.File]::WriteAllText((Join-Path $dest "start.bat"), $bat, [Text.Encoding]::Default)

# 4. optional autostart
$ans = "N"
if (-not $NoAutostartPrompt) { $ans = Read-Host "Start automatically at login? [y/N]" }
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
Write-Host "Upgrade: quit the old widget from its tray menu before starting this version."
Write-Host "Verify: debug.txt contains per-source success times and errors (no credentials)."
