@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo 安装未完成，请保留上方错误信息。
  pause
  exit /b 1
)
echo 安装完成，软件已启动。此窗口即将关闭，可从桌面快捷方式再次打开。
timeout /t 2 /nobreak >nul 2>&1
exit /b 0
