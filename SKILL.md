---
name: ai-quota-widget
description: 在 Windows 上安装、配置、验证或排查「AI 额度监控悬浮窗」(ai-quota-widget)。当用户说“帮我装个看 AI 额度的小挂件”“Codex / Kimi / GLM / DeepSeek 还剩多少额度”“额度监控装不上 / 显示 -- / 全是待更新”时使用本技能。
---

# AI 额度监控悬浮窗（ai-quota-widget）

Windows 桌面小挂件：一屏显示 **Codex / Kimi / GLM / DeepSeek** 的剩余额度、重置券、计费时段与今日消耗。
仓库：https://github.com/IanCJ86/ai-quota-widget （MIT 许可）

## 什么时候用

- 用户想装一个"随时能看到 AI 订阅还剩多少额度"的桌面挂件
- 用户已经装了但**显示不对**（全是 `--`、一直是"加载中…"、"待更新:N 项"、某个来源报错）
- 用户换了电脑 / 重装系统，要恢复这个挂件

## 前提（先检查，不要跳过）

1. 系统是 **Windows**；需要 **Python 3.10+（含 tkinter）**
2. 至少要**登录过一种** AI CLI，否则装好了也没数据：
   - Kimi Code CLI（`kimi`），或
   - Codex CLI（`codex`）
3. **绝对不要向用户索取 API Key、token 或密码**。GLM / DeepSeek 的 Key 由用户自己在右键菜单里填；程序把 Key 用 Windows DPAPI 加密存在本机，不上传任何数据。
4. **重置雷达**这一行的数据来自**第三方社区站点 codexreset.org**（非 OpenAI 官方、与本项目无关联），只是"重置概率"预测；用户若介意，可在右键菜单关掉「Codex 重置雷达」。**装好后要主动说明这一点**，不要让用户以为那是官方数据。

## 安装步骤

```powershell
git clone https://github.com/IanCJ86/ai-quota-widget.git
cd ai-quota-widget
powershell -ExecutionPolicy Bypass -File install.ps1
```

如果用户没有 git，让他从 GitHub 页面下载 ZIP 解压后，对同目录执行 `install.ps1`。

安装脚本会：检查 Python → 安装 `Pillow` / `pystray`（Python < 3.14 还会装 `backports.zstd`）→ 把
`quota_monitor.py`、`monitor_runtime.py`、`harness_stats.py` 按 `runtime-files.txt` 清单**复制全部运行模块（当前 14 个）**到安装目录
（默认 `%USERPROFILE%\Desktop\quota-widget\`，用户可自定义）→ 生成 `start.bat` → 询问是否开机自启。

> ⚠️ **必须按 `runtime-files.txt` 清单复制全部模块（当前 14 个）；安装器会建立**版本化持久虚拟环境**并逐个校验清单**。只替换其中一个会导致程序起不来或功能缺失（例如缺 `harness_stats.py` 会让 token 统计失效）。

## 配置（问用户这几项，不知道就留默认）

安装目录下的 `config.json`：

| 字段 | 说明 |
| --- | --- |
| `renew_kimi` / `renew_codex` / `renew_glm` | 续订日期，只用于显示，格式 `MM-DD` |
| `kimi_plan_name` / `glm_plan_name` / `codex_plan_name` | 套餐显示名，例如 `"Andante"`、`"Pro"`、`"Pro 20x"` |
| `show_kimi` / `show_codex` / `show_glm` / `show_deepseek` | 是否显示对应卡片 |
| `theme` | `dark` / `light` / `glass`（毛玻璃） |
| `deepseek_token_metric` | `total`（默认）/ `fresh` / `off` |

这些**用户日后都能在右键菜单里改**，不必一次问全。

## 先跑体检（离线、脱敏）

```powershell
python quota_monitor.py --doctor --data-dir "<安装目录>"
```

`--doctor` 不上网、不打印密钥/路径/账号/余额，会报告：Python 与依赖、模块清单（当前 14/14）、各来源凭据是否存在、上次成功时间、实例是否在跑。
退出码：`0` 正常 ｜ `1` 有告警 ｜ `2` 失败。装完先看它，再启动。

## 验收（必须做，不要凭感觉说"装好了"）

启动后等 **20~30 秒**（首次要查询四个来源），然后读安装目录下的 `debug.txt`：

- `"errors": {}`，且 `"data"` 里有 `k5_pct` / `c5_pct` / `ds_balance` 之类的数值 → **成功**
- `errors` 里出现某个来源 → 见下面的排错表，**不要**把所有 `--` 当成同一种故障
- 另可用 `Get-Process pythonw` 确认进程在跑，或直接看屏幕右下角

## 排错表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 一个来源显示 `--` + "等待更新" | 该来源从未查询成功 | 看 `debug.txt` 的 `errors` 里对应来源 |
| `errors.kimi` | 没登录 Kimi Code CLI | 让用户先运行一次 Kimi Code 完成登录 |
| `errors.codex` | Codex CLI 未安装/未登录，或运行时太旧（重置券需要较新的 codex） | 更新并登录 Codex CLI |
| `errors.deepseek` + `HTTP401` | Key 无效或过期 | 让用户重新生成 Key，并在右键菜单「DeepSeek 设置 → 安全保存 API Key…」里填 |
| 底部"待更新:N 项" | 有 N 个来源本轮没拿到新数据 | 结合 `errors` 判断，不是统一的故障 |
| 窗口一直"加载中…" | **一个可用来源都没有**（没登录任何 CLI / 卡片全关） | 先登录 Kimi 或 Codex；或右键菜单把卡片勾上 |
| 双击 `start.bat` 没反应 | 前台报错被吞掉 | 用 `python quota_monitor.py` 前台运行看报错 |
| 窗口不见了 | 点过 ✕ 收进了托盘 | 托盘图标双击唤回；右键菜单"退出"才真正结束 |
| 装了新版但功能没变 | 只替换了部分文件，或旧进程还在 | 先从托盘菜单**退出**旧程序，再复制**三个模块**，重新启动 |
| Windows 提示"未知发布者" | 未做代码签名 | 属于正常现象，源码在 GitHub 可自行审计 |

## 还能用的命令行

| 命令 | 用途 |
| --- | --- |
| `--version` | 打印版本号 |
| `--doctor [--data-dir DIR]` | 离线脱敏体检（首选） |
| `--json [--fresh]` | 机器可读快照（单行 JSON，不含密钥） |
| `--once [--fresh]` | 终端一次性摘要，适合"先看效果再决定装不装" |
| `--install [--dest DIR]` | 安装/升级；检测到实例在跑会**拒绝**并提示先退出，不会强制结束进程 |

## 禁止事项

- 不向用户索取任何 Key / token / 密码，也不要在对话里回显用户的凭据
- 不修改用户的全局 git 身份配置
- 不擅自改动用户 `config.json` 里已有的套餐名或续订日期
- 不承诺"额度官方实时""无限量"之类说法：Codex 的额度来自本机快照，DeepSeek 的"今日"是余额差额估算
