"""Small Chinese first-run screen; source selection is optional and repeatable."""
import tkinter as tk
from tkinter import ttk


def show_setup(app, config, save, configured):
    existing = getattr(app, '_setup_window', None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return
    win = app._setup_window = tk.Toplevel(app.root)
    win.title('额度监控 · 快速设置')
    win.attributes('-topmost', True)
    win.resizable(False, False)
    box = ttk.Frame(win, padding=18)
    box.grid()
    ttk.Label(box, text='选择要显示的账户', font=('Microsoft YaHei UI', 12, 'bold')).grid(
        row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(box, text='已登录的账户会自动识别；没有 Key 也可先打开软件。\n套餐名和续订日期以后再设置，不影响安装。').grid(
        row=1, column=0, columnspan=3, sticky='w', pady=(6,12))
    flags, checks, status = configured(), {}, {}
    for row, (name, label) in enumerate((('kimi','Kimi'), ('codex','Codex'),
                                        ('glm','GLM'), ('deepseek','DeepSeek')), 2):
        checks[name] = tk.BooleanVar(value=config.get('show_'+name, False))
        ttk.Checkbutton(box, text=label, variable=checks[name]).grid(row=row,column=0,sticky='w',pady=5)
        status[name] = ttk.Label(box, text='已发现凭据 · 待查询' if flags[name] else '未配置')
        status[name].grid(row=row,column=1,sticky='w',padx=12)

        def enter_key(provider=name):
            app.settings._save_key_secure(provider)
            ready = configured()[provider]
            status[provider].configure(text='已发现凭据 · 待查询' if ready else '未配置')
            if ready:
                checks[provider].set(True)
            win.lift()

        if name in ('glm','deepseek'):
            ttk.Button(box, text='填写 Key', command=enter_key).grid(row=row,column=2)
    ttk.Label(box, text='Kimi / Codex：先登录对应客户端，再点“开始使用”。\n其他来源未配置会明确提示，不会一直等待。').grid(
        row=6,column=0,columnspan=3,sticky='w',pady=(10,12))

    def finish(use_selection=True):
        for name, var in checks.items():
            getattr(app,'show_'+name).set(var.get() if use_selection else config.get('show_'+name,False))
        app._apply_visibility()
        app.refresh_async()
        app._fit()
        app._write_debug()
        win.destroy()

    ttk.Button(box,text='开始使用',command=finish).grid(row=7,column=1,sticky='e')
    ttk.Button(box,text='稍后设置',command=lambda: finish(False)).grid(row=7,column=2,padx=(8,0))
    win.protocol('WM_DELETE_WINDOW',lambda: finish(False))
    win.update_idletasks()
    win.geometry(f'+{max(0,(win.winfo_screenwidth()-win.winfo_reqwidth())//2)}'
                 f'+{max(0,(win.winfo_screenheight()-win.winfo_reqheight())//2)}')
    win.lift()
    # No modal wait or polling loop. Main window remains responsive.
