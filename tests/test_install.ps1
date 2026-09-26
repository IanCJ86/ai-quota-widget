param([string]$PythonPath = (Get-Command python.exe).Source)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("quota-install-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$resolvedRoot = (Resolve-Path -LiteralPath $testRoot).Path
try {
    $dest = Join-Path $testRoot "app with spaces"
    & (Join-Path $repo "install.ps1") -Destination $dest -PythonPath $PythonPath -SkipDependencies -NoAutostartPrompt
    foreach ($file in @("quota_monitor.py", "monitor_runtime.py", "harness_stats.py", "start.bat", "requirements.txt", "config.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $dest $file))) { throw "Missing installed file: $file" }
    }
    & $PythonPath -m py_compile (Join-Path $dest "quota_monitor.py") (Join-Path $dest "monitor_runtime.py") (Join-Path $dest "harness_stats.py")
    if ($LASTEXITCODE -ne 0) { throw "Installed source compilation failed" }
    $configPath = Join-Path $dest "config.json"
    $customConfig = '{"kimi_plan_name":"INSTALLER_TEST","glm_api_key":""}'
    [IO.File]::WriteAllText($configPath, $customConfig, [Text.Encoding]::UTF8)
    & (Join-Path $repo "install.ps1") -Destination $dest -PythonPath $PythonPath -SkipDependencies -NoAutostartPrompt
    if ([IO.File]::ReadAllText($configPath) -ne $customConfig) { throw "Upgrade replaced personal config" }
    $launcher = [IO.File]::ReadAllText((Join-Path $dest "start.bat"), [Text.Encoding]::Default)
    $pythonDir = Split-Path -Parent $PythonPath
    if (-not $launcher.Contains($pythonDir)) { throw "Launcher does not bind the selected interpreter" }
    Write-Host "PASS: fresh install, required files, compilation, upgrade config preservation, interpreter binding"
} finally {
    $actual = (Resolve-Path -LiteralPath $testRoot).Path
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($actual -ne $resolvedRoot -or -not $actual.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target changed; refusing removal"
    }
    $entries = @((Get-Item -LiteralPath $actual)) + @(Get-ChildItem -LiteralPath $actual -Recurse -Force)
    if (@($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Cleanup contains a reparse point; refusing removal"
    }
    Remove-Item -LiteralPath $actual -Recurse -Force
}
