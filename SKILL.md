---
name: ai-quota-widget
description: 在 Windows 安装、升级或配置 AI Quota Widget 额度监控悬浮窗。仅用户明确要安装或操作本工具时使用；询问额度本身不自动安装。
---

# AI 额度监控：快装快用

默认中文。目标是用户打开软件并看到快速设置，不是为每台电脑重新搭建开发环境。

## 安装

- 官方仓库：https://github.com/IanCJ86/ai-quota-widget 。优先正式 Release 的 `windows-x64.zip`，SHA256 与同版 `SHA256SUMS.txt` 核对，完整解压后执行包内 `setup.ps1`。软件自带运行时，不装 Python/npm/pip。用户也可双击 `install.cmd` 或直接打开 `quota-widget.exe`。
- 用户已说用 DeepSeek 等某一家就沿用，不再重复问。软件首次打开会识别已存在的登录/凭据；中文快速设置选择卡片，GLM/DeepSeek Key 在本机掩码框填写，可稍后设置。不要在聊天索取或回显 Key。
- 套餐名、续订日期、自启不是安装前置条件。不强制四家全配，不为无凭据账户等接口或反复 sleep。
- 原程序正在运行时正常退出再升级；不批量结束 Python/其他 AI 进程。v1.4.5起个人数据在 `%USERPROFILE%\.ai-quota-widget`，首次启动从旧AppData目录迁移并保留原文件，已有共享数据不覆盖。不要把Agent的旧AppData私有副本当成当前配置。
- 源码旧版迁移仅针对用户指明的目录：`setup.ps1 -ExistingDataDir "旧安装目录"`；本机同一 Windows 用户才可复用 DPAPI。目标有数据不覆盖，不跨电脑复制密钥作为配置完成的证据。

## 有限核对与交付

- 使用成品包自带 `quota-cli.exe --doctor`。它离线脱敏，0正常、1待配置/告警；不证明联网成功。不要拿全局 Python 做成品包诊断。
- 安装完成、窗口打开和账户查询成功分开说。无来源时报告“已安装，待配置”，可以结束；已有凭据才核对相应数据。不得为普通安装自写多套菜单探测脚本。
- 需要反馈时优先右键“复制脱敏诊断”，不公开原始 debug、余额或身份路径。debug 在无来源时也会写入，但不需依赖它才能完成普通安装。
- 用户试用拖动、右键、托盘恢复；若明确要求开发验收，按工程测试处理，不强加给普通安装。

## 排错/源码

仅成品包缺失、平台不支持或用户明确开发才走源码路线，见 [技术说明](docs/cli-and-install.md)。安装故障读 [排错技能](skills/ai-quota-widget-troubleshoot/SKILL.md)，先识别成品/源码，不把“未配置”当依赖坏了。

额度周期查询，非实时推送；DeepSeek 今日金额是余额差额估算；雷达来自 codexreset.org，非 OpenAI 官方。说明这些边界即可，不扩大安装任务。
