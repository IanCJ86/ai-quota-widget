# AGENTS.md — 给 AI Agent 的安装配置指令书

本指南面向安装任务：用户让你安装 **ai-quota-widget** 时，按以下步骤执行。安装和个性化无需修改源码，使用 `config.json`；用户明确要求开发、修复或发布时，可在相应范围内修改源码并执行测试。

## 前提

- 用户系统是 Windows，且已登录过 Kimi Code CLI 和/或 Codex CLI。
- **不需要向用户索要 CLI token 或密码**：读取本机已登录 CLI 的凭证，只用于对应官方服务认证。雷达访问 `codexreset.org` 这个第三方公开网站，不带任何凭据。

## 步骤

### 1. 获取仓库

```bash
git clone https://github.com/IanCJ86/ai-quota-widget.git
cd ai-quota-widget
```

（没有 git 就从 GitHub 下载 ZIP 解压。）

### 2. 运行安装脚本

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

脚本会：检查 Python 3.10+/tkinter → 安装 Pillow 和 pystray → 复制两个 Python 模块到 `%USERPROFILE%\Desktop\quota-widget\` → 生成使用同一解释器的 `start.bat` → 询问是否开机自启（默认 N）。无交互安装使用 `-NoAutostartPrompt`；支持 `-PythonPath` 和 `-Destination` 指定解释器与安装目录。依赖已安装时可加 `-SkipDependencies`，脚本仍会验证导入。升级前从托盘菜单退出旧版，已有 config.json 不覆盖。

### 3. 根据用户口述写 config.json

安装目录下的 `config.json` 是唯一需要改的文件。向用户确认以下信息（不知道就保留占位值；**这些值用户日后都能在右键菜单里自己改，不用追求完美**）：

```json
{
  "renew_kimi": "09-01",
  "renew_codex": "09-15",
  "kimi_plan_name": "Allegro",
  "codex_plan_suffix": " 20x",
  "show_kimi": true,
  "show_codex": true,
  "show_glm": false,
  "glm_api_key": "",
  "glm_region": "cn",
  "show_deepseek": true,
  "deepseek_api_key": "",
  "deepseek_low_balance": 20.0,
  "deepseek_token_metric": "total",
  "show_codex_credits": true
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `renew_kimi` / `renew_codex` / `renew_glm` | 续订日期，仅用于界面显示，格式 `MM-DD`（装好后用户可在右键菜单改） |
| `kimi_plan_name` | Kimi 套餐显示名（右键菜单可改） |
| `codex_plan_name` | Codex 套餐显示名覆盖，如 `"Pro 20x"`（右键菜单可改）；留空则用接口值 + `codex_plan_suffix` |
| `glm_plan_name` | GLM 套餐显示名，如 `"Pro"`（右键菜单可改） |
| `codex_plan_suffix` | Codex 套餐名后缀，例如 `" 20x"` |
| `theme` | 主题：`dark` / `light` / `glass`（毛玻璃），右键菜单可切换 |
| `show_kimi` / `show_codex` / `show_glm` | 各卡片是否显示（右键菜单也可切换） |
| `glm_api_key` | 可选。GLM Coding Plan API Key；**明文存储，仅兼容旧配置**。优先用环境变量 `AI_QUOTA_WIDGET_GLM_API_KEY`，或让用户点右键菜单「GLM Coding Plan 设置 → 安全保存 API Key…」（DPAPI 加密，且会清空这里的明文） |
| `glm_region` | `"cn"` 用 open.bigmodel.cn，`"intl"` 用 api.z.ai |
| `show_deepseek` | 是否显示 DeepSeek 卡片。DeepSeek 是按量付费，卡片显示**余额金额**而不是百分比 |
| `deepseek_api_key` | 可选。DeepSeek API Key，**明文仅兼容**。优先用环境变量 `DEEPSEEK_API_KEY`（用户机器上通常已有）或 `AI_QUOTA_WIDGET_DEEPSEEK_API_KEY`，或让用户点右键菜单「DeepSeek 设置 → 安全保存 API Key…」 |
| `deepseek_low_balance` | 余额低于此金额显示橙色、低于四分之一显示红色；`0` = 关闭变色提醒 |
| `deepseek_token_metric` | DeepSeek「今日」行右侧显示本机 Harness 当天 token：`"total"`（含缓存读取，默认）/ `"fresh"`（只算新输入+输出）/ `"off"`。余额行右侧固定显示计费时段：**梁文峰 时段**（北京时间工作日 9:00–12:00、14:00–18:00）或**梁文谷 时段**（其余时段）；需要 zstd（Python 3.14+ 或 `zstandard`），没有时该位置留空 |
| `show_codex_credits` | 是否显示 Codex「重置券」行（可用券为 0 时该行本就不显示）。重置券需要较新的 codex 运行时：程序优先用 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` 里最新的那个 |

注意：GLM 卡片只有在**能取到 Key**（环境变量 / `glm-key.dpapi` / `glm_api_key` 任一来源）且 `show_glm` 为 true 时才出现；DeepSeek 卡片同理（`DEEPSEEK_API_KEY`、`deepseek-key.dpapi`、`deepseek_api_key` 任一 + `show_deepseek`）。需要**有效的 GLM Coding Plan** 才能取到 GLM 数据。不要主动把用户的 Key 明文写进 config.json——让用户自己在右键菜单里保存。

### 4. 启动并验证

```bash
# 双击安装目录里的 start.bat，或：
cd "%USERPROFILE%\Desktop\quota-widget" && start.bat
```

等待约 20 秒后检查同目录 `debug.txt`：

- `"errors": {}` 且 `"data"` 里有 `k5_pct` / `c5_pct` / `ds_balance` 等数值 → 安装成功，告诉用户完成。
- `errors` 里出现 `kimi` → 用户没登录 Kimi Code CLI，让其先运行一次 Kimi Code 登录。
- `errors` 里出现 `codex` → 检查 CLI 安装与登录。默认托盘也查询 Codex；仅隐藏卡片不会关闭托盘需要的查询。
- `errors` 里出现 `deepseek` → 用户机器上没有可用的 DeepSeek Key（环境变量 `DEEPSEEK_API_KEY`、`deepseek-key.dpapi`、`deepseek_api_key` 都没有）；`HTTP401` 表示 Key 无效。`ds_spend` 是本地估算的今日消耗（`deepseek-spend.json`），官方没有用量接口，不要拿它当账单。
- 底部“待更新:N 项”表示有 N 个来源尚未取得新数据（对应卡片里的备注显示“旧 HH:MM”，从未成功过则显示“等待更新”）。查看对应来源的错误，不把所有 `--` 当成同一种故障。

### 5. 完成

向用户汇报：安装目录、如何改配置（右键菜单设置套餐/续订日期/主题）。GLM Key 让用户自己在右键菜单 `GLM Coding Plan 设置 → 安全保存 API Key…` 里输入（加密保存到本机，不写 config.json 明文）；文件里的配置项重启 widget 才生效。底部 ✕ 仅隐藏到托盘，右键菜单“退出”才会结束程序；重复运行启动器会唤回已有窗口。

## 排错速查

- 双击 start.bat 没反应 → 用 `python quota_monitor.py` 前台跑，看终端报错。
- 窗口不出现但 debug.txt 正常 → 窗口在屏幕右下角，可能被其他窗口挡住（默认置顶）。
- 修改 config.json 不生效 → 重启 widget（文件配置只在启动时读取；右键菜单里的套餐、续订日期、显示开关都是即时生效并写回 config.json）。
