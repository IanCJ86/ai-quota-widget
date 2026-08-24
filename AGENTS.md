# AGENTS.md — 给 AI Agent 的安装配置指令书

你是一个 AI agent，用户让你帮他安装 **ai-quota-widget**（一个 Windows 桌面悬浮窗，显示 Kimi Code / Codex / GLM 的额度）。按以下步骤执行，全程约 2 分钟。**不要修改 `quota_monitor.py` 的任何代码**——所有个性化都通过 `config.json` 完成。

## 前提

- 用户系统是 Windows，且已登录过 Kimi Code CLI 和/或 Codex CLI。
- **不需要向用户索要任何 token 或密码**：本工具只读取本机已登录 CLI 的凭证（`~/.kimi-code`、`~/.codex`），网络请求仅发往官方域名。

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

脚本会：检查 Python 3 是否在 PATH（不在则提示用户去 python.org 安装并退出）→ 复制文件到 `%USERPROFILE%\Desktop\quota-widget\` → 生成 `start.bat` → 询问是否开机自启（替用户回答，默认 N 即可，或先问用户）。

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
  "glm_region": "cn"
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `renew_kimi` / `renew_codex` | 续订日期，仅用于界面显示，格式 `MM-DD`（装好后用户可在右键菜单改） |
| `kimi_plan_name` | Kimi 套餐显示名（右键菜单可改） |
| `codex_plan_name` | Codex 套餐显示名覆盖，如 `"Pro 20x"`（右键菜单可改）；留空则用接口值 + `codex_plan_suffix` |
| `codex_plan_suffix` | Codex 套餐名后缀，例如 `" 20x"` |
| `show_kimi` / `show_codex` / `show_glm` | 各卡片是否显示（右键菜单也可切换） |
| `glm_api_key` | 可选。填入有效的 GLM Coding Plan API Key 后 GLM 卡片自动出现 |
| `glm_region` | `"cn"` 用 open.bigmodel.cn，`"intl"` 用 api.z.ai |

注意：GLM 卡片只有在 `glm_api_key` 非空且 `show_glm` 为 true 时才出现。需要**有效的 GLM Coding Plan** 才能取到数据。

### 4. 启动并验证

```bash
# 双击安装目录里的 start.bat，或：
cd "%USERPROFILE%\Desktop\quota-widget" && start.bat
```

等待约 20 秒后检查同目录 `debug.txt`：

- `"errors": {}` 且 `"data"` 里有 `k5_pct` / `c5_pct` 等数值 → 安装成功，告诉用户完成。
- `errors` 里出现 `kimi` → 用户没登录 Kimi Code CLI，让其先运行一次 Kimi Code 登录。
- `errors` 里出现 `codex` → 未安装/未登录 Codex CLI，可让用户在 config.json 把 `show_codex` 改为 false。
- 雷达行显示 `雷达 --` 属正常降级（forecast 接口偶发不可达），不影响主功能。

### 5. 完成

向用户汇报：安装目录、如何改配置（**右键 → Kimi 设置 / Codex 设置 可直接改套餐名和续订日期**；GLM 等进阶项编辑 config.json 后重启生效）、如何退出（右键菜单 → 退出，或底部 ✕）。

## 排错速查

- 双击 start.bat 没反应 → 用 `python quota_monitor.py` 前台跑，看终端报错。
- 窗口不出现但 debug.txt 正常 → 窗口在屏幕右下角，可能被其他窗口挡住（默认置顶）。
- 修改 config.json 不生效 → 重启 widget（文件配置只在启动时读取；右键菜单里的套餐、续订日期、显示开关都是即时生效并写回 config.json）。
