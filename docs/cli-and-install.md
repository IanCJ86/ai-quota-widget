# 安装、查询与诊断

本文供需要排错、手动配置或源码开发的用户查阅；支持哪些账户及日常安装见 [首页](../README.md)。

## 普通Windows用户

下载最新正式Release的 `ai-quota-widget-v<版本>-windows-x64.zip`，完整解压后双击 `install.cmd`，也可直接运行 `quota-widget.exe`。成品包自带 Python/Tk/依赖，**不需要自行安装环境**，面向 Windows 10/11 x64。首次使用中文快速设置，已有登录自动识别；无凭据可以跳过，之后右键设置。

安装器校验全部文件，默认安装到 `%USERPROFILE%\.ai-quota-widget-app\v<版本>`，创建桌面/开始菜单快捷方式；不默认开机自启。v1.4.5起个人数据在 `%USERPROFILE%\.ai-quota-widget`，程序与数据都避开AppData重定向。首次启动复制旧目录数据并保留原文件，已有共享数据不覆盖；回退旧版前退出新版，旧版仍读取旧目录，不会自动同步新设置。已知源码旧版可使用 `setup.ps1 -ExistingDataDir "旧目录"` 迁移；同名数据冲突会拒绝，不跨机器迁移DPAPI。成品版命令直接使用 `quota-cli.exe --doctor/--version/--once/--json`。

`quick-install.ps1` 从官方 GitHub 正式 Release 下载成品包并核对SHA256，然后调用同一个离线安装器。网络不通会报错，不切到不明镜像。

### 源码开发者（可选）

`windows-source.zip` + `install.ps1` 是备用源码安装路线，仍需Python 3.10+含Tk；建立 `.venv-<版本>` 和start.bat。不要推荐给只想使用软件的人。新装默认毛玻璃，升级保留主题。

升级前用右键菜单“退出”。运行中会拒绝覆盖，不强杀；安装失败回滚程序文件，保留个人配置、密钥和统计。依赖下载失败可能留下该版本环境，可重新运行安装器修复。桌面启动器不依赖临时uvx环境。`-SkipDependencies` 只用于已自行管理并验证的持久Python环境。

## 无界面命令

成品版在程序目录使用自带的 CLI：

```powershell
.\quota-cli.exe --version
.\quota-cli.exe --doctor
.\quota-cli.exe --once
.\quota-cli.exe --json --fresh
```

- `--doctor`：离线诊断，仅列版本、依赖可发现状态、文件齐全程度、凭据是否存在、缓存状态和安全错误类别。存在凭据不等于联网认证成功；存在模块不等于GUI已验证。也可右键“复制脱敏诊断”。
- `--json` / `--once`：默认读缓存，不刷新、不写缓存、不启动GUI或定时任务；`--fresh` 才直接查询一次每个已配置来源。会读取本机已登录凭据，只有对应官方请求使用它们。DeepSeek鲜查会更新本地金额估算基线，token鲜查会更新统计缓存。
- `--data-dir "数据目录"`：读取指定目录的配置、加密Key和缓存。成品默认 `%USERPROFILE%\.ai-quota-widget`；首次GUI迁移前，诊断只读兼容旧目录并提示，不自动写入。不要把程序目录或Agent旧私有副本的缓存当作当前数据。
- 返回码：0=本命令检查/查询成功，1=待配置或部分失败/缓存待核验/旧数据，2=查询无可用数据或安装错误。doctor无凭据且环境健康为1，必要运行模块或Tk/Pillow/pystray缺失为2；仅可选zstd统计组件缺失为1，不影响独立余额查询。`--help/--version` 为0。以诊断文字及JSON来源状态为准。
- 输出不包含Key、Cookie、凭据路径、账户ID或日志原文；`--json/--once` **包含个人额度/余额**，不应当作公开脱敏报告。公开反馈用doctor。

v1.4.2rc2 起，底部区分刷新中、连接失败、需重新认证、缓存待核验与数据过旧，不再统一显示“待更新”。数据目录内 `query-history.json` 保留最近200条查询事件；成功不会抹掉之前的失败，doctor列出末12条。只记录来源、时间、错误类别、耗时和重试安排，不含额度、余额、密钥或日志原文。主循环间隔记录只能证明存在时间间隔，不能单独认定断网、休眠或卡死；历史失败也不代表当前仍失败。记录保存失败会提示，但不阻断查询。

## wheel / uvx

开发者可使用 Release 中的 wheel。把下例文件名替换成实际下载的版本：

```powershell
uvx --from .\ai_quota_widget-<版本>-py3-none-any.whl quota_monitor --help
uvx --from .\ai_quota_widget-<版本>-py3-none-any.whl quota_monitor --install --dest "C:\Apps\quota-widget" --no-autostart
```

`uvx`只是安装/查询入口。GUI安装需要带Tk的持久Python；精简或无Tk的uv托管Python会在预检失败，此时改用python.org的Windows安装版运行源码安装器。没有声明任意uv环境都能启动GUI。

源码安装的诊断使用 `start.bat` 绑定的解释器，把上述命令替换为 `python quota_monitor.py ...`，并传入 `--data-dir "源码安装目录"`。不要混用其他全局 Python。

## 手动配置与读数

日常使用右键菜单即可。手动修改时，成品配置位于 `%USERPROFILE%\.ai-quota-widget\config.json`，源码安装版在其安装目录；修改后重启。常用字段：

| 字段 | 用途 |
| --- | --- |
| `show_kimi` / `show_codex` / `show_glm` / `show_deepseek` | 账户卡片开关 |
| `theme` | `glass` / `dark` / `light` / `steam` / `fuel` / `ink` |
| `*_plan_name` / `renew_*` | 套餐显示名、续订日期；仅是显示设置，不用于购买或认证 |
| `show_codex_5h` / `show_codex_credits` | 五小时额度行、重置券行；没有券时隐藏 |
| `show_radar` / `radar_window` | 第三方雷达开关及24/48小时窗口 |
| `network` | 右键“网络设置”：账户、雷达、更新分别跟随系统、直连或指定HTTP代理；地址不含账号密码 |
| `glm_region` | 国内 `cn` 或国际 `intl`，须与 Key 所属服务一致 |
| `deepseek_token_metric` | `total` 含缓存读取、`fresh` 新输入与输出、`off` 关闭 |
| `deepseek_low_balance` | 余额告警阈值，`0` 关闭 |
| `tray_metric` / `window_alpha` / `lock_position` | 托盘指标、透明度、拖动锁定，建议用菜单调整 |

v1.4.3起：`tray_metric=ds_spend`显示今日估算金额，四舍五入至整数，不带币种或百分号；超过999显示`999+`，悬停查看精确金额和币种。只显示DeepSeek时自动选用此项；缺少Key/当日基线、跨天未刷新或估算失败显示`--`，不伪造0。

余额差额不是完整账单：当天已经采样、关闭后再打开且没有充值等干扰时，可补算这段余额下降；首次采样之前的消费、跨天关闭期间的每日分摊、充值与消费相互抵消不能可靠还原。本机token扫描与此独立，已有Harness日志可补读当天记录。公开API Key的余额接口不等同网页登录后的平台账单接口。

v1.4.3毛玻璃保留半透明底色及原配色，停用可能导致Tk文字洗白的Windows原生acrylic叠加，因而不再提供该原生背景模糊效果。托盘诊断区分`starting`和`ready`，注册中不代表故障。若用旧版Windows PowerShell读取UTF-8诊断文件，使用`Get-Content -Encoding UTF8`；日常推荐右键复制脱敏诊断。

默认 Harness 日志目录为 `~/.dsh/sessions`。v1.4.2rc1 起可在右键设置中选择日志目录（`harness_sessions_dir`），本机统计不再要求 DeepSeek API Key。token 只覆盖本机日志，缓存读取也计入 `total`，因此大 token 数不等于高支出。DeepSeek 金额估算只覆盖首次余额采样之后观察到的变化；未运行时段、充值与消费抵消等无法完整还原。计费时段标签仅供参考，以服务商账单为准。

菜单保存的 GLM / DeepSeek Key 使用 Windows DPAPI，只能由本机对应 Windows 用户解密；不要跨电脑复制加密文件。环境变量支持 `AI_QUOTA_WIDGET_GLM_API_KEY`、`AI_QUOTA_WIDGET_DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEY`。正式 v1.4.1 环境变量优先；v1.4.2rc1 改为菜单保存的 Key 优先。旧配置中的明文 Key 仅作兼容，不建议新增；清除软件保存的 Key 不会删除环境变量。

## 开发与截图

在 Windows 源码环境安装 `requirements.txt` 后运行：

```powershell
python -m unittest discover -s tests -v
python tests/render_readme.py
```

GUI 测试与截图使用隔离桌面及演示数据，不读取个人账户。截图加 `--dpi-percent 400 --output "输出目录"` 可导出新媒体用高清 PNG。模块边界见 [结构说明](architecture.md)；历史测试数量和性能采样保留在相应版本记录，不代表当前所有电脑的性能。

## 显示语义与限制

| 场景 | 展示/动作 |
| --- | --- |
| 首次查询失败 | `--` + 可理解的错误提示，不伪造0 |
| 已有数据后失败/断网 | 保留旧值、灰色及“旧”；到期日期仍保留 |
| 瞬时错误 | 每轮最多三次；HTTP429尊重Retry-After（最多24小时），手动刷新不绕过等待 |
| 认证失效 | 提示重新认证，不密集重试 |
| 重置窗口已结束 | 该窗口标旧；不连带作废尚有效的周窗口或券 |
| 多张券部分到期 | 有完整期限列表时扣除过期张数；只有最早期限时提示待更新，不武断清零全部 |
| 几毛 / 不足一分 / 大额 | 两位金额 / `<¥0.01` / 万、亿缩写 |
| 跨天 | 昨日金额与token不冒充今日 |
| 更换Key或币种 | 重建金额估算起点；同一Key未运行期间、充值和消费同时发生等无法完整还原，非账单 |
| 小屏幕/高缩放 | 控制窗口在工作区内，必要时滚动内容，底部按钮保持可用 |
| 配置格式损坏 | 默认值兜底并提示；再次保存设置前备份原配置为 `.invalid-*.bak` |

雷达为第三方预测；Codex来源是本机CLI快照，并非官方实时承诺。token仅为本机Harness当日记录。正式发布不等于用户已验收，更不等于所有显示器/网络/杀毒软件组合已验证。

## 网络与更新

默认跟随进程环境/Windows静态代理；从桌面启动不会自动读取其他Agent的专用环境文件。需要时在本工具右键“网络设置”填写代理软件的HTTP入口（`http://主机:端口`，访问目标HTTPS服务仍验证证书），不修改系统代理，也不扫描端口或读取其他软件密钥。PAC、SOCKS及代理服务器自身TLS入口目前不直接支持，会明确提示；不要为排错关闭TLS证书验证。无效显式网络配置会阻止查询，必须在菜单确认修正，不悄悄改为直连。账户认证只允许同源HTTPS跳转。

雷达和更新可显式允许“系统连接失败后尝试直连”，默认关闭；指定代理及账户请求不会自动绕过代理。重新查询会重新读取系统连接设置，不长期锁定旧代理。

雷达分别保存24/48小时有效值和查询时间，缺失窗口保留旧值并标旧。预测时间来自网页“Data last updated”；超过3小时或时间异常标旧，未提供时明确提示，不以本机查询时间冒充信源时间。

检查更新成功后每天检查；失败依次等待1/5/15分钟，继续失败则等24小时，遵守限流等待。更新菜单显示下载量，可点击取消；元数据查询总预算约23秒，安装包下载约10分钟。网络任务由独立子进程承载，超时/取消终止自己的任务；失败保留原程序和数据。首次下载安装脚本仍使用PowerShell自身网络设置，装好后的查询及菜单更新才使用插件网络设置。

卸载：右键退出，移除本工具程序目录和快捷方式；成品版个人数据在 `%USERPROFILE%\.ai-quota-widget`，单独保留或删除。升级前的 `%LOCALAPPDATA%\AIQuotaWidget` 原文件也保留，源码版数据在其安装目录。不要删除CLI本身的凭据目录。

AI-Agent: Codex
