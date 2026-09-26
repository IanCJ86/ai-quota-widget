---
name: ai-quota-widget-troubleshoot
description: 排查已装好的「AI 额度监控悬浮窗」(ai-quota-widget) 显示异常。当用户说“额度挂了 / 显示 -- / 一直是待更新 / 数字不更新 / 窗口不见了 / 闪屏”时使用。
---

# 排查额度监控悬浮窗

只处理**已安装但显示不对**的情况。若用户还没装，改用 `ai-quota-widget` 技能安装。

## 第一步：拿证据（不要猜）

安装目录（默认 `%USERPROFILE%\Desktop\quota-widget\`）下的 `debug.txt` 是关键：

```powershell
$dst = "$env:USERPROFILE\Desktop\quota-widget"      # 用户可能改过目录
Get-Content "$dst\debug.txt" -Raw | ConvertFrom-Json |
  Select-Object pid, ui_error, errors, status_text
```

同时确认进程与版本：

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'quota_monitor' } |
  Select-Object ProcessId, CommandLine
```

## 第二步：按 `errors` 定位

| `errors` 的键 | 含义 | 怎么办 |
| --- | --- | --- |
| `kimi` | Kimi CLI 未登录 / 凭据失效 | 让用户运行一次 Kimi Code 登录 |
| `codex` | Codex CLI 未安装、未登录，或运行时版本太旧 | 更新 Codex CLI 后重新登录 |
| `deepseek` = `HTTP401` | DeepSeek Key 无效 | 用户重新生成 Key，在右键菜单里加密保存 |
| `deepseek` = `URLError` / 超时 | 网络不通（常需代理） | 让用户确认代理是否开着 |
| `glm` | Key 无效或没有有效 GLM Coding Plan | 核对 Key 与套餐；没有套餐时该卡片本就取不到数据 |
| 雷达相关 | `codexreset.org` 这个第三方站点不可达或改版 | 不影响其它卡片；可在右键菜单关掉「Codex 重置雷达」 |

`errors` 为空但某些行是 `--` → 看 `status_text`：

- "加载中…" → **首次查询尚未回来**，等 20~30 秒再看；若一直如此，说明**一个可用来源都没有**
- "待更新:N 项" → 有 N 个来源本轮没成功，回到 `errors` 看是哪些
- 某行备注是"旧 HH:MM" → 该来源本轮没成功，正显示上一次的数据（不是坏了）

## 第三步：常见"假故障"

| 用户描述 | 真实原因 |
| --- | --- |
| "数字不更新了" | 备注显示"旧 HH:MM"，说明只是这一轮没成功，鼠标悬停托盘图标可看到上次成功时间 |
| "窗口不见了" | 点过 ✕ = 收进托盘（不是退出）。托盘图标双击唤回；右键菜单"退出"才结束程序 |
| "装完没变化" | 只替换了部分文件（必须 `quota_monitor.py` + `monitor_runtime.py` + `harness_stats.py` 三个一起），或旧进程还在跑 |
| "左上角闪出一个一样的窗口" | 2026-09-26 之前的老版本问题（自动化测试窗口落到桌面）；升级到 v1.2.0 以上即可 |
| "它是不是在偷我的 Key" | 程序只读本机已登录 CLI 的凭据，Key 用 Windows DPAPI 加密存本机，不上传；可用防火墙/抓包自行验证，源码 MIT 公开 |

## 修复后的确认

重新启动后等 20~30 秒，再读一次 `debug.txt`：`errors` 应变空、`ui_error` 为 `null`。
**不要只看窗口好看就说修好了**——要看到具体的数值字段回来。

## 禁止事项

- 不要为了"让用户安心"而回显任何 Key / token
- 不要在用户机器上装额外的诊断工具或修改系统设置
- 不确定原因时，如实说"需要更多信息"，并请用户提供 `debug.txt` 内容
