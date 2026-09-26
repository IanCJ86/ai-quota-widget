# v1.3 安装、查询与诊断

对外作者：临界思潮。本文是实际技术合同，不是宣传稿。

## 普通Windows用户

下载最新正式Release的 `ai-quota-widget-v<版本>-windows-source.zip`，完整解压，运行 `install.ps1`。需要Python 3.10+（含Tk）；缺少时安装器提供安装提示，不暗中安装系统软件。安装器在目标目录建立 `.venv-<版本>`，安装依赖后才替换程序文件，生成 `start.bat`。这是Python应用，不是免环境EXE。v1.3.2新装默认毛玻璃，升级保留原主题；只需配置你实际使用的来源。

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
- 返回码：0=本命令检查/查询成功，1=部分失败或缓存待核验/旧数据，2=无可用账户数据、环境/安装错误。`--help/--version` 为0。具体以JSON各来源状态或诊断文字为准。
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

卸载：右键退出，删除本工具创建的开机启动快捷方式（若启用），再移除自己的安装目录；其中加密Key、配置和历史也会被删除，需保留时先备份。不要删除CLI本身的凭据目录。

AI-Agent: Codex
