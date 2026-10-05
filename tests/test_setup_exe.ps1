param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference='Stop'
$installerPath=(Resolve-Path -LiteralPath $Installer).Path
$root=Join-Path ([IO.Path]::GetTempPath()) ('quota-setup-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $destination=Join-Path $root '安装目录 中文'
    $watch=[Diagnostics.Stopwatch]::StartNew()
    $process=Start-Process -FilePath $installerPath -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/INSTALLROOT="'+$destination+'"'),'/NOLAUNCH=1','/NOSHORTCUT=1') -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw ('Setup.exe failed: '+$process.ExitCode) }
    $installed=@(Get-ChildItem -LiteralPath $destination -Directory)
    if ($installed.Count -ne 1) { throw 'No unique installed version' }
    $cli=Join-Path $installed[0].FullName 'quota-cli.exe'
    $version=(& $cli --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $installed[0].Name -ne ('v'+$version)) { throw 'Installed version mismatch' }
    & $cli --launch-check
    if ($LASTEXITCODE -ne 0) { throw 'Frozen runtime damaged' }
    Write-Output ('PASS: Chinese Setup.exe; Unicode path; no launch/shortcut; version '+$version+'; '+[math]::Round($watch.Elapsed.TotalSeconds,2)+' seconds')
} finally {
    $resolved=[IO.Path]::GetFullPath($root)
    $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\quota-setup-test-'
    if (-not $resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test cleanup' }
    $entries=@((Get-Item -LiteralPath $root -Force))+@(Get-ChildItem -LiteralPath $root -Recurse -Force)
    if (@($entries|Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Refuse cleanup through links' }
    Remove-Item -LiteralPath $root -Recurse -Force
}
