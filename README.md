# AI Quota Widget（额度监控悬浮窗）

一个 Windows 桌面悬浮小工具，实时显示 **Kimi Code** 和 **Codex** 的用量额度：

![screenshot](screenshot.png)

## 功能

- 显示 Kimi Code / Codex 的 **每 5 小时** 与 **每周** 额度剩余百分比
- 显示额度重置时间（5 小时窗显示倒计时，每周窗显示具体时间）
- 显示套餐名与续订日期（可自行配置）
- 每 15 分钟自动刷新，刷新时刻对齐整刻（:00 / :15 / :30 / :45）
- 双击窗口立即刷新；右键菜单：置顶 / 立即刷新 / 退出
- 底部 ＋ / － 按钮调节窗口透明度，✕ 关闭
- 无边框、可拖动、可置顶，纯 tkinter 绘制

## 使用方法

1. 安装 Python 3（仅用到标准库，无需 pip 安装任何依赖）
2. 本机需已登录 Kimi Code CLI（凭证位于 `~/.kimi-code`）和 Codex CLI（`~/.codex`，需可调用 `codex app-server`）
3. 下载本仓库，双击 `start.bat` 即可启动（无控制台窗口）

也可以直接运行：

```
python quota_monitor.py
```

## 刷新逻辑

- 启动时立即刷新一次，之后每 15 分钟自动刷新，且刷新时刻对齐时钟整刻（:00/:15/:30/:45），避免各自为政的漂移
- 双击窗口任意位置立即刷新
- Kimi 数据来自官方接口 `api.kimi.com/coding/v1/usages`；access_token 过期时会用本地 refresh_token 自动续期（client_id 为 CLI 公开值）
- Codex 数据通过本机 `codex app-server`（stdio JSON-RPC）读取 `account/rateLimits/read`
- 所有凭证只从本机 `~/.kimi-code` 与 `~/.codex` 读取，网络请求仅发往官方域名，代码不打印、不上传任何 token

## 配置项

打开 `quota_monitor.py`，文件顶部的「个人配置」区块有几个常量需要按自己的情况修改：

| 常量 | 说明 | 示例 |
| --- | --- | --- |
| `RENEW_KIMI` | Kimi 续订日期，仅用于显示，格式 `MM-DD` | `"09-01"` |
| `RENEW_CODEX` | Codex 续订日期，仅用于显示 | `"09-15"` |
| `KIMI_PLAN_NAME` | Kimi 套餐显示名（接口只返回等级，这里覆盖显示） | `"Allegro"` |
| `CODEX_PLAN_SUFFIX` | Codex 套餐名后缀，追加在接口返回值后 | `" 20x"` |

## 支持范围与局限

- 目前仅支持 **Kimi Code** 和 **Codex** 两家，暂无 Claude / DeepSeek / GLM 等方案
- 仅支持 Windows（依赖本机 CLI 凭证与 tkinter）
- 套餐名与续订日期无法从接口自动读取，需要手动配置（见上文「配置项」）

欢迎 issue / PR 扩展更多服务商。

## 免责声明

本项目为个人学习/自用工具，与 Moonshot AI、OpenAI 无任何隶属或官方关系。接口与凭证读取方式依赖第三方客户端的本地行为，可能随其版本更新而失效。请遵守相关服务条款，使用风险自负。

## License

MIT © IanCJ86
