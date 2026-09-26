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
    Write-Host '这是源码安装器，需要 Python 3.10+（含 Tk）。普通用户请下载 windows-x64 成品包，无需 Python。'
    Write-Host '源码开发环境可用：winget install --id Python.Python.3.14 --exact --scope user'
    throw '未找到 Python；未改动已有程序。'
}
$installArgs = @((Join-Path $src 'quota_monitor.py'), '--install', '--dest', $Destination, '--no-autostart')
if ($SkipDependencies) { $installArgs += '--skip-deps' }
& $py @installArgs
if ($LASTEXITCODE -ne 0) { throw '安装失败，请查看上方提示。原程序文件保留。' }
if (-not $NoAutostartPrompt) {
    $answer = Read-Host '是否开机启动？[y/N，默认不启用]'
    if ($answer -match '^[yY]') {
        $shellObject = New-Object -ComObject WScript.Shell
        $shortcut = $shellObject.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'ai-quota-widget.lnk'))
        $shortcut.TargetPath = Join-Path $Destination 'start.bat'
        $shortcut.WorkingDirectory = $Destination
        $shortcut.Save()
    }
}
