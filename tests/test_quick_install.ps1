param([Parameter(Mandatory=$true)][string]$ZipPath)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$global:QuotaFixtureZip = (Resolve-Path -LiteralPath $ZipPath).Path
$global:QuotaFixtureHash = (Get-FileHash -LiteralPath $global:QuotaFixtureZip -Algorithm SHA256).Hash
$global:QuotaFixtureBadHash = $false
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('quota-quick-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
function Invoke-RestMethod {
    param($Uri,$Headers,$TimeoutSec)
    return [pscustomobject]@{tag_name='v1.4.0';draft=$false;prerelease=$false;assets=@(
        [pscustomobject]@{name='ai-quota-widget-v1.4.0-windows-x64.zip';size=(Get-Item -LiteralPath $global:QuotaFixtureZip).Length;browser_download_url='https://github.com/IanCJ86/ai-quota-widget/releases/download/v1.4.0/app.zip'},
        [pscustomobject]@{name='SHA256SUMS.txt';browser_download_url='https://github.com/IanCJ86/ai-quota-widget/releases/download/v1.4.0/SHA256SUMS.txt'})}
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing,$Uri,$OutFile,$TimeoutSec)
    if ($OutFile) { Copy-Item -LiteralPath $global:QuotaFixtureZip -Destination $OutFile; return }
    $hash = $(if ($global:QuotaFixtureBadHash) { '0'*64 } else { $global:QuotaFixtureHash })
    return [pscustomobject]@{Content=[Text.Encoding]::UTF8.GetBytes($hash+'  ai-quota-widget-v1.4.0-windows-x64.zip'+"`n")}
}
try {
    & (Join-Path $repo 'quick-install.ps1') -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'good')
    if (-not (Test-Path -LiteralPath (Join-Path $testRoot 'good/v1.4.0/quota-widget.exe'))) { throw 'Quick install did not produce the app' }
    $global:QuotaFixtureBadHash=$true
    $rejected=$false
    try { & (Join-Path $repo 'quick-install.ps1') -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'bad') }
    catch { $rejected=$true }
    if (-not $rejected -or (Test-Path -LiteralPath (Join-Path $testRoot 'bad'))) { throw 'Bad checksum was not rejected before install' }
    'PASS: quick entry, byte-array checksum response, offline package handoff, bad hash rejected'
} finally {
    $resolved=[IO.Path]::GetFullPath($testRoot)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\quota-quick-test-'
    $entries=@(Get-Item -LiteralPath $testRoot)+@(Get-ChildItem -LiteralPath $testRoot -Recurse -Force)
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or @($entries | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'Unsafe test cleanup target' }
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
