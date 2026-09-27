# AI Quota Widget · AI 额度悬浮窗

**Windows AI 账户额度与余额悬浮监控工具。**

支持 Kimi Code、Codex 订阅额度、GLM Coding Plan 和 DeepSeek 官方 API 余额；额外支持本机 DeepSeek Harness token 统计。

是否适用取决于你使用的**账户与计费服务**，不只是客户端名称。暂不支持所有 AI 软件的自动识别或逐客户端消耗统计。

## 我能用吗？

| 我用什么软件 | 买了什么套餐 / 服务 | 能看到什么 | 怎么连接 |
| --- | --- | --- | --- |
| Kimi Code；或使用同一 Kimi Code 账户的兼容客户端 | Kimi Code 套餐 | 5 小时、每周剩余额度与重置时间 | 本机登录 Kimi Code CLI，工具读取其登录凭据 |
| Codex 桌面端 / CLI | 可使用 Codex 的订阅账户 | 5 小时、每周额度；接口提供时显示重置券及到期日 | 本机已有可识别的 Codex 登录及 app-server 运行时 |
| Claude Code、OpenCode 等，实际接入 GLM Coding Plan | GLM Coding Plan | 套餐 5 小时、每周剩余额度 | 在设置中保存对应套餐 Key，选择国内 / 国际区域 |
| DeepSeek Harness、OpenCode 等，实际接入 DeepSeek 官方 API | DeepSeek 官方 API 按量账户 | 账户余额、今日支出估算 | 在设置中保存 DeepSeek 官方 API Key |
| 本机 DeepSeek Harness | 同上；本机统计是附加项 | 当天本机 Harness 的 token 用量 | 读取本机 Harness 会话日志 |

同一账户在多个客户端使用时，这里看的是**账户级额度或余额**，不是每个客户端分别用了多少。Claude 原生订阅、Kimi Work 积分、OpenAI API 余额及第三方中转账户目前没有专用适配。

![额度悬浮窗，毛玻璃主题，演示数据](docs/images/hero.png)

## 安装与开始使用

**Windows 10/11 x64，无需 Python、Node.js 或 Git。**

1. 打开[最新正式版下载页](https://github.com/IanCJ86/ai-quota-widget/releases/latest)，下载名称以 **`windows-x64.zip`** 结尾的成品包。
2. 完整解压，双击 **`install.cmd`**；也可直接打开包内的 `quota-widget.exe`。
3. 在中文“快速设置”中选择需要的账户。已有登录会尝试识别，Key 在本机填写，也可以稍后设置。

只需连接你用的服务，不必安装所有 CLI。升级前右键“退出”旧版，再运行安装器，个人配置保留。

安装失败？先看[排错说明](docs/cli-and-install.md)。普通用户只选 `windows-x64.zip`；`windows-source.zip` 和 `.whl` 供开发者使用，`quick-install.ps1` 是可选快装脚本。

想让 AI 帮你安装？复制这段：

> 请用中文帮我安装 https://github.com/IanCJ86/ai-quota-widget 最新正式 Release 的 windows-x64 成品包，校验同版 SHA256SUMS.txt 后执行包内 setup.ps1。不要装 Python 或修改源码。保留已有配置，打开软件即可；缺少 Key 由我在快速设置里填写，可以跳过。

<details>
<summary>一条 PowerShell 命令安装</summary>

```powershell
$installer = Join-Path $env:TEMP 'ai-quota-quick-install.ps1'; Invoke-WebRequest -UseBasicParsing 'https://github.com/IanCJ86/ai-quota-widget/releases/latest/download/quick-install.ps1' -OutFile $installer; powershell -NoProfile -ExecutionPolicy Bypass -File $installer
```

脚本下载正式成品包、核对 SHA256 后安装。下载速度取决于 GitHub 网络，不在电脑上重新搭建开发环境。

</details>

## 日常怎么用

- 悬浮显示，托盘也能看剩余额度；双击刷新，右键调整账户、主题、套餐显示名和续订日期。
- 自动定时查询；网络失败保留并标记旧数据，不把历史数字当作新结果。
- 点击 **✕** 隐藏到托盘，点击托盘图标恢复；真正退出请用右键菜单。
- 可选 Codex 重置雷达来自 [codexreset.org](https://codexreset.org)，是第三方预测，不是官方承诺，也不是你的个人重置通知。

**读数说明：** DeepSeek“今日估算”来自余额变化，不是官方账单，也不需要额外网页登录授权。当天已有采样时，关闭后再打开可补算余额下降；首次采样前、跨天及充值抵消的消费不能完整还原。`tok` 只统计本机 Harness。Codex 数据可能是本机快照，存在滞后。

## 六套主题

右键 → **主题** 切换。新安装默认毛玻璃，升级保留原选择。点击图片可保存原图。

| 毛玻璃 | 月之暗面 | 月之亮面 |
| --- | --- | --- |
| [<img src="docs/images/hero.png" width="240" alt="毛玻璃">](docs/images/hero.png) | [<img src="docs/images/dark.png" width="240" alt="月之暗面">](docs/images/dark.png) | [<img src="docs/images/light.png" width="240" alt="月之亮面">](docs/images/light.png) |
| **蒸汽算力机** | **Token 加油站** | **电子墨水账本** |
| [<img src="docs/images/steam.png" width="240" alt="蒸汽算力机">](docs/images/steam.png) | [<img src="docs/images/fuel.png" width="240" alt="Token 加油站">](docs/images/fuel.png) | [<img src="docs/images/ink.png" width="240" alt="电子墨水账本">](docs/images/ink.png) |

截图为真实界面配合演示数据，并非个人账单；毛玻璃的桌面透色与模糊效果取决于系统支持，图中不含桌面合成效果。

## 数据与反馈

工具在本机运行，凭据仅用于对应服务认证；右键保存的 API Key 使用 Windows 账户加密。Kimi 登录续期可能更新本机凭据。雷达不接收账户凭据。

遇到问题，用右键 **“复制脱敏诊断”**，附操作步骤和截图[提交 Issue](https://github.com/IanCJ86/ai-quota-widget/issues)。不要上传 Key、个人配置、原始日志或缓存；截图中不想公开的余额也请遮盖。

[技术说明与排错](docs/cli-and-install.md) · [开发结构](docs/architecture.md) · [更新记录](CHANGELOG.md)

MIT · **临界思潮**（[@IanCJ86](https://github.com/IanCJ86)）。独立开源项目，与上述服务商无官方隶属关系。
