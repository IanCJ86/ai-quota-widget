# -*- coding: utf-8 -*-
# Quota Monitor: Kimi Code + Codex floating widget.
# Reads local credentials only; network calls go to official domains only.
# Never prints or logs any token.
import json
import os
import calendar
import subprocess
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime, date, timezone
import tkinter as tk
from tkinter import messagebox, simpledialog

# crisp rendering on high-DPI displays (declare per-monitor DPI awareness)
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

REFRESH_SECONDS = 900          # auto refresh every 15 minutes
KIMI_CRED = os.path.expanduser(r"~\.kimi-code\credentials\kimi-code.json")
KIMI_USAGE_URL = "https://api.kimi.com/coding/v1/usages"
KIMI_OAUTH_HOST = "https://auth.kimi.com"
KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"  # public OAuth client id of the CLI
CODEX_HOME = os.path.expanduser(r"~\.codex")
CODEX_EXE_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe"),
]
DEBUG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.txt")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")  # legacy

DEFAULT_CONFIG = {
    # ---- personal display options (edit config.json, not this file) ----
    "renew_kimi": "MM-DD",        # Kimi renewal date shown in the UI, e.g. "09-01"
    "renew_codex": "MM-DD",       # Codex renewal date shown in the UI
    "kimi_plan_name": "MyPlan",   # Kimi plan display name (API only returns a level)
    "codex_plan_name": "",        # Codex plan display override; empty = API planType + suffix
    "codex_plan_suffix": "",      # suffix appended to Codex planType, e.g. " 20x"
    # ---- visibility toggles (also in the right-click menu) ----
    "show_kimi": True,
    "show_codex": True,
    "show_glm": False,            # GLM card appears only when glm_api_key is set
    # ---- GLM Coding Plan (optional) ----
    "glm_api_key": "",            # z.ai / open.bigmodel.cn API key; empty = disabled
    "glm_region": "cn",           # "cn" -> open.bigmodel.cn, "intl" -> api.z.ai
}


def _load_config():
    cfg = dict(DEFAULT_CONFIG)
    for path in (SETTINGS_FILE, CONFIG_FILE):  # legacy settings.json first, config.json wins
        try:
            cfg.update(json.load(open(path, encoding="utf-8")))
        except Exception:
            pass
    return cfg


def _save_config(cfg):
    try:
        json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass


CFG = _load_config()

# silent subprocess: no console window flash
_NO_WINDOW = {}
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0  # SW_HIDE
    _NO_WINDOW = {"startupinfo": _si,
                  "creationflags": subprocess.CREATE_NO_WINDOW}

# colors
THEMES = {
    "dark": dict(BG="#1e1e2e", BG_CARD="#262638", BORDER="#3a3a4e",
                 FG_DIM="#7a7a90", FG_TEXT="#e8e8f4",
                 KIMI_SOFT="#8db4e8", CODEX_SOFT="#83d4ab"),
    "light": dict(BG="#f2f3f7", BG_CARD="#ffffff", BORDER="#d9dae4",
                  FG_DIM="#8a8a9a", FG_TEXT="#23233a",
                  KIMI_SOFT="#4a7fc9", CODEX_SOFT="#3a9e6e"),
}
BG = "#1e1e2e"
BG_CARD = "#262638"
FG_DIM = "#7a7a90"
FG_TEXT = "#e8e8f4"
KIMI_BLUE = "#5b9dff"
CODEX_GREEN = "#4ecf8a"
KIMI_BLUE_SOFT = "#8db4e8"
CODEX_GREEN_SOFT = "#83d4ab"
GLM_PURPLE = "#b48cff"
GLM_PURPLE_SOFT = "#c9b3f2"
KIMI_PLAN_PRESETS = ["Allegro", "基础版", "专业版"]
CODEX_PLAN_PRESETS = ["Free", "Plus", "Pro", "Pro 20x"]
CODEX_RADAR_URL = "https://codex-reset.com/api/forecast"
GLM_QUOTA_URLS = {
    "cn": "https://open.bigmodel.cn/api/monitor/usage/quota/limit",
    "intl": "https://api.z.ai/api/monitor/usage/quota/limit",
}


def _fmt_reset(iso_or_ts):
    """Format a reset time (ISO string or unix seconds) as MM-DD HH:MM local."""
    try:
        if isinstance(iso_or_ts, (int, float)):
            dt = datetime.fromtimestamp(iso_or_ts, tz=timezone.utc).astimezone()
        else:
            dt = datetime.fromisoformat(str(iso_or_ts).replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return "?"


def _countdown(iso_or_ts):
    try:
        if isinstance(iso_or_ts, (int, float)):
            dt = datetime.fromtimestamp(iso_or_ts, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(iso_or_ts).replace("Z", "+00:00"))
        secs = int((dt - datetime.now(timezone.utc)).total_seconds())
        if secs <= 0:
            return "即将重置"
        h, m = divmod(secs // 60, 60)
        return f"{h}h{m:02d}m后"
    except Exception:
        return ""


def _parse_mmdd(s):
    """Accept '08-31', '8-31', '8月31', '0831', '831', '8/31' -> 'MM-DD'; else None."""
    t = str(s).strip()
    for a, b in (("年", "-"), ("月", "-"), ("日", ""), ("/", "-"), (".", "-")):
        t = t.replace(a, b)
    t = t.strip("- ")
    if t.isdigit():
        if len(t) == 4:
            parts = [t[:2], t[2:]]
        elif len(t) == 3:
            parts = [t[0], t[1:]]
        else:
            return None
    else:
        parts = [p for p in t.split("-") if p]
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return None
    m, d = int(parts[0]), int(parts[1])
    if 1 <= m <= 12 and 1 <= d <= 31:
        return f"{m:02d}-{d:02d}"
    return None


# ---------------- Kimi ----------------

def fetch_kimi():
    cred = json.load(open(KIMI_CRED, encoding="utf-8"))
    if cred.get("expires_at", 0) <= time.time() + 60 and cred.get("refresh_token"):
        body = urllib.parse.urlencode({
            "client_id": KIMI_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": cred["refresh_token"],
        }).encode()
        for path in ("/api/oauth/token", "/v1/oauth/token"):
            try:
                req = urllib.request.Request(KIMI_OAUTH_HOST + path, data=body,
                                             headers={"Accept": "application/json"})
                r = json.load(urllib.request.urlopen(req, timeout=15))
                if r.get("access_token"):
                    cred["access_token"] = r["access_token"]
                    if r.get("refresh_token"):
                        cred["refresh_token"] = r["refresh_token"]
                    if r.get("expires_in"):
                        cred["expires_at"] = int(time.time()) + int(r["expires_in"])
                    json.dump(cred, open(KIMI_CRED, "w", encoding="utf-8"))
                    break
            except Exception:
                continue
    req = urllib.request.Request(KIMI_USAGE_URL,
                                 headers={"Authorization": "Bearer " + cred["access_token"]})
    d = json.load(urllib.request.urlopen(req, timeout=15))

    weekly = d.get("usage") or {}
    five_h = None
    for item in d.get("limits") or []:
        w = item.get("window") or {}
        try:
            dur = int(w.get("duration") or 0)
        except Exception:
            dur = 0
        if abs(dur - 300) <= 5:
            five_h = item.get("detail") or {}
    if five_h is None and d.get("limits"):
        five_h = (d["limits"][0] or {}).get("detail") or {}

    def pct_left(detail):
        try:
            if detail.get("used") is not None and detail.get("limit"):
                return 100 - int(detail["used"]) * 100 // int(detail["limit"])
            if detail.get("remaining") is not None and detail.get("limit"):
                return int(detail["remaining"]) * 100 // int(detail["limit"])
        except Exception:
            pass
        return None

    return {
        "k5_pct": pct_left(five_h), "k5_reset": five_h.get("resetTime"),
        "kw_pct": pct_left(weekly), "kw_reset": weekly.get("resetTime"),
        "k_plan": {"LEVEL_ADVANCED": "高级版", "LEVEL_BASIC": "基础版",
                   "LEVEL_PRO": "专业版"}.get(
                       ((d.get("user") or {}).get("membership") or {}).get("level"), ""),
    }


# ---------------- Codex ----------------

def _find_codex_exe():
    for c in CODEX_EXE_CANDIDATES:
        if os.path.exists(c):
            return c
    root = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin")
    if os.path.isdir(root):
        cands = [os.path.join(root, e, "codex.exe") for e in os.listdir(root)]
        cands = [c for c in cands if os.path.exists(c)]
        if cands:
            return max(cands, key=os.path.getmtime)
    return "codex"


def fetch_codex():
    env = dict(os.environ, CODEX_HOME=CODEX_HOME)
    p = subprocess.Popen([_find_codex_exe(), "app-server", "--listen", "stdio://"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=env, text=True,
                         encoding="utf-8", errors="replace", **_NO_WINDOW)
    try:
        def send(i, method, params):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i,
                                      "method": method, "params": params}) + "\n")
            p.stdin.flush()

        def read(want_id, timeout=20):
            end = time.time() + timeout
            while time.time() < end:
                line = p.stdout.readline()
                if not line:
                    raise RuntimeError("codex app-server exited")
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("id") == want_id:
                    if "error" in m:
                        raise RuntimeError("rpc error")
                    return m.get("result")
            raise TimeoutError("codex rpc timeout")

        send(0, "initialize", {"clientInfo": {"name": "quota-monitor", "version": "1.0"},
                               "capabilities": {"experimentalApi": True,
                                                "optOutNotificationMethods": []}})
        read(0)
        send(1, "account/rateLimits/read", None)
        result = read(1)
        send(2, "account/read", {})
        account = (read(2) or {}).get("account") or {}
    finally:
        try:
            p.kill()
        except Exception:
            pass

    rl = (result or {}).get("rateLimits") or {}
    if not rl:
        by_id = (result or {}).get("rateLimitsByLimitId") or {}
        rl = by_id.get("codex") or next(iter(by_id.values()), {})

    def window(node):
        if not node:
            return None
        used = node.get("usedPercent")
        return {"pct": (100 - int(used)) if used is not None else None,
                "mins": node.get("windowDurationMins"),
                "reset": node.get("resetsAt")}

    wins = [w for w in (window(rl.get("primary")), window(rl.get("secondary"))) if w]
    five_h = next((w for w in wins if w["mins"] and abs(w["mins"] - 300) <= 5), None)
    weekly = next((w for w in wins if w["mins"] and abs(w["mins"] - 10080) <= 60), None)
    if weekly is None and wins:
        weekly = wins[0]
    return {
        "c5_pct": five_h["pct"] if five_h else None,
        "c5_reset": five_h["reset"] if five_h else None,
        "cw_pct": weekly["pct"] if weekly else None,
        "cw_reset": weekly["reset"] if weekly else None,
        "c_plan": str(account.get("planType") or "").title(),
    }


# ---------------- Codex reset radar ----------------

def fetch_radar():
    """Global Codex reset probability forecast. Any failure -> {} (silent)."""
    try:
        d = json.load(urllib.request.urlopen(CODEX_RADAR_URL, timeout=8))
        prob = d.get("probabilities") or {}
        return {"cr_pct": prob.get("rounded_24h"),
                "cr_conf": d.get("confidence")}
    except Exception:
        return {}


# ---------------- GLM Coding Plan (optional) ----------------

def fetch_glm():
    """GLM Coding Plan quota. Requires CFG['glm_api_key'].
    Endpoint returns a list of limits: two TOKENS_LIMIT entries
    (5-hour then weekly, ascending reset_time) plus a TIME_LIMIT (MCP)."""
    key = (CFG.get("glm_api_key") or "").strip()
    if not key:
        return {}
    url = GLM_QUOTA_URLS.get(CFG.get("glm_region"), GLM_QUOTA_URLS["cn"])
    req = urllib.request.Request(url, headers={
        "Authorization": key,
        "Accept-Language": "zh-CN,zh",
        "Content-Type": "application/json",
    })
    d = json.load(urllib.request.urlopen(req, timeout=15))
    items = d
    for k in ("limits", "data"):
        if isinstance(items, dict):
            items = items.get(k, items)
    if isinstance(items, dict):
        items = items.get("limits") or []
    toks = [x for x in (items or [])
            if isinstance(x, dict) and x.get("type") == "TOKENS_LIMIT"]
    toks.sort(key=lambda x: x.get("reset_time") or 0)

    def row(x):
        if not x:
            return None, None
        pct = x.get("remaining_percent")
        try:
            pct = int(round(float(pct)))
        except Exception:
            pct = None
        ts = x.get("reset_time")
        try:
            ts = float(ts) / 1000.0  # milliseconds epoch
        except Exception:
            ts = None
        return pct, ts

    g5_pct, g5_reset = row(toks[0] if toks else None)
    gw_pct, gw_reset = row(toks[1] if len(toks) > 1 else None)
    return {"g5_pct": g5_pct, "g5_reset": g5_reset,
            "gw_pct": gw_pct, "gw_reset": gw_reset, "g_plan": "GLM"}


# ---------------- UI ----------------

class App:
    def __init__(self):
        self.root = tk.Tk()
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        self.root.title("Quota")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg=BG)
        self.topmost = tk.BooleanVar(value=True)
        self.data = {}
        self.errors = {}
        self.last_ok = None
        self._drag = None
        self.theme = "dark"
        self._cards = []
        self._name_labels = []
        self._bg_frames = []

        w, h = 232, 212
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw - w - 40}+{sh - h - 90}")

        sp1 = tk.Frame(self.root, bg=BG, height=6)
        sp1.grid(row=0, column=0)
        self._bg_frames.append(sp1)
        self.rows = {}  # key -> (pct_label, reset_label)
        self.section_titles = {}
        self.section_renews = {}
        self._section(1, "Kimi", KIMI_BLUE, [("k5", "每5小时"), ("kw", "每周")])
        self._divider = tk.Frame(self.root, bg="#3a3a4e", height=1)
        self._divider.grid(row=2, column=0, sticky="ew", padx=10, pady=1)
        self._section(3, "Codex", CODEX_GREEN,
                      [("c5", "每5小时"), ("cw", "每周"), ("cr", "雷达")])
        self._divider2 = tk.Frame(self.root, bg="#3a3a4e", height=1)
        self._divider2.grid(row=4, column=0, sticky="ew", padx=10, pady=1)
        self._section(5, "GLM", GLM_PURPLE, [("g5", "每5小时"), ("gw", "每周")])

        bar = tk.Frame(self.root, bg=BG)
        bar.grid(row=6, column=0, sticky="ew", padx=(17, 10), pady=(3, 2))
        self._bg_frames.append(bar)
        self.status = tk.Label(bar, text="初始化…", fg=FG_DIM, bg=BG,
                               font=("Microsoft YaHei UI", 9), anchor="w")
        self.status.pack(side="left")
        self.close_btn = tk.Label(bar, text="✕", fg=FG_DIM, bg=BG, cursor="hand2",
                                  font=("Microsoft YaHei UI", 9))
        self.close_btn.pack(side="right")
        self.close_btn._no_drag = True
        self.close_btn.bind("<Button-1>", lambda e: self._quit())
        self.alpha_val = 94
        self._alpha_btns = []
        for sym, d in (("－", -3), ("＋", 3)):
            b = tk.Label(bar, text=sym, fg=FG_DIM, bg=BG, cursor="hand2",
                         font=("Microsoft YaHei UI", 9))
            b.pack(side="right", padx=1)
            b._no_drag = True
            b.bind("<Button-1>", lambda e, dd=d: self._alpha_step(dd))
            self._alpha_btns.append(b)
        sp2 = tk.Frame(self.root, bg=BG, height=5)
        sp2.grid(row=7, column=0)
        self._bg_frames.append(sp2)
        self.root.grid_columnconfigure(0, weight=1)

        for wgt in self.root.winfo_children():
            self._bind(wgt)
        self._bind(self.root)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_checkbutton(label="置顶", variable=self.topmost,
                                command=self._toggle_top)
        self.menu.add_command(label="立即刷新", command=self.refresh_async)
        self.menu.add_separator()
        self._st = CFG
        self.show_kimi = tk.BooleanVar(value=self._st.get("show_kimi", True))
        self.show_codex = tk.BooleanVar(value=self._st.get("show_codex", True))
        self.show_glm = tk.BooleanVar(value=self._st.get("show_glm", False))
        self.menu.add_checkbutton(label="Kimi", variable=self.show_kimi,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="Codex", variable=self.show_codex,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="GLM", variable=self.show_glm,
                                command=self._apply_visibility)
        self.menu.add_separator()
        self.menu.add_cascade(label="Kimi 设置",
                              menu=self._build_provider_menu("kimi"))
        self.menu.add_cascade(label="Codex 设置",
                              menu=self._build_provider_menu("codex"))
        self.menu.add_separator()
        self.menu.add_command(label="白天/黑夜模式", command=self._toggle_theme)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self._quit)

        self._apply_visibility()
        self.refresh_async()
        self._schedule_next()

    def _fit(self):
        """Resize window to fit content, keeping current position."""
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 6
        h = self.root.winfo_reqheight() + 6
        self.root.geometry(f"{w}x{h}")  # size only; position unchanged
        self._round_corners()

    def _round_corners(self, radius=8):
        """Rounded corners: prefer Win11 DWM native rounding (antialiased)."""
        try:
            hwnd = int(self.root.wm_frame(), 16)
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
            pref = ctypes.c_int(2)
            ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            if ok == 0:
                return  # DWM handled rounding
        except Exception:
            pass
        # fallback for older Windows: region-based rounding (aliased)
        try:
            hwnd = int(self.root.wm_frame(), 16)
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1,
                                                         radius, radius)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _quit(self):
        try:
            self.root.withdraw()
            self.root.update_idletasks()
        except Exception:
            pass
        self.root.destroy()

    def _alpha_step(self, delta):
        self.alpha_val = max(40, min(100, self.alpha_val + delta))
        self.root.attributes("-alpha", self.alpha_val / 100)

    def _apply_visibility(self):
        CFG["show_kimi"] = self.show_kimi.get()
        CFG["show_codex"] = self.show_codex.get()
        CFG["show_glm"] = self.show_glm.get()
        _save_config(CFG)
        k, c = CFG["show_kimi"], CFG["show_codex"]
        g = CFG["show_glm"] and bool((CFG.get("glm_api_key") or "").strip())
        kimi_card, codex_card, glm_card = self._cards[0], self._cards[1], self._cards[2]
        (kimi_card.grid if k else kimi_card.grid_remove)()
        (codex_card.grid if c else codex_card.grid_remove)()
        (glm_card.grid if g else glm_card.grid_remove)()
        (self._divider.grid if (k and c) else self._divider.grid_remove)()
        (self._divider2.grid if (g and (k or c)) else self._divider2.grid_remove)()
        self._fit()

    def _toggle_theme(self):
        self.theme = "light" if getattr(self, "theme", "dark") == "dark" else "dark"
        t = THEMES[self.theme]
        self.root.configure(bg=t["BG"])
        for fr in self._bg_frames:
            fr.configure(bg=t["BG"])
        self._divider.configure(bg=t["BORDER"])
        self._divider2.configure(bg=t["BORDER"])
        for card in self._cards:
            card.configure(bg=t["BG_CARD"],
                           highlightbackground=t["BORDER"])
        for lbl in self._name_labels:
            lbl.configure(fg=t["FG_DIM"], bg=t["BG_CARD"])
        for pl, rl in self.rows.values():
            pl.configure(bg=t["BG_CARD"])
            rl.configure(fg=t["FG_DIM"], bg=t["BG_CARD"])
        for name, lbl in self.section_titles.items():
            lbl.configure(bg=t["BG_CARD"])
        soft = {"Kimi": t["KIMI_SOFT"], "Codex": t["CODEX_SOFT"], "GLM": GLM_PURPLE_SOFT}
        for name, lbl in self.section_renews.items():
            lbl.configure(fg=soft.get(name, t["FG_DIM"]), bg=t["BG_CARD"])
        self.status.configure(fg=t["FG_DIM"], bg=t["BG"])
        self.close_btn.configure(fg=t["FG_DIM"], bg=t["BG"])
        for b in self._alpha_btns:
            b.configure(fg=t["FG_DIM"], bg=t["BG"])
        self._render()  # pct 颜色按当前主题重算

    def _schedule_next(self):
        """Align auto-refresh to clock :00/:15/:30/:45."""
        now = time.time()
        nxt = (int(now // REFRESH_SECONDS) + 1) * REFRESH_SECONDS
        self.root.after(int((nxt - now) * 1000) + 500, self._auto)

    def _section(self, row, title, color, lines):
        f = tk.Frame(self.root, bg=BG_CARD,
                     highlightbackground="#33334a", highlightthickness=1)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(4, 0))
        self._cards.append(f)
        title_lbl = tk.Label(f, text=title, fg=color, bg=BG_CARD,
                             font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
        title_lbl.grid(row=0, column=0, columnspan=3, sticky="w",
                       padx=(7, 0), pady=(3, 0))
        renew_lbl = tk.Label(f, text="", bg=BG_CARD, anchor="w",
                             font=("Microsoft YaHei UI", 9))
        renew_lbl.grid(row=0, column=2, sticky="w",
                       padx=(12, 7), pady=(3, 0))
        self.section_titles[title] = title_lbl
        self.section_renews[title] = renew_lbl
        for i, (key, name) in enumerate(lines, start=1):
            nl = tk.Label(f, text=name, fg=FG_DIM, bg=BG_CARD,
                          font=("Microsoft YaHei UI", 9), anchor="w", width=8)
            nl.grid(row=i, column=0, sticky="w", padx=(7, 0))
            self._name_labels.append(nl)
            pct = tk.Label(f, text="…", fg=FG_TEXT, bg=BG_CARD,
                           font=("Microsoft YaHei UI", 9, "bold"),
                           anchor="w", width=4)
            pct.grid(row=i, column=1, sticky="w", padx=(6, 0))
            rst = tk.Label(f, text="", fg=FG_DIM, bg=BG_CARD,
                           font=("Microsoft YaHei UI", 9), anchor="w", width=11)
            rst.grid(row=i, column=2, sticky="w", padx=(12, 7),
                     pady=(0, 3 if i == len(lines) else 0))
            self.rows[key] = (pct, rst)

    def _bind(self, wgt):
        if getattr(wgt, "_no_drag", False):
            return
        wgt.bind("<ButtonPress-1>", self._drag_start)
        wgt.bind("<B1-Motion>", self._drag_move)
        wgt.bind("<Double-Button-1>", lambda e: self.refresh_async())
        wgt.bind("<Button-3>", self._menu)
        for child in wgt.winfo_children():
            self._bind(child)

    def _drag_start(self, e):
        self._drag = (e.x, e.y)

    def _drag_move(self, e):
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def _toggle_top(self):
        self.root.attributes("-topmost", self.topmost.get())

    # ---------- provider settings submenus (Kimi / Codex) ----------

    def _current_plan(self, kind):
        if kind == "kimi":
            return CFG.get("kimi_plan_name", "")
        return (CFG.get("codex_plan_name")
                or (self.data.get("c_plan") or "Pro")
                + CFG.get("codex_plan_suffix", ""))

    def _build_provider_menu(self, kind):
        presets = KIMI_PLAN_PRESETS if kind == "kimi" else CODEX_PLAN_PRESETS
        m = tk.Menu(self.menu, tearoff=0)
        cur = self._current_plan(kind)
        var = tk.StringVar(value=cur)
        setattr(self, f"_plan_var_{kind}", var)
        for name in presets:
            m.add_radiobutton(label=name, variable=var, value=name,
                              command=lambda n=name: self._set_plan(kind, n))
        # "custom" radiobutton shows as selected when current value is not a preset
        custom_val = "" if cur in presets else cur
        custom_idx = len(presets)
        m.add_radiobutton(label="自定义…", variable=var, value=custom_val,
                          command=lambda: self._ask_custom_plan(kind))
        self._plan_custom = getattr(self, "_plan_custom", {})
        self._plan_custom[kind] = (m, custom_idx)
        sub = tk.Menu(m, tearoff=0)
        sub.add_command(label="设为下个月今天",
                        command=lambda: self._set_renew(kind, "next_month"))
        sub.add_command(label="设为本月最后一天",
                        command=lambda: self._set_renew(kind, "last_day"))
        sub.add_command(label="手动输入…",
                        command=lambda: self._ask_renew(kind))
        m.add_cascade(label="续订日期", menu=sub)
        return m

    def _set_plan(self, kind, name):
        getattr(self, f"_plan_var_{kind}").set(name)
        CFG["kimi_plan_name" if kind == "kimi" else "codex_plan_name"] = name
        _save_config(CFG)
        self._render()

    def _ask_custom_plan(self, kind):
        cur = self._current_plan(kind)
        s = self._ask("自定义套餐", "套餐显示名：", initial=cur)
        if s and s.strip():
            name = s.strip()
            menu, idx = self._plan_custom[kind]
            menu.entryconfig(idx, value=name)  # make the radio match the new value
            self._set_plan(kind, name)
        else:
            getattr(self, f"_plan_var_{kind}").set(cur)  # revert selection

    def _set_renew(self, kind, mode):
        today = date.today()
        if mode == "next_month":
            y, m = (today.year + 1, 1) if today.month == 12 \
                else (today.year, today.month + 1)
            d = min(today.day, calendar.monthrange(y, m)[1])
        else:  # last_day
            y, m = today.year, today.month
            d = calendar.monthrange(y, m)[1]
        CFG[f"renew_{kind}"] = f"{m:02d}-{d:02d}"
        _save_config(CFG)
        self._render()

    def _ask_renew(self, kind):
        cur = CFG.get(f"renew_{kind}", "")
        s = self._ask("续订日期", "输入续订日期（如 08-31 / 8月31 / 0831）：",
                      initial=cur)
        if s is None:
            return
        v = _parse_mmdd(s)
        if v:
            CFG[f"renew_{kind}"] = v
            _save_config(CFG)
            self._render()
        else:
            messagebox.showerror("格式不对",
                                 f"无法识别「{s}」，请用 08-31 这类写法。",
                                 parent=self.root)

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

    def _auto(self):
        self.refresh_async()
        self._schedule_next()

    def refresh_async(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        data, errors = {}, {}
        try:
            data.update(fetch_kimi())
        except Exception as ex:
            errors["kimi"] = type(ex).__name__
        try:
            data.update(fetch_codex())
        except Exception as ex:
            errors["codex"] = type(ex).__name__
        data.update(fetch_radar())  # silent degrade: never touches errors
        if (CFG.get("glm_api_key") or "").strip():
            try:
                data.update(fetch_glm())
            except Exception as ex:
                errors["glm"] = type(ex).__name__
        self.root.after(0, lambda: self._apply(data, errors))

    def _apply(self, data, errors):
        if data:
            self.data = data
            self.last_ok = datetime.now()
        self.errors = errors
        render_err = None
        try:
            self._render()
            self._fit()
        except Exception as ex:
            render_err = repr(ex)
        try:
            dbg = {"updated": datetime.now().isoformat(timespec="seconds"),
                   "win": {"w": self.root.winfo_width(), "h": self.root.winfo_height(),
                           "reqw": self.root.winfo_reqwidth(), "reqh": self.root.winfo_reqheight()},
                   "data": data, "errors": errors, "render_err": render_err,
                   "status_text": self.status.cget("text")}
            with open(DEBUG_FILE, "w", encoding="utf-8") as f:
                json.dump(dbg, f, ensure_ascii=False, indent=1, default=str)
        except Exception:
            pass

    def _set_row(self, key, pct, reset_text):
        pl, rl = self.rows[key]
        if pct is None:
            pl.config(text="--")
            rl.config(text="")
        else:
            base = THEMES[getattr(self, "theme", "dark")]["FG_TEXT"]
            color = base if pct > 30 else ("#d08020" if pct > 15 else "#d04040")
            pl.config(text=f"{pct}%", fg=color)
            rl.config(text=reset_text if reset_text else "")

    def _render_radar(self):
        """Radar row: '雷达 24h 20%' + confidence suffix (low=·低, medium=·中)."""
        pl, rl = self.rows["cr"]
        pct = self.data.get("cr_pct")
        if pct is None:
            pl.config(text="--", fg=THEMES[self.theme]["FG_DIM"])
            rl.config(text="")
            return
        base = THEMES[self.theme]["FG_TEXT"]
        pl.config(text=f"24h {pct}%", fg=base)
        suffix = {"low": "·低", "medium": "·中"}.get(self.data.get("cr_conf"), "")
        rl.config(text=suffix)

    def _render(self):
        d = self.data
        if d.get("k_plan"):
            self.section_titles["Kimi"].config(
                text="Kimi · " + CFG.get("kimi_plan_name", ""))
            self.section_renews["Kimi"].config(
                text="续订 " + CFG.get("renew_kimi", ""), fg=KIMI_BLUE_SOFT)
        if d.get("c_plan"):
            c_plan = CFG.get("codex_plan_name") or (
                d["c_plan"] + CFG.get("codex_plan_suffix", ""))
            self.section_titles["Codex"].config(text="Codex · " + c_plan)
            self.section_renews["Codex"].config(
                text="续订 " + CFG.get("renew_codex", ""), fg=CODEX_GREEN_SOFT)
        self._set_row("k5", d.get("k5_pct"), _countdown(d.get("k5_reset")))
        self._set_row("kw", d.get("kw_pct"), _fmt_reset(d.get("kw_reset")))
        self._set_row("c5", d.get("c5_pct"),
                      _countdown(d.get("c5_reset")) if d.get("c5_reset") else "")
        self._set_row("cw", d.get("cw_pct"), _fmt_reset(d.get("cw_reset")))
        self._set_row("g5", d.get("g5_pct"),
                      _countdown(d.get("g5_reset")) if d.get("g5_reset") else "")
        self._set_row("gw", d.get("gw_pct"), _fmt_reset(d.get("gw_reset")))
        self._render_radar()

        parts = []
        if self.last_ok:
            parts.append("更新于 " + self.last_ok.strftime("%H:%M"))
        if self.errors:
            parts.append("刷新失败:" + ",".join(self.errors))
        if not parts:
            parts.append("加载中…")
        self.status.config(text="  ".join(parts),
                           fg="#d08080" if self.errors else FG_DIM)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
