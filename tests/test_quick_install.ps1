param([Parameter(Mandatory=$true)][string]$ZipPath)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$global:QuotaFixtureZip = (Resolve-Path -LiteralPath $ZipPath).Path
if ([IO.Path]::GetFileName($global:QuotaFixtureZip) -notmatch '^ai-quota-widget-v(\d+\.\d+\.\d+(?:rc\d+)?)-windows-x64\.zip$') { throw 'Unexpected fixture filename' }
$global:QuotaFixtureVersion = $Matches[1]
$global:QuotaFixtureName = [IO.Path]::GetFileName($global:QuotaFixtureZip)
$global:QuotaFixtureHash = (Get-FileHash -LiteralPath $global:QuotaFixtureZip -Algorithm SHA256).Hash
$global:QuotaFixtureBadHash = $false
$global:QuotaFixturePrerelease = $false
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('quota-quick-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
function Invoke-RestMethod {
    param($Uri,$Headers,$TimeoutSec)
    $url = 'https://github.com/IanCJ86/ai-quota-widget/releases/download/v'+$global:QuotaFixtureVersion+'/'
    return [pscustomobject]@{tag_name=('v'+$global:QuotaFixtureVersion);draft=$false;prerelease=$global:QuotaFixturePrerelease;assets=@(
        [pscustomobject]@{name=$global:QuotaFixtureName;size=(Get-Item -LiteralPath $global:QuotaFixtureZip).Length;browser_download_url=($url+'app.zip')},
        [pscustomobject]@{name='SHA256SUMS.txt';browser_download_url=($url+'SHA256SUMS.txt')})}
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing,$Uri,$OutFile,$TimeoutSec)
    if ($OutFile) {
        if ($TimeoutSec -lt 900 -or $TimeoutSec -gt 1200) { throw 'Slow-network download needs a bounded, sufficient budget' }
        Copy-Item -LiteralPath $global:QuotaFixtureZip -Destination $OutFile; return
    }
    $hash = $(if ($global:QuotaFixtureBadHash) { '0'*64 } else { $global:QuotaFixtureHash })
    return [pscustomobject]@{Content=[Text.Encoding]::UTF8.GetBytes($hash+'  '+$global:QuotaFixtureName+"`n")}
}
try {
    & (Join-Path $repo 'quick-install.ps1') -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'good')
    if (-not (Test-Path -LiteralPath (Join-Path $testRoot ('good/v'+$global:QuotaFixtureVersion+'/quota-widget.exe')))) { throw 'Quick install did not produce the app' }
    $global:QuotaFixtureBadHash=$true
    $rejected=$false
    try { & (Join-Path $repo 'quick-install.ps1') -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'bad') }
    catch { $rejected=$true }
    if (-not $rejected -or (Test-Path -LiteralPath (Join-Path $testRoot 'bad'))) { throw 'Bad checksum was not rejected before install' }
    $global:QuotaFixtureBadHash=$false
    $global:QuotaFixturePrerelease=$true
    $rejected=$false
    try { & (Join-Path $repo 'quick-install.ps1') -Version $global:QuotaFixtureVersion -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'pre-denied') }
    catch { $rejected=$true }
    if (-not $rejected -or (Test-Path -LiteralPath (Join-Path $testRoot 'pre-denied'))) { throw 'Prerelease installed without opt-in' }
    & (Join-Path $repo 'quick-install.ps1') -Version $global:QuotaFixtureVersion -AllowPrerelease -NoLaunch -NoShortcut -Destination (Join-Path $testRoot 'pre-allowed')
    if (-not (Test-Path -LiteralPath (Join-Path $testRoot ('pre-allowed/v'+$global:QuotaFixtureVersion+'/quota-widget.exe')))) { throw 'Pinned prerelease opt-in failed' }
    'PASS: quick entry, byte-array checksum response, offline package handoff, bad hash rejected'
} finally {
    $resolved=[IO.Path]::GetFullPath($testRoot)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\quota-quick-test-'
    $entries=@(Get-Item -LiteralPath $testRoot)+@(Get-ChildItem -LiteralPath $testRoot -Recurse -Force)
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or @($entries | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'Unsafe test cleanup target' }
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
