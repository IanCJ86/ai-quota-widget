# Bootstrap only; quota_install.py owns all copying, verification and rollback.
param(
    [string]$Destination = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'quota-widget'),
    [string]$PythonPath = '',
    [switch]$NoAutostartPrompt,
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = $PythonPath
if (-not $py) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $py = (& $launcher.Source -3 -c 'import sys; print(sys.executable)').Trim() }
}
if (-not $py) {
    Write-Host 'Python 3.10+ with Tk is required. Install Python, then run this installer again.'
    Write-Host 'Suggested command: winget install --id Python.Python.3.14 --exact --scope user'
    Write-Host 'Official alternative: https://www.python.org/downloads/windows/'
    throw 'Python is not available; no widget files changed.'
}
$installArgs = @((Join-Path $src 'quota_monitor.py'), '--install', '--dest', $Destination, '--no-autostart')
if ($SkipDependencies) { $installArgs += '--skip-deps' }
& $py @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Installation failed; read the message above. Existing app files are preserved.' }
if (-not $NoAutostartPrompt) {
    $answer = Read-Host 'Start automatically at login? [y/N]'
    if ($answer -match '^[yY]') {
        $shellObject = New-Object -ComObject WScript.Shell
        $shortcut = $shellObject.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'ai-quota-widget.lnk'))
        $shortcut.TargetPath = Join-Path $Destination 'start.bat'
        $shortcut.WorkingDirectory = $Destination
        $shortcut.Save()
    }
}
