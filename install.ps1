# Bootstrap only; quota_install.py owns all copying, verification and rollback.
param(
    [string]$Destination = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'quota-widget'),
    [string]$PythonPath = '',
    [switch]$NoAutostartPrompt,
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = ''
$candidates = if ($PythonPath) { @($PythonPath) } else {
    @((Get-Command py.exe,python.exe,python3.exe -All -ErrorAction SilentlyContinue) | ForEach-Object Source | Select-Object -Unique)
}
foreach ($candidate in $candidates) {
    # Zero-byte app-execution aliases can open the Store; do not execute them.
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf) -or (Get-Item -LiteralPath $candidate).Length -eq 0) { continue }
    $probe = [Diagnostics.Process]::new()
    try {
        $probe.StartInfo.FileName = $candidate
        $prefix = if ([IO.Path]::GetFileName($candidate) -eq 'py.exe') { '-3 ' } else { '' }
        $probe.StartInfo.Arguments = $prefix + '-c "import sys,tkinter,venv; assert sys.version_info >= (3,10); print(sys.executable)"'
        $probe.StartInfo.UseShellExecute = $false
        $probe.StartInfo.CreateNoWindow = $true
        $probe.StartInfo.RedirectStandardOutput = $true
        $probe.StartInfo.RedirectStandardError = $true
        $null = $probe.Start()
        $stdout = $probe.StandardOutput.ReadToEndAsync()
        $stderr = $probe.StandardError.ReadToEndAsync()
        if (-not $probe.WaitForExit(8000)) { $probe.Kill(); continue }
        if ($probe.ExitCode -eq 0) {
            $resolvedPython = $stdout.GetAwaiter().GetResult().Trim()
            if (Test-Path -LiteralPath $resolvedPython -PathType Leaf) { $py = $resolvedPython; break }
        }
    } catch { continue } finally { $probe.Dispose() }
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
