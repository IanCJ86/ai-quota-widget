---
name: 🐞 Bug 报告
about: 显示不对、装不上、崩溃——请按下面的模板填写，能大幅加快定位
title: "[Bug] "
labels: bug
---

<!--
请先做两件事，它们能让问题基本自证：

1. 提供安装目录下 debug.txt 的内容（里面没有你的 Key；如果担心，可只贴 errors / status_text / data 三个字段）
2. 说明你用的是哪个版本（右键菜单里可查看版本）

感谢！
-->

## 1. 现象

<!-- 哪里不对？例如：Kimi 一行一直是 --；窗口闪屏；装完打不开 -->

## 2. 期望的行为

<!-- 你原本以为会发生什么 -->

## 3. 复现步骤

1.
2.
3.

## 4. 环境信息

- 程序版本（右键菜单可查看）：
- Windows 版本：
- Python 版本（`python --version`）：
- 显示器缩放（100% / 125% / 150%）与屏幕数量：
- 已登录的 AI CLI（勾选）：Kimi Code ☐　Codex ☐　GLM ☐　DeepSeek ☐

## 5. 脱敏诊断输出（推荐用这个）

请在程序目录运行下面这条命令，把输出**整段贴进来**（它本身已脱敏，不含密钥/路径/账号/余额）：

```powershell
python quota_monitor.py --doctor --data-dir "<安装目录>"
```

或：右键菜单 →「复制脱敏诊断」。

> ⚠️ **请不要贴原始 `debug.txt` 或含余额的 JSON** —— 按仓库隐私指引，公开渠道只放脱敏信息。

## 5b. 如果你更愿意贴 debug.txt 的摘要字段

<!--
命令：Get-Content "$env:USERPROFILE\Desktop\quota-widget\debug.txt" -Raw
只需贴这几个字段，不要整份贴：
-->

```
# 只贴这四行即可，不要整份粘贴
errors:
status_text:
```

## 6. 截图（如果有）

<!-- 直接拖进来即可。若涉及隐私，请遮掉账号名/余额 -->
