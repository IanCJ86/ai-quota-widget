# AI Quota Widget（额度监控悬浮窗）

一个 Windows 桌面悬浮小工具，定时显示 **Kimi Code**、**Codex**（可选 **GLM**）的用量额度：

![screenshot](screenshot.png)

## v1.1.0：稳定性与托盘更新

- 通知区域显示透明背景的大号额度数字；✕ 隐藏到托盘，点击图标或再次运行启动器可恢复，退出请用右键菜单。
- 每个来源独立查询，最多两个查询进程同时运行；查询结束即释放。超时自动终止本工具启动的进程树，不影响其他 Codex 任务。
- 瞬时错误每轮最多三次，间隔 2 秒、5 秒；仍失败则等待 5 分钟。认证等明确错误等待正常周期，不持续轰击接口。
- 每个来源保留独立成功时间；失败或启动恢复的缓存显示为灰色旧数据，避免把历史额度误认为实时值。
- 社区明确没有活跃投票时显示“暂无投票”，与网络失败区分。
- 单实例、休眠返回补查、配置/缓存原子写入；托盘不可用时保留主窗口。
- 数字/新旧状态不变时不重绘图标，空闲不常驻查询子进程。

升级前先从右键菜单退出旧版，再运行 `install.ps1`，已有 `config.json` 会保留。新版必须同时包含 `quota_monitor.py`、`monitor_runtime.py`，托盘依赖由安装器安装。

## 30 秒安装（让 AI agent 帮你装）

不想自己动手？把这句话发给你的 AI agent（Kimi Code / Codex / Claude Code 等均可）：

> 帮我安装 ai-quota-widget：https://github.com/IanCJ86/ai-quota-widget ，读仓库里的 AGENTS.md 按步骤执行。

agent 会完成全部工作，你只需要口述续订日期和套餐名。它实际执行的命令是：

```bash
git clone https://github.com/IanCJ86/ai-quota-widget.git
cd ai-quota-widget
powershell -ExecutionPolicy Bypass -File install.ps1
```

也可以完全手动：下载仓库 → 跑 `install.ps1` → 编辑桌面 `quota-widget\config.json` → 双击 `start.bat`。

## 功能

- 显示 Kimi Code / Codex 的 **每 5 小时** 与 **每周** 额度剩余百分比
- **Codex 重置券**：显示账户里可用的「全额重置」券张数与到期日；0 张时该行自动隐藏，可在 `Codex 设置` 里关掉
- **Codex 全球重置雷达**：显示 [codexreset.org](https://codexreset.org) 的 24/48 小时预测。这是第三方公共信号，不统计个人赠送/补偿重置卡，也不代表个人账户真值
- **可选 DeepSeek 余额卡片**：填入 API Key（见「配置项」）后显示账户余额与**今日消耗**；DeepSeek 是按量付费，官方只有余额、没有百分比额度与用量接口，所以这张卡片显示金额，余额偏低时自动变色提醒。余额行右侧显示当前计费时段：**梁文峰**（北京时间周一至周五 9:00–12:00、14:00–18:00，单价翻倍）或**梁文谷**（其余时段、含周末，半价）；「今日」行右侧可选显示**本机 DeepSeek Harness 当天用掉的 token 数**（`deepseek_token_metric`）
- **可选 GLM Coding Plan 卡片**：在 config.json 填入 `glm_api_key` 并启用 `show_glm`，显示 5 小时 / 每周额度与重置时间（需有效的 GLM Coding Plan Key，见「配置项」）
- 显示额度重置时间（5 小时窗显示倒计时，每周窗显示具体时间）
- 显示套餐名与续订日期（接口不返回；**右键 → Kimi / Codex / GLM 设置 里直接选**，也可在 `config.json` 里改）
- 套餐预设：Kimi（Andante / Moderato / Allegretto / Allegro）、Codex（Go / Plus / Pro 5x / Pro 20x）、GLM（Lite / Pro / Max）；自定义名会保存为显示名，不额外积累菜单项
- 各信源成功后每 15 分钟自动刷新，不再对齐整刻钟
- 双击窗口立即刷新；右键菜单：置顶 / 立即刷新 / 主题 / 退出
- 右键可分别勾选显示 Kimi / Codex / GLM 卡片，选择写回 `config.json`，重启后自动沿用
- 菜单里的选择（卡片开关、主题、套餐、续订日期、雷达窗口、托盘指标）以及**透明度与窗口位置**都会记进 `config.json`，下次启动照旧；窗口位置只在屏幕范围内复用（换了显示器不会跑到屏幕外）
- 右键可控制 Codex 每 5 小时窗口；未手动覆盖时 Pro 默认隐藏，其他套餐默认显示；雷达可选择 24 小时或 48 小时窗口
- **三套主题**：黑夜 / 白天 / 毛玻璃（亚克力模糊，透出桌面背景；老系统不支持 Acrylic 时自动降级为普通纯色渲染，不影响使用）
- 底部 ＋ / － 按钮微调窗口透明度（3% 步进），✕ 隐藏到托盘
- 无边框、可拖动、可置顶、圆角（Win11 原生抗锯齿）
- 高 DPI 屏幕原生渲染，字体清晰不毛边；窗口尺寸自动贴合内容
- 主窗口使用 tkinter；托盘使用 Pillow 与 pystray

## 使用方法

1. 安装 Python 3.10+（含 tkinter）；`install.ps1` 会通过 pip 安装 `requirements.txt` 中的托盘依赖
2. 本机需已登录 Kimi Code CLI（凭证位于 `~/.kimi-code`）和 Codex CLI（`~/.codex`，需可调用 `codex app-server`）
3. 下载本仓库，运行 `install.ps1`，再双击桌面 `quota-widget` 中的 `start.bat`。手动在仓库运行时，先执行 `python -m pip install -r requirements.txt`

也可以直接运行：

```
python quota_monitor.py
```

## 刷新逻辑

- 启动时恢复缓存并立即查询；每个来源成功后 15 分钟再查，失败只重试对应来源
- 双击窗口任意位置立即刷新
- Kimi 数据来自官方接口 `api.kimi.com/coding/v1/usages`；access_token 过期时会用本地 refresh_token 自动续期（client_id 为 CLI 公开值）
- Codex 数据通过本机 `codex app-server`（stdio JSON-RPC）读取 `account/rateLimits/read`。该接口返回的是本机 Codex 保存的**快照**，不带采集时间：某个窗口的重置时间若已经过去，说明这份数字属于上一个窗口，界面会把该卡片标灰并显示「窗口已过期」，同时计入底部「待更新」，不把历史额度当成实时值（窗口尚未结束的滞后无法被识别，见「支持范围与局限」）
- Codex 的重置券来自同一次 app-server 会话的 `account/rateLimits/read`（`rateLimitResetCredits`）。程序优先使用 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` 中最新的运行时；桌面应用升级后遗留的旧 `bin\codex.exe` 没有这个字段，只会作为兜底
- 雷达数据来自 `codexreset.org` 的第三方公开页面，不含任何个人凭证
- GLM 数据来自 `open.bigmodel.cn/api/monitor/usage/quota/limit`（国际版 `api.z.ai` 同路径），用配置的 apiKey 鉴权
- DeepSeek 数据来自官方 `api.deepseek.com/user/balance`（Bearer Key）；官方没有用量/额度接口（实测 `/user/usage`、`/dashboard/billing/usage` 均为 404），所以只能显示余额。「今日消耗」是本机估算：以当天第一次读到的余额为起点，按之后每次余额的减少量累加，充值会自动抬高起点（不会出现负数），跨天归零；起点之前（当天 Widget 没运行时）的消耗统计不到
- DeepSeek 的**计费时段**按官方规则判断：高峰 = 北京时间周一至周五 9:00–12:00 与 14:00–18:00，其余（含周末）为空闲、单价减半。**中国法定节假日没有内置日历**，所以节假日的白天会按高峰显示（实际按空闲计费）
- 「今日」行的 token 数来自**本机 DeepSeek Harness 的会话记录**（`~/.dsh/sessions`，每条请求都带 token 用量），因此它只覆盖这台机器上 Harness 的用量，不代表账户全部消耗；需要 zstd 支持（Python 3.14+ 或 `zstandard` 包），不支持时该位置留空。缓存读取量通常远大于新 token（同一段上下文每轮都会命中缓存），`total` 会把它们算进去，所以数字可能很大而金额很小
- CLI 凭证只从本机读取，仅用于对应官方服务的认证，不发送给雷达网站，不打印或写入诊断文件

## 配置项

**推荐用右键菜单，不用编辑任何文件**：右键 → `Kimi 设置` / `Codex 设置` / `GLM 设置`：

- **套餐**：单选预设（Kimi：Andante / Moderato / Allegretto / Allegro；Codex：Go / Plus / Pro 5x / Pro 20x；GLM：Lite / Pro / Max），或「自定义…」输入并保存显示名
- **续订日期**：「设为下个月今天」「设为本月最后一天」一键搞定，或「选择日期…」弹出月/日下拉选择器（免键盘输入，初始值回填当前日期；选到 2月31日 这类不存在的日期时自动调整为该月最后一天并提示）
- **主题**：右键 → `主题` → 黑夜 / 白天 / 毛玻璃，重启后沿用

所有选择立即生效并写回 `config.json`。

需要手动改文件的场景（如首次安装、批量配置）：所有配置都在 **`config.json`**（与 `quota_monitor.py` 同目录），不用改代码。不存在时用占位默认值。右键菜单的选择也写在这个文件里：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `renew_kimi` / `renew_codex` / `renew_glm` | 各续订日期，仅用于显示（右键菜单可改） | `"09-01"` |
| `kimi_plan_name` / `codex_plan_name` / `glm_plan_name` | 套餐显示名（右键菜单可改）；codex 留空 = 接口值 + 后缀 | `"Allegro"` |
| `codex_plan_suffix` | Codex 套餐名后缀，追加在接口返回值后 | `" 20x"` |
| `theme` | 主题：`dark` / `light` / `glass` | `"dark"` |
| `show_kimi` / `show_codex` / `show_glm` | 各卡片是否显示 | `true` / `false` |
| `show_codex_5h` | Codex 每 5 小时行；`null` 按套餐自动（Pro 隐藏，其余显示） | `null` / `true` / `false` |
| `show_codex_credits` | 是否显示「重置券」行（0 张时无论如何都不显示） | `true` / `false` |
| `show_radar` / `radar_window` | 显示雷达 / 预测窗口 | `true` / `24` 或 `48` |
| `tray_metric` | 托盘显示的额度字段，默认 Codex 每周 | `"cw_pct"` |
| `window_alpha` | 窗口透明度（40–100），用右下角 ＋/－ 调过之后自动记下 | `94` |
| `window_x` / `window_y` | 窗口左上角坐标，拖动后自动记下（**程序自己维护，不建议手改**） | `1586` / `812` |
| `glm_api_key` | 可选，GLM Coding Plan API Key。**明文存储，仅为兼容旧配置保留**；推荐用右键菜单「安全保存 API Key…」或环境变量 `AI_QUOTA_WIDGET_GLM_API_KEY` | `"sk-..."` |
| `glm_region` | `"cn"` → open.bigmodel.cn，`"intl"` → api.z.ai | `"cn"` |
| `show_deepseek` | 是否显示 DeepSeek 余额卡片 | `true` / `false` |
| `deepseek_api_key` | 可选，DeepSeek API Key。**明文仅为兼容**；推荐右键菜单或环境变量 `DEEPSEEK_API_KEY` | `"sk-..."` |
| `deepseek_low_balance` | 余额低于此金额显示橙色、低于四分之一显示红色；`0` = 关闭变色提醒 | `20.0` |
| `deepseek_token_metric` | 「今日」行右侧显示本机 Harness 当天的 token：`total` 含缓存读取、`fresh` 只算新输入+输出、`off` 不显示 | `"total"` / `"fresh"` / `"off"` |

注意：直接编辑 config.json 里 `renew_*` / 套餐名 / `glm_*` / `deepseek_*` 需要重启 widget 生效；右键菜单的所有操作（套餐、续订日期、显示开关）即时生效。

**API Key 的存放顺序**（先命中者生效）：

1. 环境变量：GLM 用 `AI_QUOTA_WIDGET_GLM_API_KEY`；DeepSeek 用 `AI_QUOTA_WIDGET_DEEPSEEK_API_KEY` 或官方的 `DEEPSEEK_API_KEY`（完全不落盘，最推荐）
2. 本机加密文件 `glm-key.dpapi` / `deepseek-key.dpapi`（Windows DPAPI 加密，只有当前 Windows 账户能解密）
3. `config.json` 的 `glm_api_key` / `deepseek_api_key`（旧版明文，仅兼容）

Windows 上程序还会直接读 `HKCU\Environment`，所以新设的环境变量不需要重启资源管理器或电脑。右键菜单 `GLM Coding Plan 设置` / `DeepSeek 设置` → 「安全保存 API Key…」会弹出口令输入框（输入内容不回显），加密保存到第 2 项并**清空 config.json 里的明文**；「清除已保存的 Key」删除全部副本。系统加密不可用时程序会明确报错并且**不会退回明文写入**。

### 关于 GLM 卡片

GLM 额度接口（`monitor/usage/quota/limit`）是智谱官方 Claude Code 插件使用的内部接口，需要**有效的 GLM Coding Plan Key** 才能调通；套餐过期或 Key 无效时该卡片刷新失败（状态行会提示 `glm`）。接口返回每 5 小时与每周两条 `TOKENS_LIMIT` 记录，widget 按 `reset_time` 升序取前两条展示，另有一条每月 MCP `TIME_LIMIT` 目前不显示。

## FAQ

**能像 npm 一样 `npm install` 就装好吗？**
这是 Windows Python 应用，不通过 npm 安装。`install.ps1` 负责检查 Python/tkinter、安装托盘依赖、复制文件、生成启动器和可选开机自启。

**需要提供 token 吗？**
不需要。Kimi / Codex 凭证来自本机已登录的 CLI；GLM 是唯一的例外，需要你自己在 config.json 里填 API Key。

**雷达是什么？**
对「Codex 额度什么时候发生全球重置」的两个第三方公共信号，仅供参考，不代表官方信息；赠送/补偿重置卡、个人 5 小时/每周额度必须以 Codex 官方状态为准。

## 支持范围与局限

- 支持 Kimi Code、Codex、DeepSeek 余额，可选 GLM Coding Plan；暂无 Claude 等方案
- 仅支持 Windows（依赖本机 CLI 凭证与 tkinter）
- Codex 额度是本机 Codex 保存的快照，不含采集时间，可能滞后于真实值；只有「窗口已重置」这种情况能被自动识别并标灰
- Codex 的重置券需要较新的 codex 运行时（旧版 `bin\codex.exe` 没有该字段）
- DeepSeek 的「今日消耗」是本地估算，起点是当天第一次读到余额的时刻；官方没有用量接口，所以它不能替代官网账单
- 套餐名与续订日期无法从接口自动读取，需要手动配置（见上文「配置项」）

欢迎 issue / PR 扩展更多服务商。

## 隐私与安全说明

- 本仓库不包含任何本地凭证或账号信息
- 程序运行时读取本机凭证（`~/.kimi-code`、`~/.codex`），只用于对应官方服务认证，不发送给第三方雷达，不打印或记录到日志
- Kimi 侧仅访问官方域名 `api.kimi.com` 与 `auth.kimi.com`
- Codex 侧通过本机 `codex app-server` 获取额度，由该客户端与官方服务通信
- 雷达、GLM 与 DeepSeek 请求分别发往两个第三方公开域名与智谱 / DeepSeek 官方域名；GLM / DeepSeek 的 Key 保存在本机，只用于对应官方认证
- GLM / DeepSeek 的 Key 可用右键菜单「安全保存 API Key…」以 Windows DPAPI 加密写入本机 `glm-key.dpapi` / `deepseek-key.dpapi`（仅当前账户可解密）并清空 config.json 中的明文，也可用环境变量完全不落盘；明文 `glm_api_key` / `deepseek_api_key` 字段仅为兼容旧配置保留
- Kimi 凭证过期时，程序可能用 refresh_token 自动续期并**更新本地凭证文件**
- 这是个人自用工具：不建议直接运行未经检查的第三方修改版，改完自己看一遍代码再用

## 诊断与测试

- `debug.txt`：最近结果、每个来源的成功时间、查询耗时、错误类别和重试间隔。
- `last-good.json`：本机最近成功数据缓存；旧值会明确标识，不能作为实时额度。
- 不要上传个人 `config.json`、凭据、缓存、`glm-key.dpapi`、`deepseek-key.dpapi`、`deepseek-spend.json` 或诊断文件。仓库中的 config.json 仅为占位模板。
- 单次查询硬上限：Kimi 65 秒、Codex 50 秒、其他来源 25 秒；Windows Job Object 回收整个查询树，包括主程序意外退出的情况。
- 离线回归测试：`python -m unittest discover -s tests -v`，需要 Windows、tkinter 和托盘依赖，不访问真实账号或网络。
- v1.1.0 本机验证：25 项测试通过；独立调度器连续 90 轮查询句柄数稳定；真实四源查询成功（包含社区明确无活跃投票）。单机空闲 30 秒样本约 69 MiB 工作集、0.016 秒 CPU 时间，不代表所有电脑或查询峰值。
- 休眠逻辑通过模拟时钟测试；长期运行、实际设备睡眠唤醒与托盘视觉仍需用户验证。

## 免责声明

本项目为个人学习/自用工具，与 Moonshot AI、OpenAI、智谱无任何隶属或官方关系。接口与凭证读取方式依赖第三方客户端的本地行为，可能随其版本更新而失效。雷达数据为第三方预测，仅供参考。请遵守相关服务条款，使用风险自负。

## License

MIT © IanCJ86
