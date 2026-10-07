"""Local-only network preferences. No discovery, test requests or system changes."""
import tkinter as tk
from tkinter import ttk, messagebox
from quota_network import settings, GROUPS
from widget_viewport import Viewport, work_area, clamp_rect


def show_network(app, config, save):
    invalid = False
    try:
        current = settings(config)
    except ValueError:
        current, invalid = settings({}), True
    win = tk.Toplevel(app.root)
    win.title('额度监控 · 网络设置')
    win.transient(app.root)
    win.attributes('-topmost', True)
    win.resizable(True, True)
    viewport = Viewport(win)
    body = viewport.body
    labels = {'accounts': '账户接口', 'radar': 'Tibo雷达', 'updates': '检查及下载更新'}
    modes = {'跟随系统/环境': 'system', '直接连接': 'direct', '指定HTTP代理': 'proxy'}
    rows = {}
    tk.Label(body, text=('原网络配置无效，查询已暂停；请确认以下设置后保存。\n' if invalid else '')+
             '只影响本工具，不修改电脑网络。默认跟随系统；请使用http://代理入口（可访问HTTPS服务）。',
             wraplength=470, justify='left').grid(row=0, column=0, columnspan=3, padx=12, pady=12)
    for i, group in enumerate(GROUPS, 1):
        item = current[group]
        mode = tk.StringVar(value=next(k for k,v in modes.items() if v == item['mode']))
        url = tk.StringVar(value=item['proxy'])
        fallback = tk.BooleanVar(value=item['direct_fallback'])
        tk.Label(body, text=labels[group]).grid(row=i*2, column=0, padx=12, sticky='w')
        ttk.Combobox(body, textvariable=mode, values=list(modes), state='readonly', width=18).grid(row=i*2, column=1)
        tk.Entry(body, textvariable=url, width=30).grid(row=i*2, column=2, padx=12, pady=4)
        if group != 'accounts':
            tk.Checkbutton(body, text='系统连接失败时允许尝试直连（公司强制代理请勿启用）',
                           variable=fallback).grid(row=i*2+1, column=0, columnspan=3, sticky='w', padx=12)
        rows[group] = (mode, url, fallback)
    changed = []
    def accept():
        raw = {n: dict(mode=modes[m.get()], proxy=u.get(), direct_fallback=f.get())
               for n,(m,u,f) in rows.items()}
        try:
            normalized = settings({'network': raw})
        except ValueError:
            messagebox.showerror('地址无效', '代理格式：http://主机:端口；不支持带密码的地址。', parent=win)
            return
        candidate = dict(config, network=normalized)
        if not save(candidate):
            messagebox.showerror('保存失败', '原设置保持不变。', parent=win)
            return
        config.update(candidate)
        changed.append(True)
        win.destroy()
    tk.Label(body, text='代理地址留在本机，不进入脱敏诊断；账户请求不自动绕过代理。',
             wraplength=470).grid(row=8, column=0, columnspan=3, pady=10)
    buttons = tk.Frame(win)
    buttons.grid(row=2,column=0,columnspan=2,pady=(0,12))
    tk.Button(buttons, text='保存', command=accept).pack(side='left',padx=12)
    tk.Button(buttons, text='取消', command=win.destroy).pack(side='left',padx=12)
    win.update_idletasks()
    area = work_area(app.root)
    viewport.fit((area[0],area[1],area[2],area[3]-buttons.winfo_reqheight()-12))
    win.update_idletasks()
    w,h,x,y=clamp_rect(app.root.winfo_x()+20,app.root.winfo_y()+20,
                      win.winfo_reqwidth(),win.winfo_reqheight(),area)
    win.geometry(f'{w}x{h}{x:+d}{y:+d}')
    win.grab_set()
    app.root.wait_window(win)
    return bool(changed)
