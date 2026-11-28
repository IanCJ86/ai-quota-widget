"""Five static vector skins + Bento glass card styling.

No timers, network, raster assets, or animation loops.
"""
import math
import tkinter as tk
from widget_style import THEMES, FONT_FAMILY


class ThemePainter:
    def __init__(self, app):
        self.app = app
        self.scale = float(app.root.tk.call("tk", "scaling")) / (96 / 72)
        self.canvas = tk.Canvas(app.content, width=236 * self.scale, height=52 * self.scale,
                                highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="ew", padx=11, pady=(8, 0))
        self.snapshot = ("", None, True)
        self._draw_key = None
        self.canvas.bind("<Configure>", lambda event: self.draw())

    def apply(self, palette):
        a = self.app
        a._paint_backgrounds(palette)
        for card in a._cards:
            if palette["RELIEF"] == "ridge":
                card.configure(relief=palette["RELIEF"], bd=palette["BORDER_WIDTH"],
                               highlightthickness=0)
            else:
                card.configure(relief="flat", bd=0,
                               highlightbackground=palette["BORDER"],
                               highlightcolor=palette["BORDER"],
                               highlightthickness=1)
        for label in a._name_labels:
            label.configure(fg=palette["FG_DIM"])
        for value, note in a.rows.values():
            value.configure(fg=palette["FG_TEXT"])
            note.configure(fg=palette["FG_DIM"])
        for name, label in a.section_titles.items():
            label.configure(fg=palette["BRANDS"][name])
        for name, label in a.section_renews.items():
            label.configure(fg=palette["BRANDS"][name])
        for label in [a.status, a.close_btn, a.egress_label, *a._alpha_btns]:
            label.configure(fg=palette["FG_DIM"])
        if hasattr(a, "_paint_card_accents"):
            a._paint_card_accents(palette)
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
        for name, prefix, title in (
            ("codex", "cw", "Codex"),
            ("antigravity", "aw", "Antigravity"),
            ("kimi", "kw", "Kimi"),
            ("glm", "gw", "GLM"),
        ):
            shown = getattr(a, "show_" + name, None)
            if shown is not None and shown.get():
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

        def text(x, y, value, color, size=8, weight="normal", **kwargs):
            font_spec = (FONT_FAMILY, size, weight) if weight != "normal" else (FONT_FAMILY, size)
            return c.create_text(x * s, y * s, text=value, fill=color,
                                 font=font_spec, anchor="w", **kwargs)

        w = width / s
        source, value, stale = self.snapshot
        known = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and 0 <= value <= 100)
        shown = "--" if stale or not known else f"{value}%"
        caption = (source + " " + shown) if source else "账户用量 / 本机监控"
        if source and stale:
            caption += " · 待更新"
        accent = p["FG_DIM"] if stale else p["ACCENT"]
        ratio = (max(0.0, min(100.0, float(value))) / 100.0) if (known and not stale) else 0.0

        if theme in ("dark", "light"):
            # Crisp lunar emblem + editorial masthead + hairline progress gauge
            oval(4, 8, 28, 32, fill=p["ACCENT"], outline="")
            if theme == "dark":
                oval(12, 4, 32, 26, fill=p["BG"], outline="")
                oval(26, 7, 29, 10, fill=p["ACCENT"], outline="")
            else:
                oval(2, 6, 30, 34, fill="", outline=p["BORDER"], width=1)
                oval(10, 14, 13, 17, fill=p["BG"], outline="")
                oval(18, 22, 22, 26, fill=p["BG"], outline="")
            text(38, 13, p["LABEL"], p["FG_TEXT"], 10, "bold")
            text(38, 31, caption, p["FG_DIM"], 8)
            rect(38, 42, max(44, w - 4), 45, fill=p["TRACK"], outline="")
            if ratio > 0:
                rect(38, 42, 38 + max(2.0, (max(44, w - 4) - 38) * ratio), 45,
                     fill=accent, outline="")
        elif theme == "steam":
            rect(1, 2, w - 2, 50, fill=p["BG_CARD"], outline=p["BORDER"], width=1)
            for x in (6, w - 7):
                for y in (7, 45):
                    oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill=p["ACCENT"], outline="")
            oval(12, 9, 44, 41, fill=p["BG"], outline=p["ACCENT"], width=2)
            for angle in (140, 205, 270, 335, 400):
                rad = math.radians(angle)
                line(28 + 11 * math.cos(rad), 25 + 11 * math.sin(rad),
                     28 + 14 * math.cos(rad), 25 + 14 * math.sin(rad), fill=p["FG_DIM"])
            if known and not stale:
                angle = math.radians(140 + 260 * value / 100)
                line(28, 25, 28 + 11 * math.cos(angle), 25 + 11 * math.sin(angle),
                     fill=accent, width=2)
            else:
                text(22, 25, "--", p["FG_DIM"], 8)
            oval(26, 23, 30, 27, fill=p["ACCENT"], outline="")
            text(54, 17, "蒸汽算力机", p["FG_TEXT"], 10, "bold")
            text(54, 35, caption, p["FG_DIM"], 8)
        elif theme == "fuel":
            rect(4, 8, 24, 37, fill=p["ACCENT"], outline="")
            rect(7, 12, 21, 21, fill=p["BG"], outline="")
            line(24, 15, 29, 18, 29, 31, 34, 31, 34, 12, fill=p["ACCENT"], width=2)
            text(44, 13, "TOKEN 加油站", p["FG_TEXT"], 10, "bold")
            text(44, 30, caption, p["FG_DIM"], 8)
            segments = 16
            span = max(48.0, w - 48.0)
            seg_w = span / segments
            for i in range(segments):
                x = 44 + i * seg_w
                lit = known and not stale and i < math.ceil(value / (100 / segments))
                rect(x, 42, x + max(1.5, seg_w - 2.2), 46,
                     fill=p["ACCENT"] if lit else p["TRACK"], outline="")
        else:  # paper ledger (ink)
            rect(3, 6, 6, 46, fill=p["ACCENT"], outline="")
            text(14, 14, "电子墨水账本", p["FG_TEXT"], 10, "bold")
            text(14, 32, caption, p["FG_DIM"], 8)
            rect(14, 44, max(24, w - 2), 46, fill=p["TRACK"], outline="")
            if ratio > 0:
                rect(14, 44, 14 + max(2.0, (max(24, w - 2) - 14) * ratio), 46,
                     fill=accent, outline="")
