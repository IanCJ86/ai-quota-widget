"""Modal input only: no credentials, disk writes, scheduler or tray ownership."""
import calendar
from datetime import date
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from widget_style import BG, FG_TEXT, FG_DIM, FONT_TEXT, FONT_HINT


class WidgetDialogs:
    def __init__(self, root, topmost, config):
        self.root, self.topmost, self.config = root, topmost, config

    def _renew_picker(self, kind):
        """Modal month/day picker (no keyboard input, no year involved).

        Returns "MM-DD" or None on cancel. Day overflow (e.g. Feb 31) is
        clamped to the month's last day with a notice, instead of rejecting.
        """
        cur = self.config.get(f"renew_{kind}", "")
        try:
            cm, cd = int(cur[:2]), int(cur[3:])
        except Exception:
            t = date.today()
            cm, cd = t.month, t.day

        top = self.topmost.get()
        self.root.attributes("-topmost", True)
        self.root.lift()
        win = tk.Toplevel(self.root)
        win.title("续订日期")
        win.attributes("-topmost", True)
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg=BG)
        win.geometry(f"+{self.root.winfo_x() + 40}+{self.root.winfo_y() + 40}")

        mv = tk.StringVar(value=str(cm))
        dv = tk.StringVar(value=str(cd))
        lbl = dict(bg=BG, fg=FG_TEXT, font=FONT_TEXT)
        tk.Label(win, text="月", **lbl).grid(row=0, column=0, padx=(12, 4), pady=10)
        mc = ttk.Combobox(win, textvariable=mv, state="readonly", width=3,
                          values=[str(i) for i in range(1, 13)])
        mc.grid(row=0, column=1, padx=(0, 8))
        tk.Label(win, text="日", **lbl).grid(row=0, column=2, padx=(4, 4))
        dc = ttk.Combobox(win, textvariable=dv, state="readonly", width=3,
                          values=[str(i) for i in range(1, 32)])
        dc.grid(row=0, column=3, padx=(0, 12))

        result = {}

        def ok():
            m, d = int(mv.get()), int(dv.get())
            # no year is involved; use a non-leap reference year so Feb caps at 28
            last = calendar.monthrange(2023, m)[1]
            if d > last:
                messagebox.showinfo("已调整",
                                    f"{m}月没有{d}日，已设为{m}月{last}日。",
                                    parent=win)
                d = last
            result["v"] = f"{m:02d}-{d:02d}"
            win.destroy()

        tk.Button(win, text="确定", command=ok, width=6).grid(
            row=1, column=1, columnspan=2, pady=(0, 10))
        tk.Button(win, text="取消", command=win.destroy, width=6).grid(
            row=1, column=3, pady=(0, 10))
        # expose for smoke tests
        self._picker = (win, mv, dv, ok)

        # A borderless, topmost parent makes Tk lazy about focus, which left the
        # dialog unclickable until something else was clicked; raise it, force
        # focus and only then take the grab.
        win.update_idletasks()
        win.lift()
        win.focus_force()
        mc.focus_set()
        win.grab_set()
        self.root.wait_window(win)
        self.root.attributes("-topmost", top)
        return result.get("v")

    def _notice(self, title, text):
        """messagebox that stays in front of the borderless topmost window."""
        top = self.topmost.get()
        self.root.attributes("-topmost", True)
        self.root.lift()
        try:
            messagebox.showinfo(title, text, parent=self.root)
        finally:
            self.root.attributes("-topmost", top)

    def _ask_secret(self, title, prompt):
        """Masked single-line input (tkinter has no masked simpledialog)."""
        top = self.topmost.get()
        self.root.attributes("-topmost", True)
        self.root.lift()
        win = tk.Toplevel(self.root)
        win.title(title)
        win.attributes("-topmost", True)
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg=BG)
        win.geometry(f"+{self.root.winfo_x() + 40}+{self.root.winfo_y() + 40}")
        tk.Label(win, text=prompt, bg=BG, fg=FG_TEXT, anchor="w",
                 font=FONT_TEXT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 2))
        tk.Label(win, text="只保存在本机（Windows 加密），不会写入 config.json。",
                 bg=BG, fg=FG_DIM, anchor="w",
                 font=FONT_HINT).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6))
        value = tk.StringVar()
        entry = tk.Entry(win, textvariable=value, show="•", width=44)
        entry.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8))
        entry.focus_set()
        result = {}

        def ok(event=None):
            result["v"] = value.get().strip()
            win.destroy()

        tk.Button(win, text="保存", command=ok, width=6).grid(row=3, column=0, pady=(0, 10))
        tk.Button(win, text="取消", command=win.destroy, width=6).grid(
            row=3, column=1, pady=(0, 10))
        win.bind("<Return>", ok)
        # expose for smoke tests
        self._secret_prompt = (win, value, ok)
        # Same focus problem as the date picker: without an explicit lift and
        # focus_force the entry is not clickable until the window is refocused.
        win.update_idletasks()
        win.lift()
        win.focus_force()
        entry.focus_set()
        win.grab_set()
        self.root.wait_window(win)
        self.root.attributes("-topmost", top)
        return result.get("v")

    def _ask(self, title, prompt, initial=""):
        """simpledialog that stays in front of our borderless topmost window."""
        top = self.topmost.get()
        self.root.attributes("-topmost", True)
        self.root.lift()
        try:
            return simpledialog.askstring(title, prompt, initialvalue=initial,
                                          parent=self.root)
        finally:
            self.root.attributes("-topmost", top)
