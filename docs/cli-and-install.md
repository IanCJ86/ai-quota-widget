# 安装、查询与诊断

对外作者：临界思潮。本文是实际技术合同，不是宣传稿。

## 普通Windows用户

下载最新正式Release的 `ai-quota-widget-v<版本>-windows-x64.zip`，完整解压后双击 `install.cmd`，也可直接运行 `quota-widget.exe`。成品包自带 Python/Tk/依赖，**不需要自行安装环境**，面向 Windows 10/11 x64。首次使用中文快速设置，已有登录自动识别；无凭据可以跳过，之后右键设置。

安装器校验全部文件，安装到 `%LOCALAPPDATA%\Programs\AIQuotaWidget\v<版本>`，创建桌面/开始菜单快捷方式；不默认开机自启。个人数据在 `%LOCALAPPDATA%\AIQuotaWidget`，升级保留，旧程序版本可回退。已知源码旧版可使用 `setup.ps1 -ExistingDataDir "旧目录"` 迁移；同名数据冲突会拒绝，不跨机器迁移DPAPI。成品版命令直接使用 `quota-cli.exe --doctor/--version/--once/--json`。

`quick-install.ps1` 从官方 GitHub 正式 Release 下载成品包并核对SHA256，然后调用同一个离线安装器。网络不通会报错，不切到不明镜像。

### 源码开发者（可选）

`windows-source.zip` + `install.ps1` 是备用源码安装路线，仍需Python 3.10+含Tk；建立 `.venv-<版本>` 和start.bat。不要推荐给只想使用软件的人。新装默认毛玻璃，升级保留主题。

升级前用右键菜单“退出”。运行中会拒绝覆盖，不强杀；安装失败回滚程序文件，保留个人配置、密钥和统计。依赖下载失败可能留下该版本环境，可重新运行安装器修复。桌面启动器不依赖临时uvx环境。`-SkipDependencies` 只用于已自行管理并验证的持久Python环境。

## 无界面命令

以下示例假设在完整源码环境中运行。诊断已安装版本时，使用安装目录start.bat绑定的Python绝对路径、安装目录中的quota_monitor.py，并加`--data-dir "实际安装目录"`；不要用另一个全局Python诊断后误报缺依赖。

```powershell
python quota_monitor.py --help
python quota_monitor.py --version
python quota_monitor.py --doctor
python quota_monitor.py --once
python quota_monitor.py --json
python quota_monitor.py --once --fresh
python quota_monitor.py --json --fresh
python quota_monitor.py --install --dest "C:\Apps\quota-widget" --no-autostart
```

- `--doctor`：离线诊断，仅列版本、依赖可发现状态、文件齐全程度、凭据是否存在、缓存状态和安全错误类别。存在凭据不等于联网认证成功；存在模块不等于GUI已验证。也可右键“复制脱敏诊断”。
- `--json` / `--once`：默认读缓存，不刷新、不写缓存、不启动GUI或定时任务；`--fresh` 才直接查询一次每个已配置来源。会读取本机已登录凭据，只有对应官方请求使用它们。DeepSeek鲜查会更新本地金额估算基线，token鲜查会更新统计缓存。
- `--data-dir "实际安装目录"`：读取指定目录的配置、加密Key和缓存。CLI与桌面共同使用同一目录，不能把工具临时目录的空缓存当桌面丢数据。
- 返回码：0=本命令检查/查询成功，1=待配置或部分失败/缓存待核验/旧数据，2=查询无可用数据或安装错误。doctor无凭据且环境健康为1，必要运行模块或Tk/Pillow/pystray缺失为2；仅可选zstd统计组件缺失为1，不影响独立余额查询。`--help/--version` 为0。以诊断文字及JSON来源状态为准。
- 输出不包含Key、Cookie、凭据路径、账户ID或日志原文；`--json/--once` **包含个人额度/余额**，不应当作公开脱敏报告。公开反馈用doctor。

## wheel / uvx

Release附有wheel，不要求上传PyPI。已有uv的用户可以下载wheel后运行：

```powershell
uvx --from .\ai_quota_widget-1.3.2-py3-none-any.whl quota_monitor --help
uvx --from .\ai_quota_widget-1.3.2-py3-none-any.whl quota_monitor --install --dest "C:\Apps\quota-widget" --no-autostart
```

`uvx`只是安装/查询入口。GUI安装需要带Tk的持久Python；精简或无Tk的uv托管Python会在预检失败，此时改用python.org的Windows安装版运行源码安装器。没有声明任意uv环境都能启动GUI。

## 显示语义与限制

| 场景 | 展示/动作 |
| --- | --- |
| 首次查询失败 | `--` + 可理解的错误提示，不伪造0 |
| 已有数据后失败/断网 | 保留旧值、灰色及“旧”；到期日期仍保留 |
| 瞬时错误 | 最多三次；限流响应的等待要求最多采用300秒，随后仍按调度退避 |
| 认证失效 | 提示重新认证，不密集重试 |
| 重置窗口已结束 | 该窗口标旧；不连带作废尚有效的周窗口或券 |
| 多张券部分到期 | 有完整期限列表时扣除过期张数；只有最早期限时提示待更新，不武断清零全部 |
| 几毛 / 不足一分 / 大额 | 两位金额 / `<¥0.01` / 万、亿缩写 |
| 跨天 | 昨日金额与token不冒充今日 |
| 更换Key或币种 | 重建金额估算起点；同一Key未运行期间、充值和消费同时发生等无法完整还原，非账单 |
| 小屏幕/高缩放 | 控制窗口在工作区内，必要时滚动内容，底部按钮保持可用 |
| 配置格式损坏 | 默认值兜底并提示；再次保存设置前备份原配置为 `.invalid-*.bak` |

雷达为第三方预测；Codex来源是本机CLI快照，并非官方实时承诺。token仅为本机Harness当日记录。正式发布不等于用户已验收，更不等于所有显示器/网络/杀毒软件组合已验证。

卸载：右键退出，移除本工具程序目录和快捷方式；成品版个人数据在 `%LOCALAPPDATA%\AIQuotaWidget`，单独保留或删除，源码版数据在其安装目录。不要删除CLI本身的凭据目录。

AI-Agent: Codex
