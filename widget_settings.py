"""Provider settings coordinator. Dependencies are explicit; App owns execution."""
import calendar
from datetime import date
import tkinter as tk
from widget_style import PLAN_PRESETS, PLAN_CFG_KEY
from widget_dialogs import WidgetDialogs


class SettingsController:
    def __init__(self, app, config, save_config, key_tools):
        self.app, self.config, self.save_config = app, config, save_config
        self.KEY_TOOLS = key_tools
        self.dialogs = WidgetDialogs(app.root, app.topmost, config)

    def _current_plan(self, kind):
        if kind == "kimi":
            return self.config.get("kimi_plan_name", "")
        if kind == "glm":
            return self.config.get("glm_plan_name", "")
        return (self.config.get("codex_plan_name")
                or (self.app.data.get("c_plan") or "Pro")
                + self.config.get("codex_plan_suffix", ""))

    def _build_provider_menu(self, kind):
        presets = PLAN_PRESETS[kind]
        m = tk.Menu(self.app.menu, tearoff=0)
        self._provider_menus = getattr(self, "_provider_menus", {})
        self._provider_menus[kind] = m
        cur = self._current_plan(kind)
        var = tk.StringVar(value=cur)
        setattr(self, f"_plan_var_{kind}", var)
        for name in presets:
            m.add_radiobutton(label=name, variable=var, value=name,
                              command=lambda n=name: self._set_plan(kind, n))
        # custom input just sets the display name; nothing is remembered in the menu
        m.add_command(label="自定义…",
                      command=lambda: self._ask_custom_plan(kind))
        sub = tk.Menu(m, tearoff=0)
        sub.add_command(label="设为下个月今天",
                        command=lambda: self._set_renew(kind, "next_month"))
        sub.add_command(label="设为本月最后一天",
                        command=lambda: self._set_renew(kind, "last_day"))
        sub.add_command(label="选择日期…",
                        command=lambda: self._ask_renew(kind))
        m.add_cascade(label="续订日期", menu=sub)
        if kind == "codex":
            m.add_separator()
            self.show_codex_credits = tk.BooleanVar(
                value=bool(self.config.get("show_codex_credits", True)))
            m.add_checkbutton(label="显示重置券", variable=self.show_codex_credits,
                              command=self._toggle_codex_credits)
        if kind == "glm":
            m.add_separator()
            # config.json is plaintext; store new keys encrypted instead.
            m.add_command(label="安全保存 API Key…",
                          command=lambda: self._save_key_secure("glm"))
            m.add_command(label="清除已保存的 Key",
                          command=lambda: self._clear_key("glm"))
        return m

    def _toggle_codex_credits(self):
        self.config["show_codex_credits"] = self.show_codex_credits.get()
        self.save_config(self.config)
        self.app._render()
        self.app._fit()

    def _build_deepseek_menu(self):
        """DeepSeek has no plans or renewal dates: only the API key."""
        m = tk.Menu(self.app.menu, tearoff=0)
        m.add_command(label="安全保存 API Key…",
                      command=lambda: self._save_key_secure("deepseek"))
        m.add_command(label="清除已保存的 Key",
                      command=lambda: self._clear_key("deepseek"))
        m.add_command(label="选择 Harness 日志目录…", command=self._choose_logs)
        m.add_command(label="恢复默认日志目录", command=lambda: self._set_logs(''))
        return m

    def _choose_logs(self):
        from tkinter import filedialog
        import os
        path = filedialog.askdirectory(parent=self.app.root, title='选择 Harness sessions 目录', mustexist=True)
        if path and os.path.isdir(path) and os.access(path, os.R_OK):
            self._set_logs(path)

    def _set_logs(self, path):
        self.config['harness_sessions_dir'] = path
        self.save_config(self.config)
        self.app.refresh_async()

    def _set_plan(self, kind, name):
        getattr(self, f"_plan_var_{kind}").set(name)
        self.config[PLAN_CFG_KEY[kind]] = name
        self.save_config(self.config)
        if kind == "codex" and self.config.get("show_codex_5h") is None:
            self.app._sync_codex_5h_menu()
            self.app._apply_visibility(persist=False)
        self.app._render()

    def _ask_custom_plan(self, kind):
        s = self.dialogs._ask("自定义套餐", "套餐显示名：",
                      initial=self._current_plan(kind))
        if not (s and s.strip()):
            return  # cancel or empty: no change at all
        name = s.strip()
        getattr(self, f"_plan_var_{kind}").set(name)
        self.config[PLAN_CFG_KEY[kind]] = name
        self.save_config(self.config)
        self.app._render()

    def _set_renew(self, kind, mode):
        today = date.today()
        if mode == "next_month":
            y, m = (today.year + 1, 1) if today.month == 12 \
                else (today.year, today.month + 1)
            d = min(today.day, calendar.monthrange(y, m)[1])
        else:  # last_day
            y, m = today.year, today.month
            d = calendar.monthrange(y, m)[1]
        self.config[f"renew_{kind}"] = f"{m:02d}-{d:02d}"
        self.save_config(self.config)
        self.app._render()

    def _ask_renew(self, kind):
        v = self.dialogs._renew_picker(kind)
        if v:
            self.config[f"renew_{kind}"] = v
            self.save_config(self.config)
            self.app._render()

    def _save_key_secure(self, kind):
        """Store a provider key with DPAPI and remove any plaintext copy."""
        title, save, _ = self.KEY_TOOLS[kind]
        key = self.dialogs._ask_secret(title, title + "：")
        if not key:
            return
        saved = save(key)
        self.app._sync_credentials()
        if saved:
            self.dialogs._notice("已保存", "Key 已用当前 Windows 账户加密保存在本机，\n"
                                   "config.json 里的明文已清除。\n本机保存值优先于环境变量，连接尚待验证。")
        else:
            self.dialogs._notice("保存未完成", "加密保存或旧明文清理未完成，请检查文件写入权限。\n"
                                      "可能已生成加密副本；不能确认旧明文已清除。")
        self.app._apply_visibility()
        self.app.refresh_async()

    def _clear_key(self, kind):
        _, _, clear = self.KEY_TOOLS[kind]
        cleared = clear()
        self.app._sync_credentials()
        if cleared:
            self.dialogs._notice("已清除", "本机保存的 Key 已删除。\n如仍有环境变量，将使用环境变量；不会删除系统设置。")
        else:
            self.dialogs._notice("清除未完成", "部分本机文件未能清除，请检查文件写入权限。")
        self.app._apply_visibility()
        self.app.refresh_async()

    def _set_glm_key_secure(self):
        self._save_key_secure("glm")

    def _clear_glm_key(self):
        self._clear_key("glm")
