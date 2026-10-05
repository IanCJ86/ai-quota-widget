# Offline, per-user install of the prebuilt app. Never runs pip or installs Python.
[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:USERPROFILE '.ai-quota-widget-app'),
    [string]$ExistingDataDir = '',
    [switch]$NoLaunch,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -le 5) {
    # Agents/CI may pass PS7-only PSModulePath to Windows PowerShell 5.
    $env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
}
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$watch = [Diagnostics.Stopwatch]::StartNew()
$source = $PSScriptRoot
$stage = $null
$migrationStage = $null
$installLock = $null
$checkedPaths = @{}

function Assert-NoLinks([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if ($checkedPaths.ContainsKey($cursor)) { break }
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '安装文件路径不能包含重解析链接。' }
        $checkedPaths[$cursor] = $true
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}

function Invoke-DataMigration([string]$OldDirectory, [string]$DataDirectory) {
    if (-not (Test-Path -LiteralPath $OldDirectory -PathType Container)) { throw '旧数据目录不存在或不是文件夹，未迁移。' }
    $old = (Resolve-Path -LiteralPath $OldDirectory).Path
    $cursor = $old
    while ($cursor) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '旧数据路径不能包含重解析链接。' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $names = @('config.json','settings.json','glm-key.dpapi','deepseek-key.dpapi','last-good.json','deepseek-spend.json','harness-totals.json')
    $toCopy = @($names | Where-Object { Test-Path -LiteralPath (Join-Path $old $_) -PathType Leaf })
    if (-not $toCopy.Count) { throw '旧目录没有可识别的数据文件，未迁移。请核对来源。' }
    $data = [IO.Path]::GetFullPath($DataDirectory)
    $parent = [IO.Path]::GetDirectoryName($data)
    $cursor = $data
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '数据路径不能包含重解析链接。' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    foreach ($name in $toCopy) {
        if ((Get-Item -LiteralPath (Join-Path $old $name) -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '旧数据文件不能是链接。' }
    }
    if (Test-Path -LiteralPath $data) {
        if (-not (Test-Path -LiteralPath $data -PathType Container)) { throw '目标数据路径不是文件夹。' }
        $existing = @(Get-ChildItem -LiteralPath $data -Force)
        if ($existing.Count) {
            $same = $existing.Count -eq $toCopy.Count
            foreach ($name in $toCopy) {
                $dest = Join-Path $data $name
                if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) { $same = $false; break }
                if ((Get-FileHash -LiteralPath $dest).Hash -ne (Get-FileHash -LiteralPath (Join-Path $old $name)).Hash) { $same = $false; break }
            }
            if ($same) { Write-Host '相同旧数据已完整迁移，继续安装。'; return }
            throw '新数据目录已有个人数据，未覆盖。请核对迁移来源。'
        }
    }
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $script:migrationStage = Join-Path $parent ('.aiquota-migrate-'+[Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:migrationStage | Out-Null
    foreach ($name in $toCopy) {
        $from = Join-Path $old $name
        $to = Join-Path $script:migrationStage $name
        Copy-Item -LiteralPath $from -Destination $to
        if ((Get-FileHash -LiteralPath $from).Hash -ne (Get-FileHash -LiteralPath $to).Hash) { throw '迁移校验失败，原数据保留。' }
    }
    # All bytes are verified before the only commit point (same-volume rename).
    if (Test-Path -LiteralPath $data) { [IO.Directory]::Delete($data, $false) }
    Move-Item -LiteralPath $script:migrationStage -Destination $data
    $script:migrationStage = $null
    Write-Host ('旧数据迁移完成：{0} 个文件。' -f $toCopy.Count)
}
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
    if ($manifest.version -notmatch '^\d+\.\d+\.\d+(?:rc\d+)?$') { throw '安装包版本无效。' }
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
        Assert-NoLinks $file
        if (-not $file.StartsWith($source.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or $entry.Value -notmatch '^[a-fA-F0-9]{64}$') { throw '安装包路径或校验值无效。' }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value) { throw '安装包校验失败，请重新下载。' }
    }
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $target = Join-Path $root ('v'+$manifest.version)
    Assert-NoLinks $target
    Write-Host '[2/4] 安装软件（保留个人配置）'
    if (Test-Path -LiteralPath $target) {
        foreach ($entry in $entries) {
            Assert-NoLinks (Join-Path $target $entry.Name)
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
    # Machine-owned receipt allows future updates to trim only our own versions.
    Assert-NoLinks (Join-Path $target 'bundle-manifest.json')
    Assert-NoLinks (Join-Path $target '.install-receipt.json')
    Copy-Item -LiteralPath (Join-Path $source 'bundle-manifest.json') -Destination (Join-Path $target 'bundle-manifest.json') -Force
    @{product='AIQuotaWidget';version=$manifest.version;shortcuts=(-not $NoShortcut)} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target '.install-receipt.json') -Encoding UTF8
    # Migration only when explicitly given a known old install by the user/agent.
    if ($ExistingDataDir) {
        $data = Join-Path $env:USERPROFILE '.ai-quota-widget'
        Invoke-DataMigration $ExistingDataDir $data
    }
    Write-Host '[3/4] 创建快捷方式'
    $exe = Join-Path $target 'quota-widget.exe'
    if (-not $NoShortcut) {
        $shellObject = New-Object -ComObject WScript.Shell
        $links = @()
        try {
            foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
                $final = Join-Path $folder 'AI 额度监控.lnk'
                $tempLink = Join-Path $folder ('.aiquota-'+[Guid]::NewGuid().ToString('N')+'.lnk')
                $original = if (Test-Path -LiteralPath $final) { [IO.File]::ReadAllBytes($final) } else { $null }
                $links += [pscustomobject]@{ Path=$final; Temp=$tempLink; Original=$original; Changed=$false }
                $shortcut = $shellObject.CreateShortcut($tempLink)
                $shortcut.TargetPath = $exe
                $shortcut.WorkingDirectory = $target
                $shortcut.Save()
            }
            foreach ($link in $links) {
                Move-Item -LiteralPath $link.Temp -Destination $link.Path -Force
                $link.Changed = $true
            }
        } catch {
            foreach ($link in $links) {
                if ($link.Changed) {
                    if ($null -ne $link.Original) { [IO.File]::WriteAllBytes($link.Path, $link.Original) }
                    else { Remove-Item -LiteralPath $link.Path -Force }
                }
            }
            throw
        } finally {
            foreach ($link in $links) {
                if (Test-Path -LiteralPath $link.Temp) { Remove-Item -LiteralPath $link.Temp -Force }
            }
        }
    }
    Write-Host ('[4/4] 安装完成，用时 {0:N1} 秒。无需等待未配置账户的查询。' -f $watch.Elapsed.TotalSeconds)
    if (-not $NoLaunch) { Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Hidden }
} catch {
    Write-Host ('安装未完成：'+$_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($migrationStage -and (Test-Path -LiteralPath $migrationStage)) {
        $expectedParent = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')+'\'
        $resolvedMigration = [IO.Path]::GetFullPath($migrationStage)
        if ($resolvedMigration.StartsWith($expectedParent+'.aiquota-migrate-',[StringComparison]::OrdinalIgnoreCase)) {
            $entries = @((Get-Item -LiteralPath $migrationStage -Force)) + @(Get-ChildItem -LiteralPath $migrationStage -Recurse -Force)
            if (-not @($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
                Remove-Item -LiteralPath $migrationStage -Recurse -Force
            }
        }
    }
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        $resolved = [IO.Path]::GetFullPath($stage)
        if ($resolved.StartsWith($root+'\.install-',[StringComparison]::OrdinalIgnoreCase) -and -not ((Get-Item -LiteralPath $stage -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
    if ($installLock) { $installLock.Dispose() }
}
exit 0
