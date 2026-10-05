# Per-user uninstall. Only exact receipted version directories are removable.
[CmdletBinding()]
param([string]$Destination=$PSScriptRoot, [switch]$Silent, [switch]$RemoveData)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -le 5) {
    $env:PSModulePath=(Join-Path $PSHOME 'Modules')+';'+$env:PSModulePath
}
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$lock=$null
function Assert-Safe([string]$Path) {
    $cursor=[IO.Path]::GetFullPath($Path)
    while($cursor){
        if((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw '路径包含链接，未卸载。'}
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
}
function Assert-Tree([string]$Path) {
    Assert-Safe $Path
    foreach($item in (Get-ChildItem -LiteralPath $Path -Force -Recurse)){
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw '目录包含链接，未卸载。'}
    }
}
try {
    $root=[IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if($root -eq [IO.Path]::GetPathRoot($root).TrimEnd('\') -or $root -eq [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')){throw '不能卸载宽泛目录。'}
    Assert-Safe $root
    $marker=Join-Path $root '.install-root.json'
    Assert-Safe $marker
    $receipt=Get-Content -LiteralPath $marker -Encoding UTF8 -Raw|ConvertFrom-Json
    if($receipt.product -ne 'AIQuotaWidget' -or $receipt.root -ne $root -or $receipt.schema -ne 1){throw '没有匹配的安装回执，未卸载。'}
    $created=$false
    $lock=[Threading.Mutex]::new($false,'Local\AIQuotaWidget-Installer',[ref]$created)
    if(-not $created){throw '另一个安装或卸载任务正在运行。'}
    try{$running=[Threading.Mutex]::OpenExisting('Local\IanQuotaMonitor-v2')}catch [Threading.WaitHandleCannotBeOpenedException]{$running=$null}
    if($running){$running.Dispose();throw '请先在额度监控右键菜单选择“退出”，再卸载。'}
    if(-not $Silent){
        Add-Type -AssemblyName System.Windows.Forms
        $answer=[Windows.Forms.MessageBox]::Show('卸载 AI 额度监控？账户配置、Key和历史默认保留。','AI 额度监控',[Windows.Forms.MessageBoxButtons]::OKCancel,[Windows.Forms.MessageBoxIcon]::Question)
        if($answer -ne [Windows.Forms.DialogResult]::OK){exit 0}
        if(-not $RemoveData){
            $answer=[Windows.Forms.MessageBox]::Show('是否同时清除本工具的账户配置、加密Key和历史？这不能撤销。选择“否”保留，下次安装可继续使用。不会删除其他AI软件的登录或日志。','是否清除本工具数据',[Windows.Forms.MessageBoxButtons]::YesNo,[Windows.Forms.MessageBoxIcon]::Warning,[Windows.Forms.MessageBoxDefaultButton]::Button2)
            $RemoveData=$answer -eq [Windows.Forms.DialogResult]::Yes
        }
    }
    # Validate ALL removal targets before deleting anything. Never delete root recursively.
    $versions=@()
    foreach($dir in (Get-ChildItem -LiteralPath $root -Directory -Force)){
        if($dir.Name -notmatch '^v\d+\.\d+\.\d+$'){continue}
        Assert-Tree $dir.FullName
        $file=Join-Path $dir.FullName '.install-receipt.json'
        if(-not(Test-Path -LiteralPath $file)){continue}
        $item=Get-Content -LiteralPath $file -Encoding UTF8 -Raw|ConvertFrom-Json
        if($item.product -eq 'AIQuotaWidget' -and $item.version -eq $dir.Name.Substring(1)){$versions+=$dir.FullName}
    }
    $data=Join-Path $env:USERPROFILE '.ai-quota-widget'
    if($RemoveData -and (Test-Path -LiteralPath $data)){Assert-Tree $data}
    foreach($name in @('uninstall.ps1','.install-root.json')){Assert-Safe (Join-Path $root $name)}
    $shell=New-Object -ComObject WScript.Shell
    $links=@()
    foreach($folder in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'),[Environment]::GetFolderPath('Startup'))){
        if(-not $folder){continue} # Fresh profiles may not have a Startup folder.
        $path=Join-Path $folder 'AI 额度监控.lnk'
        if(Test-Path -LiteralPath $path){
            Assert-Safe $path
            $target=$shell.CreateShortcut($path).TargetPath
            if($target -and @($versions|Where-Object { (Join-Path $_ 'quota-widget.exe') -eq $target }).Count){$links+=$path}
        }
    }
    foreach($path in $versions){Remove-Item -LiteralPath $path -Recurse -Force}
    foreach($path in $links){Remove-Item -LiteralPath $path -Force}
    $reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIQuotaWidget'
    if(Test-Path -LiteralPath $reg){
        $entry=Get-ItemProperty -LiteralPath $reg
        if($entry.InstallLocation -eq $root){Remove-Item -LiteralPath $reg -Recurse -Force}
    }
    if($RemoveData -and (Test-Path -LiteralPath $data)){Remove-Item -LiteralPath $data -Recurse -Force}
    foreach($name in @('uninstall.ps1','.install-root.json')){
        $path=Join-Path $root $name
        if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path -Force}
    }
    Write-Host 'AI 额度监控已卸载。其他AI软件的数据和未识别目录未修改。'
    if(-not $RemoveData){Write-Host '账户配置和加密Key已保留。'}
}catch{
    Write-Host ('卸载未完成：'+$_.Exception.Message) -ForegroundColor Red
    if(-not $Silent){
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(('卸载未完成：'+$_.Exception.Message),'AI 额度监控',[Windows.Forms.MessageBoxButtons]::OK,[Windows.Forms.MessageBoxIcon]::Warning)|Out-Null
    }
    exit 1
}finally{if($lock){$lock.Dispose()}}
