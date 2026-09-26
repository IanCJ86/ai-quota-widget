"""Five static vector skins. No timers, network, raster assets or animation loop."""
import math
import tkinter as tk
from widget_style import THEMES, FONT_FAMILY


class ThemePainter:
    def __init__(self, app):
        self.app = app
        self.scale = float(app.root.tk.call("tk", "scaling")) / (96 / 72)
        self.canvas = tk.Canvas(app.content, width=236 * self.scale, height=50 * self.scale,
                                highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.snapshot = ("", None, True)
        self._draw_key = None
        self.canvas.bind("<Configure>", lambda event: self.draw())

    def apply(self, palette):
        a = self.app
        a._paint_backgrounds(palette)
        for card in a._cards:
            card.configure(relief=palette["RELIEF"], bd=palette["BORDER_WIDTH"],
                           highlightthickness=0)
        for label in a._name_labels:
            label.configure(fg=palette["FG_DIM"])
        for value, note in a.rows.values():
            value.configure(fg=palette["FG_TEXT"])
            note.configure(fg=palette["FG_DIM"])
        for name, label in a.section_titles.items():
            label.configure(fg=palette["BRANDS"][name])
        for name, label in a.section_renews.items():
            label.configure(fg=palette["BRANDS"][name])
        for label in [a.status, a.close_btn, *a._alpha_btns]:
            label.configure(fg=palette["FG_DIM"])
        self.canvas.configure(bg=palette["BG"])
        if a.theme == "glass":
            self.canvas.grid_remove()
        else:
            self.canvas.grid()
        self._menu(a.menu, palette)
        self.draw()

    def _menu(self, menu, palette):
        menu.configure(bg=palette["BG_CARD"], fg=palette["FG_TEXT"],
                       activebackground=palette["BG"], activeforeground=palette["ACCENT"],
                       disabledforeground=palette["FG_DIM"], selectcolor=palette["ACCENT"])
        for child in menu.winfo_children():
            if isinstance(child, tk.Menu):
                self._menu(child, palette)

    def update(self):
        a = self.app
        source, value, stale = "", None, True
        for name, prefix, title in (("codex", "cw", "Codex"), ("kimi", "kw", "Kimi"), ("glm", "gw", "GLM")):
            if getattr(a, "show_" + name).get():
                source = title + " 周余量"
                # The gauge describes this week, not an expired 5-hour window.
                legacy_expired = (name == "codex" and
                                  not any(a.data.get(k + "_reset") for k in ("c5", "cw")) and
                                  a.data.get("c_window_expired", False))
                stale = a._transport_stale(name) or a._window_expired(prefix) or legacy_expired
                value = a.data.get(prefix + "_pct")
                break
        self.snapshot = source, value, stale
        self.draw()

    def draw(self):
        a, c, s = self.app, self.canvas, self.scale
        theme = a.theme
        palette = THEMES.get(theme, THEMES["dark"])
        width = max(c.winfo_width(), int(float(c.cget("width"))))
        key = theme, width, self.snapshot
        if key == self._draw_key:
            return
        self._draw_key = key
        c.delete("all")
        if theme == "glass":
            return
        p = palette
        def coords(values):
            return [v * s for v in values]
        def line(*values, **kwargs):
            return c.create_line(*coords(values), **kwargs)
        def oval(*values, **kwargs):
            return c.create_oval(*coords(values), **kwargs)
        def rect(*values, **kwargs):
            return c.create_rectangle(*coords(values), **kwargs)
        def text(x, y, value, color, size=8, **kwargs):
            return c.create_text(x*s, y*s, text=value, fill=color,
                                 font=(FONT_FAMILY, size), anchor="w", **kwargs)
        w = width / s
        source, value, stale = self.snapshot
        known = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100
        shown = "--" if stale or not known else f"{value}%"
        caption = (source + " " + shown) if source else "账户用量 / 本机监控"
        if source and stale:
            caption += " · 待更新"
        accent = p["FG_DIM"] if stale else p["ACCENT"]
        if theme in ("dark", "light"):
            oval(3, 7, 27, 31, fill=p["ACCENT"], outline="")
            if theme == "dark":
                oval(11, 3, 31, 26, fill=p["BG"], outline="")
            else:
                oval(8, 13, 11, 16, fill=p["BG"], outline="")
                oval(17, 21, 22, 26, fill=p["BG"], outline="")
            text(37, 13, p["LABEL"], p["FG_TEXT"], 10)
            text(37, 34, caption, p["FG_DIM"])
            line(w-20, 10, w-4, 10, fill=p["BORDER"])
        elif theme == "steam":
            rect(0, 1, w-1, 49, outline=p["BORDER"], width=1)
            for x in (5, w-6):
                for y in (6, 44):
                    oval(x-1, y-1, x+1, y+1, fill=p["ACCENT"], outline="")
            oval(11, 8, 45, 42, fill=p["BG_CARD"], outline=p["ACCENT"], width=2)
            for angle in (140, 205, 270, 335, 400):
                rad = math.radians(angle)
                line(28+12*math.cos(rad), 25+12*math.sin(rad),
                     28+15*math.cos(rad), 25+15*math.sin(rad), fill=p["FG_DIM"])
            if known and not stale:
                angle = math.radians(140+260*value/100)
                line(28, 25, 28+12*math.cos(angle), 25+12*math.sin(angle), fill=accent, width=2)
            else:
                text(20, 25, "--", p["FG_DIM"])
            oval(26, 23, 30, 27, fill=p["ACCENT"], outline="")
            text(56, 15, "蒸汽算力机", p["FG_TEXT"], 10)
            text(56, 35, caption, p["FG_DIM"])
        elif theme == "fuel":
            rect(3, 8, 23, 36, fill=p["ACCENT"], outline="")
            rect(6, 12, 20, 21, fill=p["BG"], outline="")
            line(23, 14, 29, 18, 29, 31, 34, 31, 34, 12, fill=p["ACCENT"], width=2)
            text(43, 12, "TOKEN 加油站", p["FG_TEXT"], 10)
            text(43, 31, caption, p["FG_DIM"])
            for i in range(20):
                x = 43 + i*(w-44)/20
                lit = known and not stale and i < math.ceil(value/5)
                rect(x, 44, x+(w-44)/20-2, 47,
                     fill=p["ACCENT"] if lit else p["BORDER"], outline="")
        else:  # paper ledger
            line(4, 4, 4, 46, fill=p["BORDER"], width=2)
            text(14, 13, "电子墨水账本", p["FG_TEXT"], 10)
            text(14, 34, caption, p["FG_DIM"])
            line(14, 47, w, 47, fill=p["BORDER"])
