# One-command entrypoint. Fetch only official release assets; no Python/npm/pip.
[CmdletBinding()]
param([string]$Version = 'latest', [string]$ExistingDataDir = '', [switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$previousProgress = $ProgressPreference
$temporary = $null
try {
    if ($Version -ne 'latest' -and $Version -notmatch '^v?\d+\.\d+\.\d+$') { throw '版本号格式不正确。' }
    if (-not [Environment]::Is64BitOperatingSystem) { throw '此成品包需要 64 位 Windows。' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue' # PS5's per-chunk progress can slow large downloads drastically
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('quota-download-'+[Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    Write-Host '[1/3] 获取正式版本信息…'
    $api = 'https://api.github.com/repos/IanCJ86/ai-quota-widget/releases/'
    $api += $(if ($Version -eq 'latest') { 'latest' } else { 'tags/v'+$Version.TrimStart('v') })
    $release = Invoke-RestMethod -Uri $api -Headers @{'User-Agent'='ai-quota-widget-installer'} -TimeoutSec 30
    if ($release.draft -or $release.prerelease) { throw '目标不是正式发布版。' }
    $asset = @($release.assets | Where-Object { $_.name -match '^ai-quota-widget-v\d+\.\d+\.\d+-windows-x64\.zip$' })
    $sum = @($release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' })
    if ($asset.Count -ne 1 -or $sum.Count -ne 1) { throw '该版本没有完整的 Windows 成品包，请打开正式 Release 页面。' }
    foreach ($url in @($asset[0].browser_download_url,$sum[0].browser_download_url)) {
        if (-not $url.StartsWith('https://github.com/IanCJ86/ai-quota-widget/releases/download/',[StringComparison]::Ordinal)) { throw '下载地址不是本仓库的正式资产。' }
    }
    Write-Host ('[2/3] 下载成品包 {0}（约 {1:N1} MB），无需安装开发环境…' -f $release.tag_name,($asset[0].size/1MB))
    $zip = Join-Path $temporary 'app.zip'
    Invoke-WebRequest -UseBasicParsing -Uri $asset[0].browser_download_url -OutFile $zip -TimeoutSec 180
    $sums = (Invoke-WebRequest -UseBasicParsing -Uri $sum[0].browser_download_url -TimeoutSec 30).Content
    if ($sums -is [byte[]]) { $sums = [Text.Encoding]::UTF8.GetString($sums) }
    $pattern = '(?m)^([a-fA-F0-9]{64})\s+'+[regex]::Escape($asset[0].name)+'\s*$'
    if ($sums -notmatch $pattern -or (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $Matches[1]) { throw '下载校验失败，未执行安装。' }
    Write-Host '[3/3] 校验通过，解压并安装…'
    $unpack = Join-Path $temporary 'package'
    Expand-Archive -LiteralPath $zip -DestinationPath $unpack
    $options = @{NoLaunch=$NoLaunch}
    if ($ExistingDataDir) { $options.ExistingDataDir = $ExistingDataDir }
    & (Join-Path $unpack 'setup.ps1') @options
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw '成品包安装器未完成，请看上方中文提示。' }
} finally {
    $ProgressPreference = $previousProgress
    if ($temporary -and (Test-Path -LiteralPath $temporary)) {
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
        $resolved = [IO.Path]::GetFullPath($temporary)
        if ($resolved.StartsWith($tempRoot+'quota-download-',[StringComparison]::OrdinalIgnoreCase) -and -not ((Get-Item -LiteralPath $temporary).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $temporary -Recurse -Force
        }
    }
}
