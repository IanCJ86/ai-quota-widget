param([Parameter(Mandatory=$true)][string]$Bundle, [Parameter(Mandatory=$true)][string]$Output,
      [string]$Compiler = $env:AI_QUOTA_ISCC)
$ErrorActionPreference = 'Stop'
$outputRoot = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
if (-not $Compiler) {
    $tools = Join-Path $outputRoot 'installer-tools'
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $download = Join-Path $tools 'compiler-setup.exe'
    Invoke-WebRequest -UseBasicParsing 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe' -OutFile $download
    if ((Get-FileHash -LiteralPath $download).Hash -ne '0362A383ED217D4C4239B5933866DD96D3EB2102737DA92F80F6057A4B40DF2F' -or (Get-AuthenticodeSignature -LiteralPath $download).Status -ne 'Valid') { throw 'Compiler checksum/signature failed' }
    $compilerDir = Join-Path $tools 'inno'
    $process = Start-Process -FilePath $download -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/NOICONS',('/DIR="'+$compilerDir+'"')) -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw 'Compiler installation failed' }
    $Compiler = Join-Path $compilerDir 'ISCC.exe'
}
$bundleRoot = (Resolve-Path -LiteralPath $Bundle).Path
$version = (Get-Content -LiteralPath (Join-Path $bundleRoot 'bundle-manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json).version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Only stable installer builds allowed' }
& $Compiler ('/DAppVersion='+$version) ('/DBundleDir='+$bundleRoot) ('/DOutputDir='+$outputRoot) (Join-Path $PSScriptRoot '..\packaging\installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Setup compiler failed' }
