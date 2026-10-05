# Synthetic install/uninstall targets only; never uninstall the user's real app.
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$root=Join-Path ([IO.Path]::GetTempPath()) ('quota-uninstall-test-'+[Guid]::NewGuid().ToString('N'))
$savedProfile=$env:USERPROFILE
$reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIQuotaWidget'
$ownRegistry=-not(Test-Path -LiteralPath $reg)
$mutex=$null
$junction=$null
New-Item -ItemType Directory -Path $root | Out-Null
function Check([bool]$Condition,[string]$Message){if(-not $Condition){throw $Message}}
try {
    $env:USERPROFILE=Join-Path $root 'profile'
    $source=Join-Path $root 'bundle'
    $dest=Join-Path $root '应用 中文'
    $data=Join-Path $env:USERPROFILE '.ai-quota-widget'
    $harness=Join-Path $env:USERPROFILE '.dsh'
    foreach($dir in @($source,$data,$harness)){New-Item -ItemType Directory -Path $dir -Force|Out-Null}
    [IO.File]::WriteAllText((Join-Path $data 'config.json'),'test preferences')
    [IO.File]::WriteAllBytes((Join-Path $data 'deepseek-key.dpapi'),[byte[]]@(1,2,3))
    [IO.File]::WriteAllText((Join-Path $harness 'keep.txt'),'other application data')
    foreach($name in @('quota-widget.exe','quota-cli.exe')){[IO.File]::WriteAllText((Join-Path $source $name),'fake binary')}
    foreach($name in @('setup.ps1','uninstall.ps1')){
        $text=Get-Content -LiteralPath (Join-Path $repo ('packaging\'+$name)) -Encoding UTF8 -Raw
        [IO.File]::WriteAllText((Join-Path $source $name),$text,[Text.UTF8Encoding]::new($true))
    }
    $files=@{}
    foreach($file in Get-ChildItem -LiteralPath $source -File){$files[$file.Name]=(Get-FileHash -LiteralPath $file.FullName).Hash.ToLower()}
    @{version='1.6.0';files=$files}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $source 'bundle-manifest.json') -Encoding UTF8
    $setup=Join-Path $source 'setup.ps1'
    $options=@{Destination=$dest;NoLaunch=$true;NoShortcut=$true;NoRegistration=(-not $ownRegistry)}
    & $setup @options
    Check ($LASTEXITCODE -eq 0) 'Synthetic install failed'
    if($ownRegistry){
        $registered=Get-ItemProperty -LiteralPath $reg
        Check ($registered.InstallLocation -eq $dest -and $registered.DisplayVersion -eq '1.6.0') 'Windows registration mismatch'
        Check ($registered.UninstallString -match 'uninstall.ps1' -and $registered.QuietUninstallString -match '-Silent') 'No Windows uninstall entry'
    }
    $owned=Join-Path $dest 'v1.0.0'
    $legacy=Join-Path $dest 'v0.9.0'
    foreach($dir in @($owned,$legacy)){New-Item -ItemType Directory -Path $dir|Out-Null}
    @{product='AIQuotaWidget';version='1.0.0'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $owned '.install-receipt.json') -Encoding UTF8
    [IO.File]::WriteAllText((Join-Path $legacy 'personal.txt'),'unknown ownership')
    $uninstall=Join-Path $dest 'uninstall.ps1'
    $mutex=[Threading.Mutex]::new($false,'Local\IanQuotaMonitor-v2')
    & powershell -NoProfile -ExecutionPolicy Bypass -File $uninstall -Destination $dest -Silent
    Check ($LASTEXITCODE -eq 1 -and (Test-Path -LiteralPath $owned)) 'Running instance was not protected'
    $mutex.Dispose();$mutex=$null
    & powershell -NoProfile -ExecutionPolicy Bypass -File $uninstall -Destination $dest -Silent
    Check ($LASTEXITCODE -eq 0) 'Preserving uninstall failed'
    Check (-not(Test-Path -LiteralPath $owned) -and -not(Test-Path -LiteralPath (Join-Path $dest 'v1.6.0'))) 'Owned versions left behind'
    Check (Test-Path -LiteralPath (Join-Path $legacy 'personal.txt')) 'Legacy/personal folder removed'
    Check ((Get-Content -LiteralPath (Join-Path $data 'config.json') -Raw) -eq 'test preferences') 'Default uninstall changed preferences'
    Check ((Get-Item -LiteralPath (Join-Path $data 'deepseek-key.dpapi')).Length -eq 3) 'Default uninstall deleted key'
    if($ownRegistry){Check (-not(Test-Path -LiteralPath $reg)) 'Uninstall entry left behind'}
    # Reinstall, reject linked trees before ANY destructive operation.
    $options.NoRegistration=$true
    & $setup @options
    Check ($LASTEXITCODE -eq 0) 'Reinstall failed'
    $outside=Join-Path $root 'outside';New-Item -ItemType Directory -Path $outside|Out-Null
    [IO.File]::WriteAllText((Join-Path $outside 'sentinel.txt'),'must survive')
    $junction=Join-Path $dest 'v9.0.0'
    New-Item -ItemType Junction -Path $junction -Target $outside|Out-Null
    & powershell -NoProfile -ExecutionPolicy Bypass -File $uninstall -Destination $dest -Silent -RemoveData
    Check ($LASTEXITCODE -eq 1 -and (Test-Path -LiteralPath $data) -and (Test-Path -LiteralPath (Join-Path $dest 'v1.6.0'))) 'Unsafe uninstall was not atomic'
    Check (Test-Path -LiteralPath (Join-Path $outside 'sentinel.txt')) 'Followed junction'
    [IO.Directory]::Delete($junction);$junction=$null
    & powershell -NoProfile -ExecutionPolicy Bypass -File $uninstall -Destination $env:USERPROFILE -Silent
    Check ($LASTEXITCODE -eq 1 -and (Test-Path -LiteralPath $data)) 'Broad root accepted'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $uninstall -Destination $dest -Silent -RemoveData
    Check ($LASTEXITCODE -eq 0 -and -not(Test-Path -LiteralPath $data)) 'Explicit data removal failed'
    Check (Test-Path -LiteralPath (Join-Path $harness 'keep.txt')) 'Deleted another AI application data'
    Write-Output ('PASS: uninstall; registry='+$ownRegistry+'; keep data/key by default; owned old versions; running/link/root protection; explicit own-data removal')
}finally{
    if($mutex){$mutex.Dispose()}
    $env:USERPROFILE=$savedProfile
    if($ownRegistry -and (Test-Path -LiteralPath $reg)){
        $entry=Get-ItemProperty -LiteralPath $reg
        if($entry.InstallLocation -and $entry.InstallLocation.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $reg -Force}
    }
    if($junction -and (Test-Path -LiteralPath $junction)){
        if(-not $junction.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test link'}
        [IO.Directory]::Delete($junction)
    }
    $resolved=[IO.Path]::GetFullPath($root)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\quota-uninstall-test-'
    $entries=@(Get-Item -LiteralPath $root -Force)+@(Get-ChildItem -LiteralPath $root -Recurse -Force)
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or @($entries|Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count){throw 'Unsafe test cleanup'}
    Remove-Item -LiteralPath $root -Recurse -Force
}
