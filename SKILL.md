---
name: ai-quota-widget
description: 在 Windows 上安装、升级、配置或验证 AI Quota Widget 额度监控悬浮窗。用于用户明确要安装或操作这个工具；单纯询问平台额度，不默认安装软件。
---

# AI 额度监控悬浮窗

显示 Kimi / Codex / GLM 订阅额度，以及 DeepSeek 余额与本机 Harness token。仓库：https://github.com/IanCJ86/ai-quota-widget （MIT）。

## 环境与已有安装

- Windows，Python 3.10+且含Tk。缺少时按仓库 AGENTS.md 的安装指引处理，不把 Windows Store 的python占位命令当作有效解释器。
- 有一种来源即可：已登录 Kimi / Codex CLI，**或** GLM Coding Plan / DeepSeek Key。仅用Key不必安装CLI；尚未配置来源可以先安装，但不能说已取得额度。
- 找到已有安装目录和start.bat，升级用同一目录并保留个人配置、加密凭据与统计。运行中先正常退出本工具，不批量结束Python或其他AI进程。
- 不索取/回显密钥。让用户在菜单安全保存，或复用既有环境变量。DPAPI保护本机文件；查询仍需向对应官方服务发送认证请求，不能说“凭据从不离开电脑”。换电脑不要直接复制旧DPAPI文件当作已恢复。

## 安装与配置

优先使用GitHub**最新正式Release**的 `windows-source.zip`，不把开发分支当正式版。解压完整ZIP后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -NoAutostartPrompt
```

可用 `-Destination "实际安装目录"` 和 `-PythonPath "已验证的python.exe路径"` 指定位置和解释器。开机自启按用户选择。Git用户可检出正式tag再运行同一安装器；不覆盖有未提交改动的仓库。

安装器按 `runtime-files.txt` 复制并校验**全部模块**，建立版本化持久环境和start.bat。不要只复制“三个文件”，不要用 `--skip-deps` 跳过新电脑的依赖检查。安装失败按实际错误处理，不关闭安全防护或强行覆盖来宣称成功。

只改用户指定设置，其他保留；套餐名和续订日期只是显示信息，不据此推断订阅权限。

| 字段 | 用途 |
| --- | --- |
| `renew_kimi` / `renew_codex` / `renew_glm` | 续订日期，MM-DD，仅显示 |
| `kimi_plan_name` / `glm_plan_name` / `codex_plan_name` | 套餐显示名 |
| `show_kimi` / `show_codex` / `show_glm` / `show_deepseek` | 显示用户实际使用的来源 |
| `theme` | glass / dark / light / steam / fuel / ink；默认以所安装版本为准，升级保留选择 |
| `deepseek_token_metric` | total / fresh / off；本机日志统计，非官方账单 |

优先通过右键菜单配置。直接编辑config.json前退出工具，再改并重启，避免运行中的设置覆盖文件。

## 诊断与验收

1. 从**安装目录start.bat**获取绑定的Python路径，用它运行：

   ```powershell
   & "<start.bat绑定的python.exe>" "<安装目录>\quota_monitor.py" --doctor --data-dir "<安装目录>"
   ```

   不用另一个全局Python冒充安装环境。doctor离线且脱敏，不含密钥/路径/账号/余额；0正常、1告警、2失败。它检查环境和缓存，**不能证明联网成功**。
2. 启动start.bat，核对版本和窗口。首次查询通常数十秒，重试可能更久，不以固定等待时间替代成功证据。
3. 必要时在本机核对debug.txt的app_version、pid、updated、ui_error、errors、success_at，只验证已启用且已配置的来源；成功时间应晚于启动、对应数值回来。`errors={}`、缓存旧值或存在pythonw进程本身均不足以证明成功。
4. 验证右键菜单、关闭到托盘与恢复。汇报目录、版本、已验证来源和未配置/失败项；原始debug、个人余额截图不发公开渠道。

向用户说明：数据按周期查询，不是实时推送；DeepSeek今日为余额差额估算；雷达来自 **codexreset.org 第三方预测，非OpenAI官方**，可关闭“重置雷达（第三方站点）”。

## CLI与排错

- `--version`：版本。
- `--doctor --data-dir DIR`：离线脱敏诊断；公开反馈也可用右键“复制脱敏诊断”。
- `--once` / `--json`：默认读缓存，可能无数据；显式加 `--fresh` 才联网，输出含个人额度/余额，不整份公开。
- `--install --dest DIR --no-autostart`：共用安装器，运行中拒绝覆盖，不强制杀进程。

异常时读取 [排错技能](skills/ai-quota-widget-troubleshoot/SKILL.md)，接口见 [CLI说明](docs/cli-and-install.md)。若只复制了本技能，先获取对应正式版本仓库，勿假定相对路径已存在。
