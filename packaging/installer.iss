; A Chinese per-user wizard around the SAME verified offline installer as ZIP.
#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef BundleDir
  #error BundleDir required
#endif
[Setup]
AppId=AIQuotaWidget.BundleInstaller
AppName=AI 额度监控
AppVersion={#AppVersion}
AppPublisher=临界思潮
DefaultDirName={%USERPROFILE}\.ai-quota-widget-app
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=ai-quota-widget-v{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
SetupLogging=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{tmp}\quota-bundle"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CheckForMutexes('Local\IanQuotaMonitor-v2') then
    Result := '额度监控正在运行。请在右键菜单选择“退出”，再安装；个人配置不会丢失。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Args, Root: String; ExitCode: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  Args := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\quota-bundle\setup.ps1') + '"';
  Root := ExpandConstant('{param:INSTALLROOT|}');
  if Root <> '' then begin
    if Pos('"', Root) > 0 then RaiseException('安装目录无效。');
    Args := Args + ' -Destination "' + Root + '"';
  end;
  if ExpandConstant('{param:NOLAUNCH|}') = '1' then Args := Args + ' -NoLaunch';
  if ExpandConstant('{param:NOSHORTCUT|}') = '1' then Args := Args + ' -NoShortcut';
  if ExpandConstant('{param:NOREGISTRATION|}') = '1' then Args := Args + ' -NoRegistration';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Args,
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    RaiseException('无法启动安装。个人配置和旧版已保留。');
  if ExitCode <> 0 then
    RaiseException('安装未完成。请检查目录写入权限或重新下载成品包，旧版与个人配置保留。');
end;
