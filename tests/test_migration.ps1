$ErrorActionPreference = 'Stop'
$file = Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging/setup.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Installer parse failed' }
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-DataMigration'},$true)
Invoke-Expression $function.Extent.Text
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('quota-migration-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$resolved=(Resolve-Path -LiteralPath $testRoot).Path
try {
    $old=Join-Path $testRoot 'old 中文'
    New-Item -ItemType Directory -Path $old | Out-Null
    foreach ($n in @('config.json','settings.json','last-good.json')) { [IO.File]::WriteAllText((Join-Path $old $n),'{}') }
    foreach ($failure in @(1,2,3,4)) {
        $data=Join-Path $testRoot ('target'+$failure)
        $script:copyCount=0; $script:fail=$failure
        function Copy-Item { param($LiteralPath,$Destination)
            $script:copyCount++
            if ($script:copyCount -eq $script:fail) { throw 'injected copy failure' }
            Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination
        }
        function Move-Item { param($LiteralPath,$Destination)
            if ($script:fail -eq 4) { throw 'injected commit failure' }
            Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
        }
        $failed=$false
        try { Invoke-DataMigration $old $data } catch { $failed=$true }
        if (-not $failed -or (Test-Path -LiteralPath $data)) { throw 'Migration left partial target' }
        Remove-Item Function:\Copy-Item,Function:\Move-Item
        Invoke-DataMigration $old $data
        if (@(Get-ChildItem -LiteralPath $data).Count -ne 3) { throw 'Retry incomplete' }
        Invoke-DataMigration $old $data  # identical completed migration is idempotent
    }
    foreach ($wrong in @((Join-Path $testRoot 'missing'), (Join-Path $old 'config.json'))) {
        $failed=$false
        try { Invoke-DataMigration $wrong (Join-Path $testRoot 'invalid') } catch { $failed=$true }
        if (-not $failed) { throw 'Invalid source accepted' }
    }
    [IO.File]::WriteAllText((Join-Path $testRoot 'target1/config.json'),'personal-new-data')
    $failed=$false
    try { Invoke-DataMigration $old (Join-Path $testRoot 'target1') } catch { $failed=$true }
    if (-not $failed -or [IO.File]::ReadAllText((Join-Path $testRoot 'target1/config.json')) -ne 'personal-new-data') { throw 'New data overwritten' }
    Write-Host 'PASS: copy 1/2/3 and commit faults; clean retries; idempotence; invalid source; conflict preservation'
} finally {
    $actual=(Resolve-Path -LiteralPath $testRoot).Path
    if ($actual -ne $resolved -or -not $actual.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup target mismatch' }
    $all=@((Get-Item -LiteralPath $actual -Force))+@(Get-ChildItem -LiteralPath $actual -Recurse -Force)
    if (@($all | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Unsafe cleanup links' }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $actual -Recurse -Force
}
