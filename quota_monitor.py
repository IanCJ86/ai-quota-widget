# -*- coding: utf-8 -*-
# Quota Monitor: Kimi Code + Codex floating widget.
# Reads local credentials only; public radar calls are read-only and credential-free.
# Never prints or logs any token.
import base64
import json
import os
import sys
import calendar
import queue
import re
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timezone
from html import unescape
from monitor_runtime import (Scheduler, SingleInstance, atomic_json, dpapi_protect,
                             dpapi_unprotect, validate_result)

QUERY_MODE = len(sys.argv) == 3 and sys.argv[1] == "--query"
if not QUERY_MODE:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        pystray = None  # Main window still works if optional tray packages are absent.

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
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-good.json")
# GLM key storage: config.json is plaintext, so the settings menu encrypts the
# key with Windows DPAPI instead (user-scoped, decryptable only on this account).
GLM_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glm-key.dpapi")
GLM_KEY_ENV = "AI_QUOTA_WIDGET_GLM_API_KEY"   # preferred: no secret on disk at all
# DeepSeek is pay-as-you-go: its API reports a money balance, not a percentage.
DEEPSEEK_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deepseek-key.dpapi")
DEEPSEEK_KEY_ENV = "AI_QUOTA_WIDGET_DEEPSEEK_API_KEY"
DEEPSEEK_ENV = "DEEPSEEK_API_KEY"             # name used by the official CLI/SDK
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"

DEFAULT_CONFIG = {
    # ---- personal display options (edit config.json, not this file) ----
    "renew_kimi": "MM-DD",        # Kimi renewal date shown in the UI, e.g. "09-01"
    "renew_codex": "MM-DD",       # Codex renewal date shown in the UI
    "kimi_plan_name": "MyPlan",   # Kimi plan display name (API only returns a level)
    "codex_plan_name": "",        # Codex plan display override; empty = API planType + suffix
    "codex_plan_suffix": "",      # suffix appended to Codex planType, e.g. " 20x"
    "glm_plan_name": "",          # GLM plan display name, e.g. "Lite" / "Pro" / "Max"
    "renew_glm": "MM-DD",         # GLM renewal date shown in the UI
    "custom_plan_kimi": "",       # user-defined plan names (kept as menu entries)
    "custom_plan_codex": "",
    "custom_plan_glm": "",
    "theme": "dark",              # dark / light / glass
    # ---- visibility toggles (also in the right-click menu) ----
    "show_kimi": True,
    "show_codex": True,
    # None = follow the selected plan: Pro hidden, other plans shown.
    # A boolean is a user's explicit menu override.
    "show_codex_5h": None,
    "show_radar": True,
    "radar_window": 24,   # 24 or 48 hours
    "tray_metric": "cw_pct",  # Codex weekly percentage in the Windows tray
    "show_glm": False,            # GLM card visibility; rows show "--" until a key works
    # DeepSeek has no percentage quota, so the card shows money instead.
    "show_deepseek": True,
    # ---- GLM Coding Plan (optional) ----
    # Legacy plaintext field: still honoured, but the settings menu stores new
    # keys encrypted (GLM_KEY_FILE) and clears this one on save.
    "glm_api_key": "",
    "glm_region": "cn",           # "cn" -> open.bigmodel.cn, "intl" -> api.z.ai
    # ---- DeepSeek (pay-as-you-go balance) ----
    "deepseek_api_key": "",       # legacy plaintext field, same rules as glm_api_key
    # Money cannot be a percentage: warn below this amount and alarm below a
    # quarter of it. Set to 0 to switch the colour warning off.
    "deepseek_low_balance": 20.0,
}


def _load_config():
    cfg = dict(DEFAULT_CONFIG)
    for path in (SETTINGS_FILE, CONFIG_FILE):  # legacy settings.json first, config.json wins
        try:
            with open(path, encoding="utf-8") as stream:
                cfg.update(json.load(stream))
        except Exception:
            pass
    return cfg


def _save_config(cfg):
    try:
        atomic_json(CONFIG_FILE, cfg)
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

_CODEX_PROCESS_LOCK = threading.Lock()
_CODEX_ACTIVE_PROCESS = None

# colors
TRANSP_KEY = "#010102"  # glass colorkey: root pixels of this color go transparent
THEMES = {
    "dark": dict(BG="#1e1e2e", BG_CARD="#262638", BORDER="#3a3a4e",
                 FG_DIM="#7a7a90", FG_TEXT="#e8e8f4",
                 KIMI_SOFT="#8db4e8", CODEX_SOFT="#83d4ab"),
    "light": dict(BG="#f2f3f7", BG_CARD="#ffffff", BORDER="#d9dae4",
                  FG_DIM="#8a8a9a", FG_TEXT="#23233a",
                  KIMI_SOFT="#4a7fc9", CODEX_SOFT="#3a9e6e"),
    # glass: root/spacer/bar pixels use TRANSP_KEY and become see-through,
    # acrylic blur is applied behind them; cards stay solid for readability
    "glass": dict(BG=TRANSP_KEY, BG_CARD="#2b2b3d", BORDER="#55556e",
                  FG_DIM="#a0a0b8", FG_TEXT="#f2f2f8",
                  KIMI_SOFT="#8db4e8", CODEX_SOFT="#83d4ab"),
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
DEEPSEEK_BLUE = "#4d6bfe"
DEEPSEEK_SOFT = "#8fa2ff"
PLAN_PRESETS = {
    "kimi": ["Andante", "Moderato", "Allegretto", "Allegro"],
    "codex": ["Go", "Plus", "Pro 5x", "Pro 20x"],
    "glm": ["Lite", "Pro", "Max"],
}
PLAN_CFG_KEY = {"kimi": "kimi_plan_name", "codex": "codex_plan_name",
                "glm": "glm_plan_name"}
# Global reset sources are public, third-party signals. They do not expose or
# replace the account-specific Codex quota below.
CODEX_RESETS_PAGE_URL = "https://codex-resets.com/"
CODEX_RESETS_API_URL = "https://codex-resets.com/api/v1/status"
CODEX_RADAR_URL = "https://codexreset.org/"
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
    with open(KIMI_CRED, encoding="utf-8") as stream:
        cred = json.load(stream)
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
                with urllib.request.urlopen(req, timeout=15) as response:
                    r = json.load(response)
                if r.get("access_token"):
                    cred["access_token"] = r["access_token"]
                    if r.get("refresh_token"):
                        cred["refresh_token"] = r["refresh_token"]
                    if r.get("expires_in"):
                        cred["expires_at"] = int(time.time()) + int(r["expires_in"])
                    atomic_json(KIMI_CRED, cred)
                    break
            except Exception:
                continue
    req = urllib.request.Request(KIMI_USAGE_URL,
                                 headers={"Authorization": "Bearer " + cred["access_token"]})
    with urllib.request.urlopen(req, timeout=15) as response:
        d = json.load(response)

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
    five_h = five_h or {}

    def pct_left(detail):
        try:
            if detail.get("used") is not None and detail.get("limit"):
                return max(0, min(100, 100 - int(detail["used"]) * 100 // int(detail["limit"])))
            if detail.get("remaining") is not None and detail.get("limit"):
                return max(0, min(100, int(detail["remaining"]) * 100 // int(detail["limit"])))
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
    global _CODEX_ACTIVE_PROCESS
    env = dict(os.environ, CODEX_HOME=CODEX_HOME)
    p = subprocess.Popen([_find_codex_exe(), "app-server", "--listen", "stdio://"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=env, text=True,
                         encoding="utf-8", errors="replace", **_NO_WINDOW)
    with _CODEX_PROCESS_LOCK:
        _CODEX_ACTIVE_PROCESS = p
    output = queue.Queue(maxsize=128)

    def collect_stdout():
        try:
            for line in p.stdout:
                # Drop excess notifications instead of growing memory without limit.
                if len(line) <= 262144:
                    try:
                        output.put(line, timeout=1)
                    except queue.Full:
                        return
        finally:
            try:
                output.put_nowait(None)
            except queue.Full:
                pass

    reader = threading.Thread(target=collect_stdout, daemon=True)
    reader.start()
    try:
        def send(i, method, params):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i,
                                      "method": method, "params": params}) + "\n")
            p.stdin.flush()

        def read(want_id, timeout=20):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                try:
                    line = output.get(timeout=max(0.01, end - time.monotonic()))
                except queue.Empty:
                    raise TimeoutError("codex rpc timeout")
                if line is None:
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
        account = {}
        try:
            send(2, "account/read", {})
            account = (read(2, timeout=3) or {}).get("account") or {}
        except Exception:
            pass  # Optional plan name must not discard valid quota data.
    finally:
        try:
            p.kill()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass
        with _CODEX_PROCESS_LOCK:
            if _CODEX_ACTIVE_PROCESS is p:
                _CODEX_ACTIVE_PROCESS = None
        reader.join(timeout=1)
        try:
            p.stdin.close()
        except OSError:
            pass
        if not reader.is_alive():
            p.stdout.close()

    by_id = (result or {}).get("rateLimitsByLimitId") or {}
    rl = by_id.get("codex") or (result or {}).get("rateLimits") or {}

    def window(node):
        if not node:
            return None
        used = node.get("usedPercent")
        return {"pct": max(0, min(100, 100 - int(used))) if used is not None else None,
                "mins": node.get("windowDurationMins"),
                "reset": node.get("resetsAt")}

    wins = [w for w in (window(rl.get("primary")), window(rl.get("secondary"))) if w]
    five_h = next((w for w in wins if w["mins"] and abs(w["mins"] - 300) <= 5), None)
    weekly = next((w for w in wins if w["mins"] and abs(w["mins"] - 10080) <= 60), None)

    def expired(node):
        """True when the window this percentage belongs to already ended.

        The app-server serves the locally stored snapshot and exposes no
        capture time; a reset timestamp in the past is the only freshness
        signal available, and it means the percentage describes an older
        window."""
        try:
            return float(node["reset"]) <= time.time()
        except (KeyError, TypeError, ValueError):
            return False

    shown = [w for w in (five_h, weekly) if w]
    return {
        "c5_pct": five_h["pct"] if five_h else None,
        "c5_reset": five_h["reset"] if five_h else None,
        "cw_pct": weekly["pct"] if weekly else None,
        "cw_reset": weekly["reset"] if weekly else None,
        "c_plan": str(account.get("planType") or rl.get("planType") or "").title(),
        # Any displayed window that already reset makes the snapshot stale; the
        # UI greys it instead of passing it off as the current value.
        "c_window_expired": bool(shown) and any(expired(w) for w in shown),
    }


# ---------------- Codex reset radar ----------------

def _fetch_public_text(url, accept):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ai-quota-widget/1.0", "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("response too large")
        return raw


def _visible_html_text(raw):
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def _int_match(pattern, text):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def fetch_main_radar():
    html = _fetch_public_text(CODEX_RADAR_URL, "text/html").decode("utf-8", errors="replace")
    return {
        "cr_main24": _int_match(
            r'data-testid="probability-ring-24h"[^>]*data-target-value="(\d+)"', html),
        "cr_main48": _int_match(
            r'data-testid="probability-ring-48h"[^>]*data-target-value="(\d+)"', html),
        "cr_main_updated": datetime.now(timezone.utc).isoformat(),
        "cr_main_mode": "model",
    }


def fetch_community_radar():
    try:
        page = _visible_html_text(_fetch_public_text(
            CODEX_RESETS_PAGE_URL, "text/html,application/xhtml+xml"))
        pct = _int_match(
            r"Possible reset\s+(\d+)\s*%\s+chance of reset", page)
        if pct is not None:
            return {"cr_resets_pct": pct, "cr_resets_mode": "community_vote",
                    "cr_resets_updated": datetime.now(timezone.utc).isoformat()}
    except Exception:
        pass  # Independent, bounded API fallback.
    d = json.loads(_fetch_public_text(CODEX_RESETS_API_URL, "application/json").decode("utf-8"))
    body = d.get("data")
    if not isinstance(body, dict) or "active_watch" not in body:
        raise ValueError("community schema changed")
    watch = body["active_watch"]
    if watch is None:
        return {"cr_resets_pct": None, "cr_resets_mode": "no_watch"}
    # The percent field is already 0..100; 1 means 1%, not 100%.
    pct = float(watch["reset_chance_percent"])
    return {"cr_resets_pct": round(pct), "cr_resets_mode": "api_watch",
            "cr_resets_updated": (d.get("meta") or {}).get("generated_at")}


# ---------------- provider API keys (GLM / DeepSeek) ----------------

def _windows_env(name):
    """Read a user environment variable straight from the registry.

    A widget started before the variable was added keeps its old environment,
    and Explorer only picks up HKCU\\Environment changes after a settings
    broadcast, so read the value directly instead of trusting os.environ.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value or "").strip()
    except Exception:
        return ""


def _read_protected_key(path):
    """Read a DPAPI-protected key written by the settings menu."""
    try:
        with open(path, encoding="utf-8") as stream:
            record = json.load(stream)
        if record.get("scheme") != "dpapi":
            return ""
        secret = dpapi_unprotect(base64.b64decode(record.get("data") or ""))
        return secret.decode("utf-8").strip() if secret else ""
    except Exception:
        return ""


def provider_key(path, env_names, field):
    """Resolve an API key: environment, then encrypted file, then legacy config.

    config.json is plaintext on disk, so the settings menu writes keys through
    Windows DPAPI and drops the plaintext copy; the legacy field keeps working
    for existing installs.
    """
    for name in env_names:
        value = (os.environ.get(name) or _windows_env(name) or "").strip()
        if value:
            return value
    stored = _read_protected_key(path)
    if stored:
        return stored
    return (CFG.get(field) or "").strip()


def save_provider_key(path, field, key):
    """Encrypt the key for the current user. Never falls back to plaintext."""
    key = (key or "").strip()
    if not key:
        return False
    blob = dpapi_protect(key)
    if not blob:
        return False
    try:
        atomic_json(path, {"version": 1, "scheme": "dpapi",
                           "data": base64.b64encode(blob).decode("ascii")})
    except OSError:
        return False
    if CFG.get(field):
        CFG[field] = ""   # the encrypted copy replaces the plaintext one
        _save_config(CFG)
    return True


def clear_provider_key(path, field):
    """Delete every stored copy: the encrypted file and the legacy field."""
    removed = False
    try:
        os.unlink(path)
        removed = True
    except OSError:
        pass
    if CFG.get(field):
        CFG[field] = ""
        _save_config(CFG)
        removed = True
    return removed


def glm_api_key():
    return provider_key(GLM_KEY_FILE, (GLM_KEY_ENV,), "glm_api_key")


def save_glm_key(key):
    return save_provider_key(GLM_KEY_FILE, "glm_api_key", key)


def clear_glm_key():
    return clear_provider_key(GLM_KEY_FILE, "glm_api_key")


def deepseek_api_key():
    return provider_key(DEEPSEEK_KEY_FILE, (DEEPSEEK_KEY_ENV, DEEPSEEK_ENV),
                        "deepseek_api_key")


def save_deepseek_key(key):
    return save_provider_key(DEEPSEEK_KEY_FILE, "deepseek_api_key", key)


def clear_deepseek_key():
    return clear_provider_key(DEEPSEEK_KEY_FILE, "deepseek_api_key")


def fetch_glm():
    """GLM Coding Plan quota. Requires a configured GLM Coding Plan key.
    Endpoint returns a list of limits: two TOKENS_LIMIT entries
    (5-hour then weekly, ascending reset_time) plus a TIME_LIMIT (MCP)."""
    key = glm_api_key()
    if not key:
        return {}
    url = GLM_QUOTA_URLS.get(CFG.get("glm_region"), GLM_QUOTA_URLS["cn"])
    req = urllib.request.Request(url, headers={
        "Authorization": key,
        "Accept-Language": "zh-CN,zh",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        d = json.load(response)
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


# ---------------- DeepSeek (pay-as-you-go balance) ----------------

def fetch_deepseek():
    """DeepSeek API balance. There is no percentage quota and no public usage
    endpoint; `/user/balance` returns money, so the card shows money."""
    key = deepseek_api_key()
    if not key:
        return {}
    req = urllib.request.Request(DEEPSEEK_BALANCE_URL, headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        d = json.load(response)
    infos = [x for x in (d.get("balance_infos") or []) if isinstance(x, dict)]
    if not infos:
        raise ValueError("no balance info")
    # Prefer CNY when the account reports several currencies.
    info = next((x for x in infos if str(x.get("currency") or "").upper() == "CNY"),
                infos[0])

    def amount(field):
        try:
            return round(float(info.get(field) or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    return {
        "ds_balance": amount("total_balance"),
        "ds_granted": amount("granted_balance"),
        "ds_topped_up": amount("topped_up_balance"),
        "ds_currency": str(info.get("currency") or "").upper()[:8],
        "ds_available": bool(d.get("is_available")),
        "ds_plan": "按量付费",
    }


# ---------------- UI ----------------

class App:
    def __init__(self, instance=None):
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
        self.instance = instance
        self._closed = False
        self._commands = queue.SimpleQueue()
        self._verified = set()
        self._success_at = {}
        self._diagnostics = {}
        self._ui_error = None
        self._last_render_minute = None
        self._tray_value = object()
        self._tray_thread = None
        self._tray_failed = False
        self.scheduler = Scheduler(os.path.abspath(__file__), self._on_result, REFRESH_SECONDS)
        self._load_cache()
        self._drag = None
        self.theme = "dark"
        self.tray = None
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
        self.row_labels = {}
        self.section_titles = {}
        self.section_renews = {}
        self._section(1, "Kimi", KIMI_BLUE, [("k5", "每5小时"), ("kw", "每周")])
        self._divider = tk.Frame(self.root, bg="#3a3a4e", height=1)
        self._divider.grid(row=2, column=0, sticky="ew", padx=10, pady=1)
        self._section(3, "GLM", GLM_PURPLE, [("g5", "每5小时"), ("gw", "每周")])
        self._divider2 = tk.Frame(self.root, bg="#3a3a4e", height=1)
        self._divider2.grid(row=4, column=0, sticky="ew", padx=10, pady=1)
        self._section(5, "Codex", CODEX_GREEN,
                      [("c5", "每5小时"), ("cw", "每周"),
                       ("cr_main", "主源"),
                       ("cr_resets", "社区")])
        self._divider3 = tk.Frame(self.root, bg="#3a3a4e", height=1)
        self._divider3.grid(row=6, column=0, sticky="ew", padx=10, pady=1)
        # DeepSeek is pay-as-you-go, so this card shows a money balance.
        self._section(7, "DeepSeek", DEEPSEEK_BLUE, [("ds", "余额")])
        self._dividers = [self._divider, self._divider2, self._divider3]

        bar = tk.Frame(self.root, bg=BG)
        bar.grid(row=8, column=0, sticky="ew", padx=(17, 10), pady=(3, 2))
        self._bg_frames.append(bar)
        self.status = tk.Label(bar, text="初始化…", fg=FG_DIM, bg=BG,
                               font=("Microsoft YaHei UI", 9), anchor="w")
        self.status.pack(side="left")
        self.close_btn = tk.Label(bar, text="✕", fg=FG_DIM, bg=BG, cursor="hand2",
                                  font=("Microsoft YaHei UI", 9))
        self.close_btn.pack(side="right")
        self.close_btn._no_drag = True
        self.close_btn.bind("<Button-1>", lambda e: self._minimize_to_tray())
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
        sp2.grid(row=9, column=0)
        self._bg_frames.append(sp2)
        self.root.grid_columnconfigure(0, weight=1)

        for wgt in self.root.winfo_children():
            self._bind(wgt)
        self._bind(self.root)

        self.menu = tk.Menu(self.root, tearoff=0)
        self._st = CFG
        self.menu.add_checkbutton(label="置顶", variable=self.topmost,
                                command=self._toggle_top)
        self.menu.add_command(label="立即刷新", command=self.refresh_async)
        self.menu.add_separator()
        self.show_kimi = tk.BooleanVar(value=self._st.get("show_kimi", True))
        self.show_codex = tk.BooleanVar(value=self._st.get("show_codex", True))
        self.show_codex_5h = tk.BooleanVar(value=self._codex_5h_visible())
        self.show_glm = tk.BooleanVar(value=self._st.get("show_glm", False))
        self.show_deepseek = tk.BooleanVar(value=self._st.get("show_deepseek", True))
        self.menu.add_checkbutton(label="Kimi Coding Plan", variable=self.show_kimi,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="GLM Coding Plan", variable=self.show_glm,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="Codex", variable=self.show_codex,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="DeepSeek 余额", variable=self.show_deepseek,
                                command=self._apply_visibility)
        self.menu.add_checkbutton(label="Codex 每5小时窗口", variable=self.show_codex_5h,
                                command=self._apply_visibility)
        self.show_radar = tk.BooleanVar(value=self._st.get("show_radar", True))
        self.menu.add_checkbutton(label="Codex 重置雷达", variable=self.show_radar,
                                command=self._apply_visibility)
        self._radar_var = tk.StringVar(value=str(self._st.get("radar_window", 24)))
        rw = tk.Menu(self.menu, tearoff=0)
        for label, val in (("24小时内", "24"), ("48小时内", "48")):
            rw.add_radiobutton(label=label, variable=self._radar_var, value=val,
                               command=lambda v=val: self._set_radar_window(int(v)))
        self.menu.add_cascade(label="雷达窗口", menu=rw)
        self.menu.add_separator()
        self.menu.add_cascade(label="Kimi Coding Plan 设置",
                              menu=self._build_provider_menu("kimi"))
        self.menu.add_cascade(label="GLM Coding Plan 设置",
                              menu=self._build_provider_menu("glm"))
        self.menu.add_cascade(label="Codex 设置",
                              menu=self._build_provider_menu("codex"))
        self.menu.add_cascade(label="DeepSeek 设置",
                              menu=self._build_deepseek_menu())
        self.menu.add_separator()
        self._theme_var = tk.StringVar(value=self.theme)
        tm = tk.Menu(self.menu, tearoff=0)
        for label, name in (("黑夜", "dark"), ("白天", "light"), ("毛玻璃", "glass")):
            tm.add_radiobutton(label=label, variable=self._theme_var, value=name,
                               command=lambda n=name: self._set_theme(n))
        self.menu.add_cascade(label="主题", menu=tm)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self._quit)

        self._apply_visibility(persist=False)
        self._set_theme(CFG.get("theme", "dark"))
        self._init_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self.refresh_async()
        self.root.after(100, self._poll)

    def _fit(self):
        """Resize window to fit content, clamped fully on-screen."""
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 6
        h = self.root.winfo_reqheight() + 6
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        # only pull back when genuinely overflowing the screen edges
        if x + w > sw - 8:
            x = sw - w - 8
        if y + h > sh - 48:  # keep clear of taskbar
            y = sh - h - 48
        if x < -w // 2:
            x = 8
        if y < -h // 2:
            y = 8
        self.root.geometry(f"{w}x{h}+{x}+{y}")
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
        if self._closed:
            return
        self._closed = True
        self.scheduler.close()  # Reap only our Job Object trees, never other Codex tasks.
        # Nothing may run after destroy(): a callback that outlives its
        # interpreter only produces Tcl "invalid command name" noise.
        try:
            for timer in self.root.tk.eval("after info").split():
                self.root.tk.call("after", "cancel", timer)
        except Exception:
            pass
        try:
            self.root.withdraw()
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def _minimize_to_tray(self):
        """Close button hides the main window; tray menu remains available."""
        if self.tray is not None and self.tray.visible and self._tray_thread.is_alive():
            self.root.withdraw()
        else:
            self.status.config(text="托盘不可用，窗口已保留")

    def _tray_image(self, value, stale=False):
        """Create a transparent tray icon showing the selected percentage."""
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        pct = int(value) if value is not None else None
        color = (131, 212, 171, 255) if pct is None or pct > 30 else (
            (208, 128, 32, 255) if pct > 15 else (208, 64, 64, 255))
        if stale:
            color = (155, 155, 165, 255)
        text = "--" if pct is None else str(pct)
        try:
            size = 46 if pct is not None and len(text) <= 2 else 34
            font = ImageFont.truetype(r"C:\Windows\Fonts\calibrib.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        x = (64 - (box[2] - box[0])) / 2
        y = (64 - (box[3] - box[1])) / 2 - 9
        draw.text((x, y), text, fill=color, font=font)
        return image

    def _init_tray(self):
        if pystray is None:
            self._tray_failed = True
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示额度监控", self._tray_show, default=True),
            pystray.MenuItem("立即刷新", self._tray_refresh),
            pystray.MenuItem("退出", self._tray_quit),
        )
        try:
            self.tray = pystray.Icon("quota-monitor", self._tray_image(None),
                                     "Codex 每周 --", menu)
            def run_tray():
                try:
                    self.tray.run()
                except Exception:
                    self._commands.put("tray_failed")
            self._tray_thread = threading.Thread(target=run_tray, daemon=True)
            self._tray_thread.start()
        except Exception:
            self.tray = None
            self._tray_failed = True

    def _tray_show(self, icon, item):
        self._commands.put("show")

    def _tray_refresh(self, icon, item):
        self._commands.put("refresh")

    def _tray_quit(self, icon, item):
        self._commands.put("quit")

    def _update_tray(self):
        if self.tray is None:
            return
        metric = CFG.get("tray_metric", "cw_pct")
        value = self.data.get(metric)
        source = "codex" if metric.startswith("c") else "kimi" if metric.startswith("k") else "glm"
        stale = self._is_stale(source)
        key = (metric, value, stale)
        if key != self._tray_value:
            self.tray.icon = self._tray_image(value, stale)
            self._tray_value = key
        shown = "--" if value is None else f"{int(value)}%"
        stamp = self._success_at.get(source)
        when = datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M") if stamp else "尚无成功数据"
        title = f"{source.title()} {'每周' if 'w_' in metric else '5小时'} {shown} | {'旧数据' if stale else '更新'} {when}"
        if self.tray.title != title:
            self.tray.title = title

    def _alpha_step(self, delta):
        self.alpha_val = max(40, min(100, self.alpha_val + delta))
        self.root.attributes("-alpha", self.alpha_val / 100)

    def _set_radar_window(self, hours):
        CFG["radar_window"] = hours
        _save_config(CFG)
        self._render()

    def _codex_5h_default_visible(self):
        """Plan default: Pro has no 5-hour window; other plans do."""
        plan = (self._current_plan("codex") or "").strip().lower()
        return not plan.startswith("pro")

    def _codex_5h_visible(self):
        override = CFG.get("show_codex_5h")
        return self._codex_5h_default_visible() if override is None else bool(override)

    def _sync_codex_5h_menu(self):
        if hasattr(self, "show_codex_5h"):
            self.show_codex_5h.set(self._codex_5h_visible())

    # Card order in the window; dividers sit between consecutive cards.
    CARD_ORDER = ("kimi", "glm", "codex", "deepseek")

    def _apply_visibility(self, persist=True):
        CFG["show_kimi"] = self.show_kimi.get()
        CFG["show_codex"] = self.show_codex.get()
        CFG["show_glm"] = self.show_glm.get()
        CFG["show_deepseek"] = self.show_deepseek.get()
        if persist:
            # A clicked checkbutton is an explicit user override. Leaving this
            # as None is how the plan-based default remains active.
            CFG["show_codex_5h"] = self.show_codex_5h.get()
        visible = {name: bool(getattr(self, "show_" + name).get())
                   for name in self.CARD_ORDER}
        for card, name in zip(self._cards, self.CARD_ORDER):
            (card.grid if visible[name] else card.grid_remove)()
        # Exactly one divider between two neighbouring visible cards (the slot
        # just above the lower one), so hiding a card in the middle never
        # leaves two lines stacked together.
        indexes = [i for i, name in enumerate(self.CARD_ORDER) if visible[name]]
        wanted = {lower - 1 for _, lower in zip(indexes, indexes[1:])}
        for index, divider in enumerate(self._dividers):
            (divider.grid if index in wanted else divider.grid_remove)()
        if persist:
            CFG["show_radar"] = self.show_radar.get()
            _save_config(CFG)
        if hasattr(self, "scheduler"):
            self.scheduler.configure(self._enabled_sources())
        c5_visible = visible["codex"] and self.show_codex_5h.get()
        self._set_row_visible("c5", c5_visible)
        for key in ("cr_main", "cr_resets"):
            if key in self.rows:
                widgets = [self.row_labels[key][0], *self.rows[key]]
                for wgt in widgets:
                    (wgt.grid if (visible["codex"] and CFG["show_radar"])
                     else wgt.grid_remove)()
        self._fit()

    def _apply_acrylic(self, on):
        """SetWindowCompositionAttribute: ACCENT_ENABLE_ACRYLICBLURBEHIND (4)
        when on, ACCENT_DISABLED (0) when off. Returns True on success."""
        try:
            hwnd = int(self.root.wm_frame(), 16)
            # ABGR tint for acrylic: alpha 0x99, color #1e1e2e (dark slate)
            tint = (0x99 << 24) | (0x2E << 16) | (0x1E << 8) | 0x1E

            class ACCENTPOLICY(ctypes.Structure):
                _fields_ = [("AccentState", ctypes.c_int),
                            ("AccentFlags", ctypes.c_int),
                            ("GradientColor", ctypes.c_uint),
                            ("AnimationId", ctypes.c_int)]

            class WCA(ctypes.Structure):
                _fields_ = [("Attribute", ctypes.c_int),
                            ("Data", ctypes.c_void_p),
                            ("SizeOfData", ctypes.c_size_t)]

            accent = ACCENTPOLICY(4 if on else 0, 0, tint if on else 0, 0)
            data = WCA(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p),
                       ctypes.sizeof(accent))
            return bool(ctypes.windll.user32.SetWindowCompositionAttribute(
                hwnd, ctypes.byref(data)))
        except Exception:
            return False

    def _set_theme(self, name):
        if name not in THEMES:
            name = "dark"
        leaving_glass = getattr(self, "theme", "dark") == "glass" and name != "glass"
        if name == "glass":
            # Acrylic is best-effort: if SetWindowCompositionAttribute or the
            # colorkey is unsupported, the window just stays solid with the
            # glass palette (readable, no blur) -- a deliberate graceful degrade.
            self._acrylic_on = self._apply_acrylic(True)
            try:
                self.root.attributes("-transparentcolor", TRANSP_KEY)
            except Exception:
                self._acrylic_on = False
        elif leaving_glass:
            try:
                self.root.attributes("-transparentcolor", "")
            except Exception:
                pass
            self._apply_acrylic(False)
            self._acrylic_on = False
        self.theme = name
        if hasattr(self, "_theme_var"):
            self._theme_var.set(name)
        if CFG.get("theme") != name:
            CFG["theme"] = name
            _save_config(CFG)
        t = THEMES[name]
        self.root.configure(bg=t["BG"])
        for fr in self._bg_frames:
            fr.configure(bg=t["BG"])
        for divider in self._dividers:
            divider.configure(bg=t["BORDER"])
        for card in self._cards:
            card.configure(bg=t["BG_CARD"],
                           highlightbackground=t["BORDER"])
        for lbl in self._name_labels:
            lbl.configure(fg=t["FG_DIM"], bg=t["BG_CARD"])
        for pl, rl in self.rows.values():
            pl.configure(bg=t["BG_CARD"])
            rl.configure(fg=t["FG_DIM"], bg=t["BG_CARD"])
        for lbl in self.section_titles.values():
            lbl.configure(bg=t["BG_CARD"])
        soft = {"Kimi": t["KIMI_SOFT"], "Codex": t["CODEX_SOFT"], "GLM": GLM_PURPLE_SOFT}
        for lbl_name, lbl in self.section_renews.items():
            lbl.configure(fg=soft.get(lbl_name, t["FG_DIM"]), bg=t["BG_CARD"])
        self.status.configure(fg=t["FG_DIM"], bg=t["BG"])
        self.close_btn.configure(fg=t["FG_DIM"], bg=t["BG"])
        for b in self._alpha_btns:
            b.configure(fg=t["FG_DIM"], bg=t["BG"])
        self._render()  # pct 颜色按当前主题重算

    def _section(self, row, title, color, lines):
        f = tk.Frame(self.root, bg=BG_CARD,
                     highlightbackground="#33334a", highlightthickness=1)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(4, 0))
        self._cards.append(f)
        # fixed pixel column widths so titles never distort alignment across cards
        f.grid_columnconfigure(0, minsize=64)
        f.grid_columnconfigure(1, minsize=34)
        f.grid_columnconfigure(2, minsize=100)
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
                          font=("Microsoft YaHei UI", 9), anchor="w", width=9)
            nl.grid(row=i, column=0, sticky="w", padx=(7, 0))
            self._name_labels.append(nl)
            self.row_labels[key] = (nl,)
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

    # ---------- provider settings submenus (Kimi / Codex / GLM) ----------

    def _current_plan(self, kind):
        if kind == "kimi":
            return CFG.get("kimi_plan_name", "")
        if kind == "glm":
            return CFG.get("glm_plan_name", "")
        return (CFG.get("codex_plan_name")
                or (self.data.get("c_plan") or "Pro")
                + CFG.get("codex_plan_suffix", ""))

    def _build_provider_menu(self, kind):
        presets = PLAN_PRESETS[kind]
        m = tk.Menu(self.menu, tearoff=0)
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
        if kind == "glm":
            m.add_separator()
            # config.json is plaintext; store new keys encrypted instead.
            m.add_command(label="安全保存 API Key…",
                          command=lambda: self._save_key_secure("glm"))
            m.add_command(label="清除已保存的 Key",
                          command=lambda: self._clear_key("glm"))
        return m

    def _build_deepseek_menu(self):
        """DeepSeek has no plans or renewal dates: only the API key."""
        m = tk.Menu(self.menu, tearoff=0)
        m.add_command(label="安全保存 API Key…",
                      command=lambda: self._save_key_secure("deepseek"))
        m.add_command(label="清除已保存的 Key",
                      command=lambda: self._clear_key("deepseek"))
        return m

    def _set_plan(self, kind, name):
        getattr(self, f"_plan_var_{kind}").set(name)
        CFG[PLAN_CFG_KEY[kind]] = name
        _save_config(CFG)
        if kind == "codex" and CFG.get("show_codex_5h") is None:
            self._sync_codex_5h_menu()
            self._apply_visibility(persist=False)
        self._render()

    def _ask_custom_plan(self, kind):
        s = self._ask("自定义套餐", "套餐显示名：",
                      initial=self._current_plan(kind))
        if not (s and s.strip()):
            return  # cancel or empty: no change at all
        name = s.strip()
        getattr(self, f"_plan_var_{kind}").set(name)
        CFG[PLAN_CFG_KEY[kind]] = name
        _save_config(CFG)
        self._render()

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
        v = self._renew_picker(kind)
        if v:
            CFG[f"renew_{kind}"] = v
            _save_config(CFG)
            self._render()

    def _renew_picker(self, kind):
        """Modal month/day picker (no keyboard input, no year involved).

        Returns "MM-DD" or None on cancel. Day overflow (e.g. Feb 31) is
        clamped to the month's last day with a notice, instead of rejecting.
        """
        cur = CFG.get(f"renew_{kind}", "")
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
        lbl = dict(bg=BG, fg=FG_TEXT, font=("Microsoft YaHei UI", 9))
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

    # Provider key handling shared by the GLM and DeepSeek settings menus.
    KEY_TOOLS = {
        "glm": ("GLM API Key", save_glm_key, clear_glm_key),
        "deepseek": ("DeepSeek API Key", save_deepseek_key, clear_deepseek_key),
    }

    def _save_key_secure(self, kind):
        """Store a provider key with DPAPI and remove any plaintext copy."""
        title, save, _ = self.KEY_TOOLS[kind]
        key = self._ask_secret(title, title + "：")
        if not key:
            return
        if save(key):
            self._notice("已保存", "Key 已用当前 Windows 账户加密保存在本机，\n"
                                   "config.json 里的明文已清除。")
        else:
            self._notice("保存失败", "本机加密不可用，Key 未保存。\n"
                                     "（程序不会把 Key 以明文写进文件。）")
        self._apply_visibility()

    def _clear_key(self, kind):
        _, _, clear = self.KEY_TOOLS[kind]
        if clear():
            self._notice("已清除", "本机保存的 Key 已删除。")
        self._apply_visibility()

    def _set_glm_key_secure(self):
        self._save_key_secure("glm")

    def _clear_glm_key(self):
        self._clear_key("glm")

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
                 font=("Microsoft YaHei UI", 9)).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 2))
        tk.Label(win, text="只保存在本机（Windows 加密），不会写入 config.json。",
                 bg=BG, fg=FG_DIM, anchor="w",
                 font=("Microsoft YaHei UI", 8)).grid(
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

    def refresh_async(self):
        if self._closed:
            return
        self.scheduler.configure(self._enabled_sources())
        self.scheduler.refresh()
        self.scheduler.tick()
        self.status.config(text="刷新中…（保留上次数据）")

    def _enabled_sources(self):
        names = []
        if CFG.get("show_codex", True) or CFG.get("tray_metric", "cw_pct").startswith("c"):
            names.append("codex")
        if CFG.get("show_kimi", True) or CFG.get("tray_metric", "cw_pct").startswith("k"):
            names.append("kimi")
        if CFG.get("show_codex", True) and CFG.get("show_radar", True):
            names.extend(("main", "community"))
        if CFG.get("show_glm") and glm_api_key():
            names.append("glm")
        if CFG.get("show_deepseek", True) and deepseek_api_key():
            names.append("deepseek")
        return names

    # Sources whose payload can admit that the data describes an earlier
    # window: the query succeeds, but the number is not current.
    EXPIRED_KEY = {"codex": "c_window_expired"}

    def _data_expired(self, source):
        key = self.EXPIRED_KEY.get(source)
        return bool(key and self.data.get(key))

    def _is_stale(self, source):
        if self._data_expired(source):
            return True
        return (source not in self._verified or source in self.errors or
                time.time() - self._success_at.get(source, 0) > REFRESH_SECONDS + 60)

    def _stale_text(self, source):
        """Label why a source is grey: no data, outdated, or an ended window."""
        if self._data_expired(source):
            return "窗口已过期"
        stamp = self._success_at.get(source)
        return "旧 " + datetime.fromtimestamp(stamp).strftime("%H:%M") if stamp else "等待更新"

    def _load_cache(self):
        try:
            with open(CACHE_FILE, encoding="utf-8") as stream:
                cache = json.load(stream)
            for name, record in cache.get("sources", {}).items():
                try:
                    stamp = float(record["success_at"])
                    if not 0 < stamp <= time.time() + 60:
                        continue
                    data = validate_result(name, record["data"])
                    self.data.update(data)
                    self._success_at[name] = stamp
                except (KeyError, TypeError, ValueError):
                    continue
        except (OSError, ValueError, AttributeError):
            pass

    @staticmethod
    def _source_keys(name):
        return {"kimi": ("k5_", "kw_", "k_plan"),
                "codex": ("c5_", "cw_", "c_plan", "c_window"),
                "glm": ("g5_", "gw_", "g_plan"), "main": ("cr_main",),
                "community": ("cr_resets",), "deepseek": ("ds_",)}[name]

    def _save_cache(self):
        sources = {name: {"success_at": stamp,
                         "data": {key: value for key, value in self.data.items()
                                  if key.startswith(self._source_keys(name))}}
                   for name, stamp in self._success_at.items()}
        atomic_json(CACHE_FILE, {"version": 1, "sources": sources})

    def _on_result(self, name, payload, diagnostics):
        if payload.get("ok"):
            self.data.update(payload["data"])
            self._success_at[name] = time.time()
            self._verified.add(name)
            self.errors.pop(name, None)
            try:
                self._save_cache()
            except OSError:
                self._ui_error = "CacheWriteFailed"
        else:
            self.errors[name] = payload.get("error", "QueryFailed")
        self._diagnostics[name] = diagnostics
        try:
            self._render()
            self._fit()
            self._update_tray()
        except Exception as ex:
            self._ui_error = type(ex).__name__
        self._write_debug()

    def _write_debug(self):
        try:
            atomic_json(DEBUG_FILE, {
                "updated": datetime.now().isoformat(timespec="seconds"), "pid": os.getpid(),
                "data": self.data, "errors": self.errors, "ui_error": self._ui_error,
                "success_at": {name: datetime.fromtimestamp(ts).isoformat(timespec="seconds")
                               for name, ts in self._success_at.items()},
                "queries": self._diagnostics, "status_text": self.status.cget("text"),
                "active": [name for name, state in self.scheduler.states.items() if state["worker"]],
                "tray": {"available": bool(self.tray and self.tray.visible),
                         "title": self.tray.title if self.tray else None}})
        except Exception:
            pass

    def _poll(self):
        """Single GUI-thread timer; no worker ever calls Tk, and errors cannot cancel it."""
        try:
            while not self._commands.empty():
                command = self._commands.get_nowait()
                if command == "quit":
                    self._quit()
                    return
                if command == "show":
                    self.root.deiconify()
                    self.root.lift()
                elif command == "refresh":
                    self.refresh_async()
                elif command == "tray_failed":
                    self._tray_failed = True
                    self.root.deiconify()
            if self.instance and self.instance.requested():
                self.root.deiconify()
                self.root.lift()
            if self._tray_thread and not self._tray_thread.is_alive() and not self._tray_failed:
                self._tray_failed = True
                self.root.deiconify()
            self.scheduler.tick()
            minute = int(time.time() // 60)
            if minute != self._last_render_minute:
                self._last_render_minute = minute
                if self.root.state() != "withdrawn":
                    self._render()
                    self._fit()
                self._update_tray()
        except Exception as ex:
            self._ui_error = type(ex).__name__
            self._write_debug()
        finally:
            if not self._closed:
                # Idle: one cheap check / second, no image allocation, disk or network I/O.
                self.root.after(250 if self.scheduler.active else 1000, self._poll)

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

    def _set_row_visible(self, key, visible):
        """Show/hide a complete quota row without leaving an empty label."""
        widgets = [self.row_labels[key][0], *self.rows[key]]
        for wgt in widgets:
            (wgt.grid if visible else wgt.grid_remove)()

    def _set_amount(self, key, amount, currency, note=""):
        """Render money instead of a percentage (pay-as-you-go balances)."""
        pl, rl = self.rows[key]
        if amount is None:
            pl.config(text="--")
            rl.config(text="")
            return
        symbols = {"CNY": "¥", "USD": "$"}
        text = f"{symbols.get(currency, currency + ' ' if currency else '')}{amount:,.2f}"
        base = THEMES[getattr(self, "theme", "dark")]["FG_TEXT"]
        # Money has no natural percentage, so warn on an absolute threshold.
        limit = CFG.get("deepseek_low_balance") or 0
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            limit = 0.0
        color = base
        if limit > 0 and amount <= limit:
            color = "#d04040" if amount <= limit / 4 else "#d08020"
        pl.config(text=text, fg=color)
        rl.config(text=note)

    def _render_radar(self):
        """Show the selected primary source plus the community signal."""
        win = CFG.get("radar_window", 24)

        main_pct = self.data.get("cr_main48" if win == 48 else "cr_main24")
        self._set_row("cr_main", main_pct, f"主源·{win}h")
        if main_pct is not None:
            color = "#d08020" if main_pct >= 80 else THEMES[self.theme]["FG_DIM"]
            self.rows["cr_main"][0].config(fg=color)

        resets_pct = self.data.get("cr_resets_pct")
        self._set_row("cr_resets", resets_pct, "社区投票")
        if resets_pct is None and self.data.get("cr_resets_mode") == "no_watch":
            self.rows["cr_resets"][1].config(text="暂无投票")
        if resets_pct is not None:
            color = "#d08020" if resets_pct >= 80 else THEMES[self.theme]["FG_DIM"]
            self.rows["cr_resets"][0].config(fg=color)

    def _render(self):
        d = self.data
        # The Kimi usage endpoint may omit membership.level. The local display
        # override and renewal date must still be rendered in that case.
        k_plan = CFG.get("kimi_plan_name") or d.get("k_plan") or ""
        if k_plan or CFG.get("renew_kimi"):
            self.section_titles["Kimi"].config(
                text="Kimi · " + k_plan)
            self.section_renews["Kimi"].config(
                text="续订 " + CFG.get("renew_kimi", ""), fg=KIMI_BLUE_SOFT)
        if d.get("c_plan"):
            c_plan = CFG.get("codex_plan_name") or (
                d["c_plan"] + CFG.get("codex_plan_suffix", ""))
            self.section_titles["Codex"].config(text="Codex · " + c_plan)
            self.section_renews["Codex"].config(
                text="续订 " + CFG.get("renew_codex", ""), fg=CODEX_GREEN_SOFT)
        if d.get("g_plan"):
            g_title = "GLM" + ((" · " + CFG["glm_plan_name"])
                               if CFG.get("glm_plan_name") else "")
            self.section_titles["GLM"].config(text=g_title)
            renew_g = CFG.get("renew_glm", "")
            self.section_renews["GLM"].config(
                text=("续订 " + renew_g) if renew_g and renew_g != "MM-DD" else "",
                fg=GLM_PURPLE_SOFT)
        self._set_row("k5", d.get("k5_pct"), _countdown(d.get("k5_reset")))
        self._set_row("kw", d.get("kw_pct"), _fmt_reset(d.get("kw_reset")))
        # Visibility is a user/menu setting with a plan-aware default. The row
        # intentionally remains visible as "--" when enabled but the API does
        # not expose a 5-hour window yet.
        self._set_row_visible("c5", CFG.get("show_codex", True)
                              and self.show_codex_5h.get())
        self._set_row("c5", d.get("c5_pct"),
                      _countdown(d.get("c5_reset")) if d.get("c5_reset") else "")
        self._set_row("cw", d.get("cw_pct"), _fmt_reset(d.get("cw_reset")))
        self._set_row("g5", d.get("g5_pct"),
                      _countdown(d.get("g5_reset")) if d.get("g5_reset") else "")
        self._set_row("gw", d.get("gw_pct"), _fmt_reset(d.get("gw_reset")))
        # DeepSeek is pay-as-you-go: the card shows money, not a percentage.
        if d.get("ds_plan") or d.get("ds_balance") is not None:
            self.section_titles["DeepSeek"].config(text="DeepSeek")
            self.section_renews["DeepSeek"].config(text="按量付费", fg=DEEPSEEK_SOFT)
        if d.get("ds_balance") is not None:
            self._set_amount("ds", d.get("ds_balance"), d.get("ds_currency") or "",
                             "可用" if d.get("ds_available", True) else "账号不可用")
        self._render_radar()
        enabled = self._enabled_sources()
        for source, keys in {"kimi": ("k5", "kw"), "codex": ("c5", "cw"),
                             "glm": ("g5", "gw"), "main": ("cr_main",),
                             "community": ("cr_resets",),
                             "deepseek": ("ds",)}.items():
            if source in enabled and self._is_stale(source):
                text = self._stale_text(source)
                for key in keys:
                    self.rows[key][1].config(text=text)
                    self.rows[key][0].config(fg=THEMES[self.theme]["FG_DIM"])
        stale = [name for name in enabled if self._is_stale(name)]
        parts = []
        account_times = [self._success_at.get(name) for name in enabled
                         if name in ("kimi", "codex", "glm", "deepseek")]
        if account_times and all(account_times):
            parts.append("额度更新 " + datetime.fromtimestamp(min(account_times)).strftime("%H:%M"))
        if stale:
            labels = {"kimi": "Kimi", "codex": "Codex", "glm": "GLM", "main": "主源",
                      "community": "社区", "deepseek": "DeepSeek"}
            parts.append("待更新:" + "/".join(labels[name] for name in stale))
        if self._tray_failed:
            parts.append("托盘不可用")
        if not parts:
            parts.append("加载中…")
        self.status.config(text="  ".join(parts),
                           fg="#d08080" if stale else FG_DIM)

    def run(self):
        self.root.mainloop()


def query_worker(name):
    if sys.stdin.buffer.readline(16) != b"go\n":
        return
    try:
        fn = {"kimi": fetch_kimi, "codex": fetch_codex, "glm": fetch_glm,
              "deepseek": fetch_deepseek, "main": fetch_main_radar,
              "community": fetch_community_radar}[name]
        data = validate_result(name, fn())
        payload = {"ok": True, "data": data}
    except Exception as ex:
        code = ex.code if isinstance(ex, urllib.error.HTTPError) else None
        payload = {"ok": False, "error": f"HTTP{code}" if code else type(ex).__name__,
                   "retryable": code not in (400, 401, 403, 404) and not isinstance(ex, FileNotFoundError)}
    # Only known public/account quota fields; never exception text, request headers or credentials.
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    if QUERY_MODE:
        query_worker(sys.argv[2])
    else:
        instance = SingleInstance("IanQuotaMonitor-v2")
        app = None
        try:
            if not instance.existing:
                app = App(instance)
                app.run()
        finally:
            if app:
                app.scheduler.close()
            instance.close()
