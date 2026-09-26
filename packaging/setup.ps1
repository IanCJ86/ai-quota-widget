# Offline, per-user install of the prebuilt app. Never runs pip or installs Python.
[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\AIQuotaWidget'),
    [string]$ExistingDataDir = '',
    [switch]$NoLaunch,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$watch = [Diagnostics.Stopwatch]::StartNew()
$source = $PSScriptRoot
$stage = $null
$installLock = $null
try {
    $created = $false
    $installLock = [Threading.Mutex]::new($false, 'Local\AIQuotaWidget-Installer', [ref]$created)
    if (-not $created) { throw '另一个安装任务正在运行，请等待完成。' }
    try {
        $running = [Threading.Mutex]::OpenExisting('Local\IanQuotaMonitor-v2')
    } catch [Threading.WaitHandleCannotBeOpenedException] { $running = $null }
    if ($running) { $running.Dispose(); throw '额度监控正在运行。请在右键菜单选择“退出”，再安装；个人配置不会丢失。' }
    Write-Host '[1/4] 校验成品包（不需要安装 Python）'
    $manifest = Get-Content -LiteralPath (Join-Path $source 'bundle-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($manifest.version -notmatch '^\d+\.\d+\.\d+$') { throw '安装包版本无效。' }
    $root = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($root -eq [IO.Path]::GetPathRoot($root).TrimEnd('\') -or $root -eq $env:USERPROFILE -or $root -eq $source) { throw '请选择独立安装目录。' }
    $cursor = $root
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '安装目录不能包含重解析链接。' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $entries = @($manifest.files.PSObject.Properties)
    if ($entries.Count -lt 3 -or -not $manifest.files.'quota-widget.exe' -or -not $manifest.files.'quota-cli.exe') { throw '安装包文件清单不完整。' }
    foreach ($entry in $entries) {
        $file = [IO.Path]::GetFullPath((Join-Path $source $entry.Name))
        if (-not $file.StartsWith($source.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or $entry.Value -notmatch '^[a-fA-F0-9]{64}$') { throw '安装包路径或校验值无效。' }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value) { throw '安装包校验失败，请重新下载。' }
    }
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $target = Join-Path $root ('v'+$manifest.version)
    Write-Host '[2/4] 安装软件（保留个人配置）'
    if (Test-Path -LiteralPath $target) {
        foreach ($entry in $entries) {
            if ((Get-FileHash -LiteralPath (Join-Path $target $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) { throw '该版本的已有文件与成品包不同，未覆盖。请使用新的独立目录。' }
        }
    } else {
        $stage = Join-Path $root ('.install-'+[Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stage | Out-Null
        foreach ($entry in $entries) {
            $to = Join-Path $stage $entry.Name
            New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($to)) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $source $entry.Name) -Destination $to
            if ((Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash -ne $entry.Value) { throw '复制校验失败，原版本未替换。' }
        }
        Move-Item -LiteralPath $stage -Destination $target
        $stage = $null
    }
    # Migration only when explicitly given a known old install by the user/agent.
    if ($ExistingDataDir) {
        $data = Join-Path $env:LOCALAPPDATA 'AIQuotaWidget'
        $names = @('config.json','settings.json','glm-key.dpapi','deepseek-key.dpapi','last-good.json','deepseek-spend.json','harness-totals.json')
        $toCopy = @($names | Where-Object { Test-Path -LiteralPath (Join-Path $ExistingDataDir $_) -PathType Leaf })
        foreach ($name in $toCopy) {
            if (Test-Path -LiteralPath (Join-Path $data $name)) { throw '新数据目录已有个人数据，未覆盖。请先核对迁移来源。' }
        }
        New-Item -ItemType Directory -Path $data -Force | Out-Null
        foreach ($name in $toCopy) { Copy-Item -LiteralPath (Join-Path $ExistingDataDir $name) -Destination (Join-Path $data $name) }
    }
    Write-Host '[3/4] 创建快捷方式'
    $exe = Join-Path $target 'quota-widget.exe'
    if (-not $NoShortcut) {
        $shellObject = New-Object -ComObject WScript.Shell
        foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
            $shortcut = $shellObject.CreateShortcut((Join-Path $folder 'AI 额度监控.lnk'))
            $shortcut.TargetPath = $exe
            $shortcut.WorkingDirectory = $target
            $shortcut.Save()
        }
    }
    Write-Host ('[4/4] 安装完成，用时 {0:N1} 秒。无需等待未配置账户的查询。' -f $watch.Elapsed.TotalSeconds)
    if (-not $NoLaunch) { Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Hidden }
} catch {
    Write-Host ('安装未完成：'+$_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        $resolved = [IO.Path]::GetFullPath($stage)
        if ($resolved.StartsWith($root+'\.install-',[StringComparison]::OrdinalIgnoreCase) -and -not ((Get-Item -LiteralPath $stage -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
    if ($installLock) { $installLock.Dispose() }
}
exit 0
