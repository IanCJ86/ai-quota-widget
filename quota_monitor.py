# -*- coding: utf-8 -*-
# Quota Monitor: Kimi Code + Codex floating widget.
# Reads local credentials only; public radar calls are read-only and credential-free.
# Never prints or logs any token.
import base64
import hashlib
import json
import math
import os
import sys
import queue
import re
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from app_version import APP_VERSION, USER_AGENT
from quota_network import stream as network_stream, error_code, retry_after
from quota_paths import data_locations, resolve_data_dir, migrate_data
from quota_state import (source_status, window_expired, error_label, finite,
                         validate_config, credit_status, refresh_notice, radar_status, merge_radar)
from quota_signals import tariff_status, voucher_fingerprints, observe_vouchers, voucher_colors

# CLI dispatch precedes GUI imports and config/credential access.
if __name__ == '__main__' and sys.argv[1:] and sys.argv[1] != '--query':
    from quota_cli import main
    raise SystemExit(main())
from widget_style import (
    TRANSP_KEY, THEMES, THEME_CHOICES, BG, BG_CARD, FG_DIM, FG_TEXT,
    KIMI_BLUE, CODEX_NEUTRAL, KIMI_BLUE_SOFT, CODEX_NEUTRAL_SOFT,
    GLM_PURPLE, GLM_PURPLE_SOFT, DEEPSEEK_BLUE, DEEPSEEK_SOFT,
    FONT_TITLE, FONT_TEXT, FONT_VALUE, FONT_STATUS, MONEY_PAD,
    TITLE_RESERVE_MAX, TITLE_GAP, TITLE_SLACK,
)

if sys.argv[1:] == ["--version"]:
    print(APP_VERSION)
    raise SystemExit(0)

from monitor_runtime import (Scheduler, SingleInstance, atomic_json, dpapi_protect,
                             dpapi_unprotect, validate_result, QueryHistory)

QUERY_MODE = len(sys.argv) == 3 and sys.argv[1] == "--query"
HEADLESS_MODE = QUERY_MODE or any(arg in sys.argv for arg in
    ('--doctor','--json','--once','--install','--help','--version'))
if not HEADLESS_MODE:
    import tkinter as tk
    from tkinter import font as tkfont
    from widget_settings import SettingsController
    from widget_windows import WindowEffects
    from widget_tray import TrayIcon, CommandInbox
    from widget_themes import ThemePainter
    from widget_viewport import Viewport, work_area, clamp_rect

# crisp rendering on high-DPI displays (declare per-monitor DPI awareness)
try:
    import ctypes
    if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
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
CODEX_HOME = os.environ.get('CODEX_HOME') or os.path.expanduser(r"~\.codex")
CODEX_BIN_DIR = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin")
# Legacy location: the desktop app now keeps versioned runtimes in
# bin\<hash>\codex.exe and can leave an outdated codex.exe here, so this is only
# a fallback (see _find_codex_exe).
CODEX_EXE_CANDIDATES = [
    os.path.join(CODEX_BIN_DIR, "codex.exe"),
]
DEBUG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.txt")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")  # legacy
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-good.json")
# GLM key storage: config.json is plaintext, so the settings menu encrypts the
# key with Windows DPAPI instead (user-scoped, decryptable only on this account).
GLM_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glm-key.dpapi")
GLM_KEY_ENV = "AI_QUOTA_WIDGET_GLM_API_KEY"   # no extra copy in app files
# DeepSeek is pay-as-you-go: its API reports a money balance, not a percentage.
DEEPSEEK_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deepseek-key.dpapi")
DEEPSEEK_KEY_ENV = "AI_QUOTA_WIDGET_DEEPSEEK_API_KEY"
DEEPSEEK_ENV = "DEEPSEEK_API_KEY"             # name used by the official CLI/SDK
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
# API-key balance history; platform-web billing needs separate login authorization.
DEEPSEEK_SPEND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "deepseek-spend.json")
DATA_DIR = resolve_data_dir(os.path.dirname(os.path.abspath(__file__)))
DEBUG_FILE, CONFIG_FILE, SETTINGS_FILE, CACHE_FILE, GLM_KEY_FILE, DEEPSEEK_KEY_FILE, DEEPSEEK_SPEND_FILE = (
    os.path.join(DATA_DIR, name) for name in ('debug.txt','config.json','settings.json','last-good.json',
                                           'glm-key.dpapi','deepseek-key.dpapi','deepseek-spend.json'))

DEFAULT_CONFIG = {
    "network": {},  # per-source system/direct/custom proxy; never changes Windows
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
    "theme": "glass",             # glass / dark / light / steam / fuel / ink
    # ---- visibility toggles (also in the right-click menu) ----
    "show_kimi": True,
    "show_codex": True,
    # None = follow the selected plan: Pro hidden, other plans shown.
    # A boolean is a user's explicit menu override.
    "show_codex_5h": None,
    # Reset vouchers ("full reset" credits) and the daily token row.
    "show_codex_credits": True,
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
    "deepseek_token_metric": "total",
    "harness_sessions_dir": "",
    # Money cannot be a percentage: warn below this amount and alarm below a
    # quarter of it. Set to 0 to switch the colour warning off.
    "deepseek_low_balance": 20.0,
}


CONFIG_ISSUES = []
CONFIG_SAVE_FAILED = False

def _load_config():
    CONFIG_ISSUES.clear()
    cfg = dict(DEFAULT_CONFIG)
    for path in (SETTINGS_FILE, CONFIG_FILE):  # legacy settings.json first, config.json wins
        try:
            with open(path, encoding="utf-8-sig") as stream:
                raw = json.load(stream)
            cfg, issues = validate_config(raw, cfg)
            CONFIG_ISSUES.extend(issues)
        except FileNotFoundError:
            continue
        except Exception:
            CONFIG_ISSUES.append(os.path.basename(path) + ': unreadable/invalid JSON')
    return cfg


def _save_config(cfg):
    global CONFIG_SAVE_FAILED
    try:
        if CONFIG_ISSUES:
            # Keep the original untouched until an explicit settings save.
            import shutil
            if os.path.isfile(CONFIG_FILE):
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + '.invalid-' + str(time.time_ns()) + '.bak')
        atomic_json(CONFIG_FILE, cfg)
        CONFIG_ISSUES.clear()
        CONFIG_SAVE_FAILED = False
        return True
    except Exception:
        CONFIG_SAVE_FAILED = True
        return False


CFG = _load_config()


def prepare_shared_data():
    """GUI owner only: publish shared state before constructing any controllers."""
    global DATA_DIR, DEBUG_FILE, CONFIG_FILE, SETTINGS_FILE, CACHE_FILE
    global GLM_KEY_FILE, DEEPSEEK_KEY_FILE, DEEPSEEK_SPEND_FILE
    target, legacy = data_locations(os.path.dirname(os.path.abspath(__file__)))
    migrate_data(target, legacy)
    DATA_DIR = str(target)
    DEBUG_FILE, CONFIG_FILE, SETTINGS_FILE, CACHE_FILE, GLM_KEY_FILE, DEEPSEEK_KEY_FILE, DEEPSEEK_SPEND_FILE = (
        os.path.join(DATA_DIR, name) for name in ('debug.txt', 'config.json', 'settings.json',
        'last-good.json', 'glm-key.dpapi', 'deepseek-key.dpapi', 'deepseek-spend.json'))
    CFG.clear()
    CFG.update(_load_config())

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
# DeepSeek doubles its prices during weekday peak windows (Beijing time); the
# balance row says which regime the last refresh fell in.
DEEPSEEK_PEAK = "梁文锋 时段"
DEEPSEEK_OFFPEAK = "梁文谷 时段"
BEIJING = timezone(timedelta(hours=8))
# Local DeepSeek Harness transcripts, used for an optional "tokens today" figure.
DSH_SESSIONS = os.path.expanduser(r"~\.dsh\sessions")
# The public reset radar is a third-party signal. It does not expose or replace
# the account-specific Codex quota below.
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


def _fmt_day(iso_or_ts):
    """Format a date, or unix seconds, as MM-DD local."""
    try:
        if isinstance(iso_or_ts, (int, float)):
            dt = datetime.fromtimestamp(iso_or_ts, tz=timezone.utc).astimezone()
        else:
            dt = datetime.fromisoformat(str(iso_or_ts).replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d")
    except Exception:
        return ""


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
                                             headers={"Accept": "application/json", "User-Agent": USER_AGENT})
                with account_request(req, timeout=15) as response:
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
                                 headers={"Authorization": "Bearer " + cred["access_token"],
                                          "User-Agent": USER_AGENT})
    with account_request(req, timeout=15) as response:
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
    """Locate the codex CLI the account actually uses.

    Versioned runtimes live in bin\\<hash>\\codex.exe and the newest one is what
    the desktop app and the CLI itself run; an outdated bin\\codex.exe can be
    left behind for months and its app-server lacks newer methods such as
    account/usage/read or reset credits, so the legacy path is a fallback only.
    """
    try:
        names = os.listdir(CODEX_BIN_DIR) if os.path.isdir(CODEX_BIN_DIR) else []
    except OSError:
        names = []
    runtimes = [os.path.join(CODEX_BIN_DIR, name, "codex.exe") for name in names]
    runtimes = [path for path in runtimes if os.path.exists(path)]
    if runtimes:
        return max(runtimes, key=os.path.getmtime)
    for candidate in CODEX_EXE_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
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

        send(0, "initialize", {"clientInfo": {"name": "quota-monitor", "version": APP_VERSION},
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

    # Reset credits: granted "full reset" vouchers with an expiry.
    credit = (result or {}).get("rateLimitResetCredits") or {}
    try:
        credit_count = int(credit.get("availableCount"))
    except (TypeError, ValueError):
        credit_count = None
    expiries = []
    for item in credit.get("credits") or []:
        if isinstance(item, dict) and item.get("status", "available") == "available":
            expiries.append(item.get("expiresAt"))

    return {
        "c5_pct": five_h["pct"] if five_h else None,
        "c5_reset": five_h["reset"] if five_h else None,
        "cw_pct": weekly["pct"] if weekly else None,
        "cw_reset": weekly["reset"] if weekly else None,
        "c_plan": str(account.get("planType") or rl.get("planType") or "").title(),
        # Any displayed window that already reset makes the snapshot stale; the
        # UI greys it instead of passing it off as the current value.
        "c_window_expired": bool(shown) and any(expired(w) for w in shown),
        "cr_credit_count": credit_count,
        "cr_credit_tokens": voucher_fingerprints(credit.get('credits')),
        "cr_credit_scope": hashlib.sha256(str(account.get('id') or account.get('email') or
                                               CODEX_HOME).encode()).hexdigest(),
        "cr_credit_expiries": [e for e in expiries if finite(e)],
        "cr_credit_expiry": min([e for e in expiries if isinstance(e, (int, float))],
                                default=None),
    }


# ---------------- Codex reset radar ----------------

def account_request(req, timeout=15):
    import io
    return io.BytesIO(network_stream(req, CFG, 'accounts', limit=2*1024*1024, budget=timeout))

def _fetch_public_text(url, accept):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    import codecs
    parser = _RadarParser()
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    size = [0]
    def consume(block):
        size[0] += len(block)
        parser.feed(decoder.decode(block))
        return len(parser.values) == 2 and (parser.updated is not None or size[0] >= 512*1024)
    return network_stream(req, CFG, 'radar', limit=2*1024*1024, budget=20, consume=consume)


class _RadarParser(HTMLParser):
    """Attribute order/quote style must not break the public page adapter."""
    def __init__(self):
        super().__init__()
        self.values = {}
        self.updated = None
        self._text = ''
        self._ignored = 0

    def handle_data(self, data):
        if self._ignored:
            return
        self._text = (self._text + data)[-1024:]
        if 'Data last updated:' not in self._text:
            return
        match = re.search(r'Data last updated:\s*([A-Za-z]{3} \d{1,2}, (?:\d{4} )?\d{1,2}:\d{2} [AP]M UTC)', self._text)
        if match:
            text = match.group(1)
            try:
                has_year = bool(re.search(r', \d{4} ', text))
                parsed = datetime.strptime(text, '%b %d, %Y %I:%M %p UTC' if has_year else '%b %d, %I:%M %p UTC').replace(tzinfo=timezone.utc)
                if not has_year:
                    now = datetime.now(timezone.utc)
                    parsed = parsed.replace(year=now.year)
                    if parsed > now + timedelta(days=1):
                        parsed = parsed.replace(year=now.year-1)
                self.updated = parsed.timestamp()
            except ValueError:
                pass

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._ignored = max(0, self._ignored-1)

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._ignored += 1
        attrs = dict(attrs)
        name = attrs.get("data-testid")
        if name not in ("probability-ring-24h", "probability-ring-48h"):
            return
        try:
            value = int(attrs.get("data-target-value"))
        except (TypeError, ValueError):
            return
        if 0 <= value <= 100:
            self.values[name] = value


def fetch_main_radar():
    html = _fetch_public_text(CODEX_RADAR_URL, "text/html").decode("utf-8", errors="replace")
    parser = _RadarParser()
    parser.feed(html)
    if not parser.values:
        raise ValueError("missing radar probabilities")
    return {
        "cr_main24": parser.values.get("probability-ring-24h"),
        "cr_main48": parser.values.get("probability-ring-48h"),
        "cr_main_updated": parser.updated,
        "cr_main24_at": time.time() if 'probability-ring-24h' in parser.values else None,
        "cr_main48_at": time.time() if 'probability-ring-48h' in parser.values else None,
    }


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
    """Resolve an API key: explicit local override, environment, legacy config.

    config.json is plaintext on disk, so the settings menu writes keys through
    Windows DPAPI and drops the plaintext copy; the legacy field keeps working
    for existing installs.
    """
    stored = _read_protected_key(path)
    if stored:
        return stored
    for name in env_names:
        # An explicitly empty process variable must mask a registry value too
        # (isolated runs / deliberate credential removal), not resurrect it.
        value = (os.environ[name] if name in os.environ else _windows_env(name) or "").strip()
        if value:
            return value
    return (CFG.get(field) or "").strip()


def harness_sessions_dir():
    return os.path.abspath(os.path.expanduser(CFG.get('harness_sessions_dir') or DSH_SESSIONS))


def source_identity(name):
    # Opaque cache namespace, never a key or credential in logs.
    if name == 'deepseek':
        context = deepseek_api_key()
    elif name == 'glm':
        context = glm_api_key() + '\0' + CFG.get('glm_region', 'cn')
    elif name == 'tokens':
        context = harness_sessions_dir()
    else:
        return None
    return hashlib.sha256(context.encode('utf-8')).hexdigest()


def available_sources():
    from quota_cli import configured
    flags = dict(configured(sys.modules[__name__]))
    flags['main'] = bool(CFG.get('show_radar')) and bool(CFG.get('show_codex'))
    flags['tokens'] = (CFG.get('deepseek_token_metric') != 'off'
                       and os.path.isdir(harness_sessions_dir()))
    return flags


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
    return _clear_plaintext_key(field)


def _clear_plaintext_key(field):
    candidate = dict(CFG, **{field: ""})
    if not _save_config(candidate):
        return False
    CFG[field] = ""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as stream:
            legacy = json.load(stream)
        if not isinstance(legacy, dict):
            return False
        if legacy.get(field):
            legacy[field] = ""
            atomic_json(SETTINGS_FILE, legacy)
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return False
    return True


def clear_provider_key(path, field):
    """Delete every stored copy: the encrypted file and the legacy field."""
    if not _clear_plaintext_key(field):
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


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
        "User-Agent": USER_AGENT,
        "Authorization": key,
        "Accept-Language": "zh-CN,zh",
        "Content-Type": "application/json",
    })
    with account_request(req, timeout=15) as response:
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

def deepseek_spend(balance, today=None, scope=None):
    # GUI and explicit --fresh CLI may run together. Serialize read/modify/write.
    import msvcrt
    with open(DEEPSEEK_SPEND_FILE + '.lock', 'a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            return _deepseek_spend(balance, today, scope)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _deepseek_spend(balance, today=None, scope=None):
    """Estimate today's spend from the API-key balance endpoint.
    The first reading of a day becomes the baseline; a top-up raises
    the baseline instead of producing negative spend. Returns the amount spent
    so far today (0.0 when nothing has been observed yet)."""
    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or not math.isfinite(balance) or balance < 0:
        raise ValueError("invalid balance")
    today = today or date.today().isoformat()
    state = {}
    try:
        with open(DEEPSEEK_SPEND_FILE, encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError:
        state = {}
    if not isinstance(state, dict):
        raise ValueError('invalid spend history')
    opened = state.get("open")
    if state and (not finite(opened) or opened < 0 or not finite(state.get('last')) or state['last'] < 0):
        raise ValueError('invalid spend history')
    if (state.get("day") != today or (scope is not None and state.get('scope') != scope) or isinstance(opened, bool)
            or not isinstance(opened, (int, float)) or not math.isfinite(opened)):
        state = {"version": 2, "day": today, "open": balance, "last": balance,
                 'scope': scope, 'started': datetime.now().isoformat(timespec='seconds')}
    else:
        previous = state.get("last")
        if isinstance(previous, (int, float)) and not isinstance(previous, bool) and math.isfinite(previous):
            delta = previous - balance
            if delta < 0:
                state["open"] = round(state["open"] - delta, 8)  # top-up
            state["last"] = balance
    state["updated"] = datetime.now().isoformat(timespec="seconds")
    atomic_json(DEEPSEEK_SPEND_FILE, state)
    return round(max(0.0, state["open"] - balance), 8)


def local_harness_tokens(day=None, root=None, strict=False):
    """Independent optional worker: bounded streaming, metadata-only cache."""
    from harness_stats import totals
    cache = None if root is not None else os.path.join(os.path.dirname(CONFIG_FILE),
                                                       "harness-totals.json")
    return totals(root or harness_sessions_dir(), day, cache, strict=strict)


# Offline calendar: State Council's 2026 public holiday schedule. Weekends stay
# off-peak even on make-up working days: the provider explicitly says Mon-Fri.
# https://www.beijing.gov.cn/fuwu/bmfw/sy/jrts/202511/t20251104_4258838.html
DEEPSEEK_HOLIDAYS = {
    2026: frozenset(date(2026, month, day)
                    for month, first, last in ((1, 1, 3), (2, 15, 23), (4, 4, 6),
                                               (5, 1, 5), (6, 19, 21),
                                               (9, 25, 27), (10, 1, 7))
                    for day in range(first, last + 1)),
}


def deepseek_peak_label(when=None):
    """梁文峰 during DeepSeek's double-price windows, 梁文谷 otherwise.

    Peak is Beijing Mon-Fri 09:00-12:00 and 14:00-18:00, excluding holidays.
    Outside known calendar years, potential peak hours have no label rather
    than inventing a holiday policy; known off-peak hours remain unambiguous.
    """
    if when is None:
        when = datetime.now(timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(BEIJING)
    minutes = local.hour * 60 + local.minute
    peak = local.weekday() < 5 and (9 * 60 <= minutes < 12 * 60
                                    or 14 * 60 <= minutes < 18 * 60)
    if peak:
        holidays = DEEPSEEK_HOLIDAYS.get(local.year)
        if holidays is None:
            return ""
        peak = local.date() not in holidays
    return DEEPSEEK_PEAK if peak else DEEPSEEK_OFFPEAK


TRAY_CHOICES = {
    "kimi": [("k5_pct", "Kimi 每5小时"), ("kw_pct", "Kimi 每周")],
    "codex": [("c5_pct", "Codex 每5小时"), ("cw_pct", "Codex 每周")],
    "glm": [("g5_pct", "GLM 每5小时"), ("gw_pct", "GLM 每周")],
    "deepseek": [("ds_spend", "DeepSeek 今日估算金额（四舍五入）")],
}
TRAY_DEFAULT = {"kimi": "kw_pct", "codex": "cw_pct", "glm": "gw_pct", "deepseek": "ds_spend"}

def clamp_position(x, y, w, h, screen_w, screen_h):
    """Where to put the window given a remembered position, or None.

    A remembered spot can end up off-screen after a monitor change, so it is only
    reused when a useful part of the window would still be visible; the result is
    then pulled inside the working area the way _fit does."""
    if x is None or y is None:
        return None
    if min(x + w, screen_w) - max(x, 0) < 40:
        return None
    if min(y + h, screen_h) - max(y, 0) < 40:
        return None
    return (min(max(x, 0), max(screen_w - w - 8, 0)),
            min(max(y, 0), max(screen_h - h - 48, 0)))


def _fmt_tokens(value):
    """Compact token counts: 75682437 -> "75.7M", 1181266882 -> "1.2B"."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:          # NaN or nonsense
        return None
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if number >= limit:
            scaled = number / limit
            if scaled >= 100:
                return "%d%s" % (round(scaled), suffix)
            return "%.1f%s" % (scaled, suffix)
    return "%d" % round(number)


def fetch_deepseek():
    """DeepSeek API balance. There is no percentage quota and no public usage
    endpoint; `/user/balance` returns money, so the card shows money."""
    key = deepseek_api_key()
    if not key:
        return {}
    req = urllib.request.Request(DEEPSEEK_BALANCE_URL, headers={
        "User-Agent": USER_AGENT,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    })
    with account_request(req, timeout=15) as response:
        d = json.load(response)
    infos = [x for x in (d.get("balance_infos") or []) if isinstance(x, dict)]
    if not infos:
        raise ValueError("no balance info")
    # Prefer CNY when the account reports several currencies.
    info = next((x for x in infos if str(x.get("currency") or "").upper() == "CNY"),
                infos[0])

    def amount(field):
        value = info.get(field, 0 if field != "total_balance" else None)
        if isinstance(value, bool) or value is None:
            raise ValueError("invalid balance field")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid balance field")
        return round(value, 8)

    balance = amount("total_balance")
    result = {
        "ds_balance": balance,
        "ds_granted": amount("granted_balance"),
        "ds_topped_up": amount("topped_up_balance"),
        "ds_currency": str(info.get("currency") or "").upper()[:8],
        "ds_available": bool(d.get("is_available")),
        "ds_plan": "按量付费",
    }
    validate_result("deepseek", result)
    scope = hashlib.sha256((key + '\0' + result['ds_currency']).encode()).hexdigest()
    try:
        result["ds_spend"] = deepseek_spend(balance, scope=scope)
    except (OSError, ValueError, TypeError, OverflowError):
        result['ds_spend'] = None
        result['ds_spend_error'] = 'SpendWriteFailed'
    result["ds_spend_day"] = date.today().isoformat()
    return result


def fetch_tokens():
    day = date.today()
    tokens = local_harness_tokens(day, strict=True)
    if tokens is None:
        raise FileNotFoundError("local usage unavailable")
    return {"ds_tokens_total": tokens["total"], "ds_tokens_fresh": tokens["fresh"],
            "ds_tokens_day": day.isoformat()}


# ---------------- UI ----------------

class App:
    def __init__(self, instance=None):
        self._first_run = bool(getattr(sys, 'frozen', False) and not os.path.isfile(CONFIG_FILE))
        if self._first_run:
            from quota_cli import configured
            for name, ready in configured(sys.modules[__name__]).items():
                CFG['show_'+name] = ready
        self.root = tk.Tk()
        # Hide it before anything else: wm overrideredirect() maps the window as
        # a side effect, and Windows paints it at its default position first, so
        # setting it up before withdrawing produced a brief flash in the top-left
        # corner.  Withdrawn first, nothing is ever painted until deiconify().
        self.root.withdraw()
        self.effects = WindowEffects(self.root)
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        self.root.title("Quota")
        # Size and position are set before the window can be shown, so even a
        # stray map lands where the widget belongs.
        w, h = 232, 212
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        try:
            point = (int(CFG.get('window_x', sw-w-40)), int(CFG.get('window_y', sh-h-90)))
            remembered = clamp_rect(*point, w, h, work_area(self.root, point))[-2:]
        except (TypeError, ValueError):
            remembered = None
        self._pos = remembered or (sw - w - 40, sh - h - 90)
        self._geom = None       # last geometry applied by _fit(), to avoid churn
        self.root.geometry("%dx%d+%d+%d" % (w, h, self._pos[0], self._pos[1]))
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Transparency and position are remembered between runs.
        try:
            self.alpha_val = max(40, min(100, int(CFG.get("window_alpha", 94))))
        except (TypeError, ValueError):
            self.alpha_val = 94
        self.root.attributes("-alpha", self.alpha_val / 100)
        self.root.configure(bg=BG)
        self.topmost = tk.BooleanVar(value=True)
        self.data = {}
        self._radar_trends = {}
        self._credit_observation = {}
        self._source_identities = {name: source_identity(name) for name in ('glm','deepseek','tokens')}
        self.errors = {}
        self.last_ok = None
        self.instance = instance
        self._closed = False
        self._commands = CommandInbox()
        self._commands.attach(self.root, lambda: self._poll_commands(reschedule=False))
        self._verified = set()
        self._success_at = {}
        self._diagnostics = {}
        self._ui_error = None
        self._last_render_minute = None
        self.tray_controller = TrayIcon(self._commands)
        self._last_tray_state = None
        self.history = QueryHistory(os.path.join(os.path.dirname(DEBUG_FILE), 'query-history.json'))
        self.scheduler = Scheduler(os.path.abspath(__file__), self._on_result, REFRESH_SECONDS,
                                   on_event=self.history.record)
        self._load_cache()
        self._drag = None
        self.theme = "dark"
        self._cards = []
        self._name_labels = []
        self.viewport = Viewport(self.root)
        self.content = self.viewport.body

        self.theme_painter = ThemePainter(self)
        self.rows = {}  # key -> (pct_label, reset_label)
        self.row_labels = {}
        self.section_titles = {}
        self.section_renews = {}
        self._title_text = {}       # full title text, before any ellipsis
        # Height of a card's header row, measured from the title font. The row
        # is given this height explicitly (see _section) so the header labels
        # cannot influence the card's column widths.
        self._head_height = tkfont.Font(font=FONT_TITLE).metrics("linespace") + 4
        self._section(1, "Kimi", KIMI_BLUE, [("k5", "每5小时"), ("kw", "每周")])
        self._divider = tk.Frame(self.content, bg="#3a3a4e", height=1)
        self._divider.grid(row=2, column=0, sticky="ew", padx=10, pady=1)
        self._section(3, "GLM", GLM_PURPLE, [("g5", "每5小时"), ("gw", "每周")])
        self._divider2 = tk.Frame(self.content, bg="#3a3a4e", height=1)
        self._divider2.grid(row=4, column=0, sticky="ew", padx=10, pady=1)
        self._section(5, "Codex", CODEX_NEUTRAL,
                      [("c5", "每5小时"), ("cw", "每周"),
                       ("cr_credit", "重置券"), ("cr_main", "Tibo雷达")])
        self._divider3 = tk.Frame(self.content, bg="#3a3a4e", height=1)
        self._divider3.grid(row=6, column=0, sticky="ew", padx=10, pady=1)
        # DeepSeek is pay-as-you-go, so this card shows a money balance.
        self._section(7, "DeepSeek", DEEPSEEK_BLUE,
                      [("ds", "账号余额"), ("ds_spend", "今日估算")])
        self._dividers = [self._divider, self._divider2, self._divider3]

        bar = tk.Frame(self.root, bg=BG)
        bar.grid(row=2, column=0, sticky="ew", padx=(19, 12), pady=(3, 2))
        self.status = tk.Label(bar, text="初始化…", fg=FG_DIM, bg=BG,
                               font=FONT_STATUS, anchor="w")
        self.status.pack(side="left")
        self.close_btn = tk.Label(bar, text="✕", fg=FG_DIM, bg=BG, cursor="hand2",
                                  font=FONT_STATUS)
        self.close_btn.pack(side="right")
        self.close_btn._no_drag = True
        self.close_btn.bind("<Button-1>", lambda e: self._minimize_to_tray())
        self._alpha_btns = []
        for sym, d in (("－", -3), ("＋", 3)):
            b = tk.Label(bar, text=sym, fg=FG_DIM, bg=BG, cursor="hand2",
                         font=FONT_STATUS)
            b.pack(side="right", padx=1)
            b._no_drag = True
            b.bind("<Button-1>", lambda e, dd=d: self._alpha_step(dd))
            self._alpha_btns.append(b)
        # A little breathing room under the refresh line; the bar's own pady
        # plus this should end up close to the top margin so the frame looks
        # evenly padded.
        sp2 = tk.Frame(self.root, bg=BG, height=3)
        sp2.grid(row=3, column=0)
        self.root.grid_columnconfigure(0, weight=1)

        for wgt in self.root.winfo_children():
            self._bind(wgt)
        self._bind(self.root)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.settings = SettingsController(self, CFG, _save_config, {
            "glm": ("GLM API Key", save_glm_key, clear_glm_key),
            "deepseek": ("DeepSeek API Key", save_deepseek_key, clear_deepseek_key),
        })
        self._st = CFG
        self.menu.add_checkbutton(label="置顶", variable=self.topmost,
                                command=self._toggle_top)
        self.lock_position = tk.BooleanVar(value=CFG.get("lock_position", False))
        self.menu.add_checkbutton(label="锁定位置（拖动不移动）",
                                  variable=self.lock_position,
                                  command=self._toggle_lock_position)
        self.menu.add_command(label="立即刷新", command=self.refresh_async)
        self.menu.add_command(label="快速设置…", command=self._setup_sources)
        self.menu.add_command(label="网络设置…", command=self._network_settings)
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
        self.menu.add_checkbutton(label="Tibo雷达（第三方站点）", variable=self.show_radar,
                                command=self._apply_visibility)
        self._radar_var = tk.StringVar(value=str(self._st.get("radar_window", 24)))
        rw = tk.Menu(self.menu, tearoff=0)
        for label, val in (("24小时内", "24"), ("48小时内", "48")):
            rw.add_radiobutton(label=label, variable=self._radar_var, value=val,
                               command=lambda v=val: self._set_radar_window(int(v)))
        self.menu.add_cascade(label="Tibo雷达窗口", menu=rw)
        self._tray_var = tk.StringVar(value=CFG.get("tray_metric", "cw_pct"))
        self.tray_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="托盘显示", menu=self.tray_menu)
        self.menu.add_separator()
        self.menu.add_cascade(label="Kimi Coding Plan 设置",
                              menu=self.settings._build_provider_menu("kimi"))
        self.menu.add_cascade(label="GLM Coding Plan 设置",
                              menu=self.settings._build_provider_menu("glm"))
        self.menu.add_cascade(label="Codex 设置",
                              menu=self.settings._build_provider_menu("codex"))
        self.menu.add_cascade(label="DeepSeek 设置",
                              menu=self.settings._build_deepseek_menu())
        self.menu.add_separator()
        self._theme_var = tk.StringVar(value=self.theme)
        tm = tk.Menu(self.menu, tearoff=0)
        for label, name in THEME_CHOICES:
            tm.add_radiobutton(label=label, variable=self._theme_var, value=name,
                               command=lambda n=name: self._set_theme(n))
        self.menu.add_cascade(label="主题", menu=tm)
        self.menu.add_separator()
        self.menu.add_command(label=f"版本 {APP_VERSION}", state="disabled")
        from quota_update import UpdateController
        self.updater = UpdateController(self, os.path.dirname(CONFIG_FILE), CFG)
        self.menu.add_command(label="检查更新", command=self.updater.request)
        self.updater.menu_index = self.menu.index('end')
        self.menu.add_command(label='复制脱敏诊断', command=self._copy_diagnostics)
        self.menu.add_command(label="退出", command=self._quit)

        self._apply_visibility(persist=False)
        self._set_theme(CFG.get("theme", DEFAULT_CONFIG["theme"]))
        self._init_tray()
        self._fix_tray_metric(persist=False)
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self._fit()                      # size it up before it becomes visible
        self.root.deiconify()
        self._redraw()                   # fresh surface, never a stale one
        self.refresh_async()
        self._write_debug()  # startup evidence also exists when no source is configured
        self.root.after(100, self._poll)
        self.root.after(1000, self._poll_commands)
        if self._first_run:
            self.root.after(200, self._setup_sources)

    def _setup_sources(self):
        from widget_onboarding import show_setup
        from quota_cli import configured
        show_setup(self, CFG, _save_config, lambda: configured(sys.modules[__name__]))

    def _sync_columns(self):
        """Give every card the same three columns, each only as wide as needed.

        Labels and values are laid out at their natural width and the column
        widths are the largest of those plus the cell padding, so the cards line
        up with each other without the slack the old fixed widths used to
        leave."""
        # Padding must be part of the minimum, or a card whose content is wider
        # than the minimum grows a few pixels and stops matching its neighbours.
        label_w = max([lbl.winfo_reqwidth() for lbl in self._name_labels] or [0]) + 7
        value_w = max([pl.winfo_reqwidth() for pl, _ in self.rows.values()] or [0]) + 4
        # A title shares its row with the renewal date, which has to sit exactly
        # at the notes column's x so it lines up with the notes underneath. A
        # title may use everything left of it, i.e. label_w + value_w + 1 pixels
        # (the card border and cell paddings account for the rest), so reserve
        # whatever the widest title is missing - capped, so an absurd plan name
        # is shortened instead of widening every card.
        title_font = tkfont.Font(font=self.section_titles['DeepSeek'].cget('font'))
        widest = max([title_font.measure(self._title_text.get(name, lbl.cget("text")))
                      for name, lbl in self.section_titles.items()] or [0])
        room = label_w + value_w + 1
        value_w += min(max(widest + TITLE_GAP + TITLE_SLACK - room, 0),
                       TITLE_RESERVE_MAX)
        room = label_w + value_w + 1
        notes_x = room + 8                           # notes label's own x
        for card in self._cards:
            card.grid_columnconfigure(0, minsize=label_w)
            card.grid_columnconfigure(1, minsize=value_w)
        # Placed header labels do not participate in Tk's requested size.
        # Reserve the notes column even before the first query has returned.
        for name, card in zip(self.section_titles, self._cards):
            card.grid_columnconfigure(2, minsize=self.section_renews[name].winfo_reqwidth()+12)
            height = max(self.section_titles[name].winfo_reqheight(), self.section_renews[name].winfo_reqheight()+1)
            card.winfo_children()[0].configure(height=height)
            self.section_titles[name].master.place_configure(height=height)
        for name, lbl in self.section_titles.items():
            renew = self.section_renews.get(name)
            if renew is None:
                continue
            head_x = renew.master.winfo_x() or 7     # header's own x inside card
            renew.place_configure(x=max(notes_x - head_x, 0), y=1)
            full = self._title_text.get(name, lbl.cget("text"))
            lbl.configure(text=self._ellipsize(title_font, full,
                                               max(room - TITLE_GAP, 60)))

    @staticmethod
    def _ellipsize(font, text, limit):
        """Shorten text with an ellipsis so it draws within limit pixels."""
        if font.measure(text) <= limit:
            return text
        trimmed = text
        while trimmed and font.measure(trimmed + "…") > limit:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else "…"

    def _set_title(self, name, text):
        """Card titles remember their full text so _sync_columns can trim them."""
        self._title_text[name] = text
        self.section_titles[name].configure(text=text)

    def _fit(self):
        """Resize window to fit content, clamped fully on-screen."""
        if self._drag:
            return          # never fight a drag in progress with a resize
        self.root.update_idletasks()
        self._sync_columns()
        self.root.update_idletasks()
        area = work_area(self.root)
        self.viewport.fit(area)
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 6
        h = self.root.winfo_reqheight() + 6
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # While hidden in the tray the window manager reports a placeholder
        # position, so keep the spot we last knew about instead of moving it.
        if self.root.winfo_viewable():
            self._pos = (self.root.winfo_x(), self.root.winfo_y())
        x, y = self._pos
        w, h, x, y = clamp_rect(x, y, w, h, area)
        # Avoid needless geometry/region churn. This is redraw hardening, not
        # proof that a screenshot of another window is a compositor artifact.
        target = (w, h, x, y)
        if target != self._geom:
            resized = self._geom is None or target[:2] != self._geom[:2]
            self.root.geometry("%dx%d+%d+%d" % target)
            self.root.update_idletasks()  # apply pending size before reading HWND dimensions
            if resized:
                self._round_corners()
            self._redraw()
            self._geom = target

    def _redraw(self):
        return self.effects._redraw()

    def _round_corners(self, radius=8):
        return self.effects._round_corners(radius)

    def _quit(self):
        if self._closed:
            return
        self._closed = True
        if hasattr(self, 'updater'):
            self.updater.cancel.set()
        self._commands.close()
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
            self.tray_controller.stop()
        except Exception:
            pass
        self.root.destroy()

    def _minimize_to_tray(self):
        """Close button hides the main window; tray menu remains available."""
        if self.tray_controller.available:
            self.root.withdraw()
        else:
            self.status.config(text="托盘不可用，窗口已保留")

    def _init_tray(self):
        self.tray_controller.start()

    def _visible_tray_choices(self):
        """Tray metrics offered for the cards that are currently switched on."""
        choices = []
        for card in self.CARD_ORDER:
            shown = getattr(self, "show_" + card, None)
            if card in TRAY_CHOICES and shown is not None and shown.get():
                choices.extend(TRAY_CHOICES[card])
        return choices

    def _rebuild_tray_menu(self):
        self.tray_menu.delete(0, "end")
        choices = self._visible_tray_choices()
        if not choices:
            self.tray_menu.add_command(label="（未显示可用账户）", state="disabled")
            return
        for metric, label in choices:
            self.tray_menu.add_radiobutton(label=label, value=metric,
                                           variable=self._tray_var,
                                           command=self._set_tray_metric)

    def _set_tray_metric(self):
        CFG["tray_metric"] = self._tray_var.get()
        _save_config(CFG)
        self._update_tray()

    def _fix_tray_metric(self, persist=True):
        """Keep the tray pointing at a card that is actually being queried."""
        choices = dict(self._visible_tray_choices())
        current = CFG.get("tray_metric", "cw_pct")
        if choices and current not in choices:
            first = next(iter(choices))
            for card in self.CARD_ORDER:
                shown = getattr(self, "show_" + card, None)
                if card in TRAY_DEFAULT and shown is not None and shown.get():
                    first = TRAY_DEFAULT[card]
                    break
            CFG["tray_metric"] = first
            self._tray_var.set(first)
            if persist:
                _save_config(CFG)
        self._rebuild_tray_menu()
        self._update_tray()

    def _update_tray(self):
        if self.tray_controller.icon is None or self._closed:
            return
        if not self._visible_tray_choices():
            if self.tray_controller.last_value != ('no_percentage',):
                self.tray_controller.icon.icon = self.tray_controller.image(None)
                self.tray_controller.last_value = ('no_percentage',)
            self.tray_controller.icon.title = 'AI 额度监控 · 点击打开'
            return
        metric = CFG.get("tray_metric", "cw_pct")
        value = self.data.get(metric)
        amount = metric == 'ds_spend'
        source = 'deepseek' if amount else "codex" if metric.startswith("c") else "kimi" if metric.startswith("k") else "glm"
        stale = self._transport_stale(source) or (not amount and self._window_expired(metric.split("_")[0]))
        if amount and (self.data.get('ds_spend_day') != date.today().isoformat()
                       or self.data.get('ds_spend_error') or not finite(value) or value < 0):
            value, stale = None, True
        key = (metric, value, stale)
        if key != self.tray_controller.last_value:
            self.tray_controller.icon.icon = self.tray_controller.image(value, stale, amount=amount)
            self.tray_controller.last_value = key
        shown = "--" if value is None else f"{value:.2f} {self.data.get('ds_currency','')}" if amount else f"{int(value)}%"
        stamp = self._success_at.get(source)
        when = datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M") if stamp else "尚无成功数据"
        period = '今日估算（非账单）' if amount else '每周' if 'w_' in metric else '5小时'
        provider = 'DeepSeek' if amount else source.title()
        title = f"{provider} {period} {shown} | {'旧数据' if stale else '更新'} {when}"
        if self.tray_controller.icon.title != title:
            self.tray_controller.icon.title = title

    def _alpha_step(self, delta):
        self.alpha_val = max(40, min(100, self.alpha_val + delta))
        self.root.attributes("-alpha", self.alpha_val / 100)
        if CFG.get("window_alpha") != self.alpha_val:
            CFG["window_alpha"] = self.alpha_val
            _save_config(CFG)

    def _set_radar_window(self, hours):
        CFG["radar_window"] = hours
        _save_config(CFG)
        self._render()

    def _codex_5h_default_visible(self):
        """Plan default: Pro has no 5-hour window; other plans do."""
        plan = (self.settings._current_plan("codex") or "").strip().lower()
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
            self._sync_credentials()
        if hasattr(self, "tray_menu"):
            self._fix_tray_metric(persist=persist)  # no startup config rewrite
        c5_visible = visible["codex"] and self.show_codex_5h.get()
        self._set_row_visible("c5", c5_visible)
        for key in ("cr_main",):
            if key in self.rows:
                widgets = [self.row_labels[key][0], *self.rows[key]]
                for wgt in widgets:
                    (wgt.grid if (visible["codex"] and CFG["show_radar"])
                     else wgt.grid_remove)()
        self._fit()

    def _apply_acrylic(self, on):
        return self.effects._apply_acrylic(on)

    def _set_theme(self, name):
        if name not in THEMES:
            name = DEFAULT_CONFIG["theme"]
        leaving_glass = getattr(self, "theme", "dark") == "glass" and name != "glass"
        # A colour key makes every background pixel mouse-transparent on
        # Windows, including the spaces between footer buttons. Never use it.
        self.root.attributes("-transparentcolor", "")
        if name == "glass" or leaving_glass:
            try:
                self.root.attributes("-transparentcolor", "")
            except Exception:
                pass
            self._apply_acrylic(False)
            self._acrylic_on = False
        # Native acrylic + Tk/GDI + layered alpha can wash colored glyphs out
        # on some Windows compositors. Keep the glass palette/alpha but never
        # enable this second compositor. No color-key / click-through fallback.
        self.theme = name
        if hasattr(self, "_theme_var"):
            self._theme_var.set(name)
        if CFG.get("theme") != name:
            CFG["theme"] = name
            _save_config(CFG)
        self.theme_painter.apply(THEMES[name])
        self._render()
        self._fit()

    def _paint_backgrounds(self, palette):
        """Inherit the containing card/root surface, including new nested widgets.

        Only separators and card borders need explicit roles. Dialogs and menus
        own their styling; do not mutate their widgets during a theme switch.
        """
        def visit(widget, background):
            if isinstance(widget, (tk.Toplevel, tk.Menu)):
                return
            if widget in self._cards:
                background = palette["BG_CARD"]
                widget.configure(highlightbackground=palette["BORDER"])
            if widget in self._dividers:
                widget.configure(bg=palette["BORDER"])
                return
            if widget is self.root or isinstance(widget, (tk.Frame, tk.Label, tk.Canvas)):
                widget.configure(bg=background)
            for child in widget.winfo_children():
                visit(child, background)
        visit(self.root, palette["BG"])

    def _section(self, row, title, color, lines):
        f = tk.Frame(self.content, bg=BG_CARD,
                     highlightbackground="#33334a", highlightthickness=1)
        f.grid(row=row, column=0, sticky="ew", padx=12,
               pady=(8, 0) if row == 1 else (4, 0))
        self._cards.append(f)
        # Column widths are equalised across cards in _sync_columns(); nothing is
        # fixed here, so each column is only as wide as its content needs.
        # Title and renewal share their own full-width row. The title is packed
        # left and the renewal is placed at the third column's x (set in
        # _sync_columns), so the renewal lines up with the notes below it and
        # the two can never overlap. The row is placed, with a spacer keeping
        # its height in the grid, so the header cannot influence the columns.
        spacer = tk.Frame(f, bg=BG_CARD, height=self._head_height)
        spacer.grid(row=0, column=0, columnspan=3, pady=(3, 0))
        head = tk.Frame(f, bg=BG_CARD)
        head.place(x=7, y=3, relwidth=1, width=-10, height=self._head_height)
        title_lbl = tk.Label(head, text=title, fg=color, bg=BG_CARD,
                             font=FONT_TITLE, anchor="w")
        title_lbl.pack(side="left")
        renew_lbl = tk.Label(head, text="", bg=BG_CARD, anchor="w",
                             font=FONT_TEXT)
        renew_lbl.place(x=0, y=1)
        self.section_titles[title] = title_lbl
        self.section_renews[title] = renew_lbl
        for i, line in enumerate(lines, start=1):
            key, name = line[0], line[1]
            nl = tk.Label(f, text=name, fg=FG_DIM, bg=BG_CARD,
                          font=FONT_TEXT, anchor="w")
            nl.grid(row=i, column=0, sticky="w", padx=(7, 0))
            self._name_labels.append(nl)
            self.row_labels[key] = (nl,)
            # One shared, left-aligned numeric column for every card.
            pct = tk.Label(f, text="…", fg=FG_TEXT, bg=BG_CARD,
                           font=FONT_VALUE, anchor="w")
            pct.grid(row=i, column=1, sticky="w", padx=(4, 0))
            rst = tk.Label(f, text="", fg=FG_DIM, bg=BG_CARD,
                           font=FONT_TEXT, anchor="w")
            rst.grid(row=i, column=2, sticky="w", padx=(8, 3),
                     pady=(0, 3 if i == len(lines) else 0))
            self.rows[key] = (pct, rst)

    def _bind(self, wgt):
        if getattr(wgt, "_no_drag", False):
            return
        wgt.bind("<ButtonPress-1>", self._drag_start)
        wgt.bind("<B1-Motion>", self._drag_move)
        wgt.bind("<ButtonRelease-1>", self._drag_end)
        wgt.bind("<Double-Button-1>", lambda e: self.refresh_async())
        wgt.bind("<Button-3>", self._menu)
        for child in wgt.winfo_children():
            self._bind(child)

    def _drag_start(self, e):
        # Toplevel bindtags also receive child events, even when _bind skipped
        # that child. Scrollbars and action buttons must never start a drag.
        if getattr(getattr(e,'widget',None),'_no_drag',False):
            return
        if not self.lock_position.get():
            self._drag = (e.x, e.y)
            # A translucent, borderless, always-on-top window tears while being
            # dragged (Windows repaints it piecemeal), which reads as the same
            # panel flickering across the screen.  Go opaque for the drag.
            if self.alpha_val < 100:
                self.root.attributes("-alpha", 1.0)

    def _drag_move(self, e):
        if self._drag and not self.lock_position.get():
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, _event=None):
        """Remember where the window was dropped, so it reopens there."""
        if not self._drag:
            return
        self._drag = None
        self.root.attributes("-alpha", self.alpha_val / 100)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self._pos = (x, y)
        if CFG.get("window_x") != x or CFG.get("window_y") != y:
            CFG["window_x"], CFG["window_y"] = x, y
            _save_config(CFG)

    def _toggle_lock_position(self):
        self._drag_end()
        CFG["lock_position"] = self.lock_position.get()
        _save_config(CFG)
        self._render()

    def _menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass  # The Exit command has already destroyed the interpreter.
        # Labels and their toplevel both have this binding. Do not open a
        # second native popup when the same right-click bubbles to the root.
        return "break"

    def _toggle_top(self):
        self.root.attributes("-topmost", self.topmost.get())

    def refresh_async(self):
        if self._closed:
            return
        self._sync_credentials()
        self.scheduler.configure(self._enabled_sources())
        self.scheduler.refresh()
        self.scheduler.tick()
        if self.root.state() != 'withdrawn':
            self._render()
            self._fit()
        self._write_debug()

    def _enabled_sources(self):
        """Only query what the window is actually showing.

        A hidden card costs nothing: no worker process, no API call, no third
        party request.  The tray icon can only show a source that is queried, so
        it follows the visible cards too (see _fix_tray_metric)."""
        flags = available_sources()
        names = []
        if CFG.get("show_codex", True) and flags['codex']:
            names.append("codex")
        if CFG.get("show_kimi", True) and flags['kimi']:
            names.append("kimi")
        if CFG.get("show_codex", True) and CFG.get("show_radar", True):
            names.append("main")
        if CFG.get("show_glm") and flags['glm']:
            names.append("glm")
        if CFG.get("show_deepseek", True):
            if flags['deepseek']:
                names.append('deepseek')
            if flags['tokens']:
                names.append("tokens")
        return names

    def _sync_credentials(self):
        for name in ('glm','deepseek','tokens'):
            identity = source_identity(name)
            if self._source_identities.get(name) == identity:
                continue
            self._source_identities[name] = identity
            if hasattr(self, 'scheduler'):
                self.scheduler.configure([n for n in self.scheduler.states if n != name])
            self.data = {k:v for k,v in self.data.items() if not k.startswith(self._source_keys(name))}
            self._success_at.pop(name, None)
            self._verified.discard(name)
            self.errors.pop(name, None)
        if hasattr(self, 'scheduler'):
            self.scheduler.configure(self._enabled_sources())

    # Sources whose payload can admit that the data describes an earlier
    # window: the query succeeds, but the number is not current.
    EXPIRED_KEY = {"codex": "c_window_expired"}

    def _data_expired(self, source):
        if source in ('kimi','glm'):
            return any(self._window_expired(k) for k in (('k5','kw') if source == 'kimi' else ('g5','gw')))
        if source == "codex":
            keys = ["cw"] + (["c5"] if self.show_codex_5h.get() else [])
            known = [self.data.get(k + "_reset") for k in keys]
            if any(isinstance(v, (int, float)) for v in known):
                return any(self._window_expired(k) for k in keys)
        key = self.EXPIRED_KEY.get(source)
        return bool(key and self.data.get(key))

    def _window_expired(self, key):
        return window_expired(self.data, key)

    def _transport_stale(self, source):
        if source == 'main':
            return radar_status(self.data, CFG.get('radar_window', 24),
                                source in self._verified, self.errors.get(source))['stale']
        return source_status(self.data, self._success_at.get(source, 0),
                             source in self._verified, self.errors.get(source), interval=REFRESH_SECONDS)['stale']

    def _is_stale(self, source):
        if self._data_expired(source):
            return True
        return self._transport_stale(source)

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
                    if not isinstance(record, dict):
                        continue
                    identity = source_identity(name)
                    if identity is not None and record.get('identity') != identity:
                        continue
                    stamp = record['success_at']
                    if not finite(stamp):
                        continue
                    if not 0 < stamp <= time.time() + 60:
                        continue
                    data = validate_result(name, record["data"])
                    if name == "deepseek" and "ds_spend_day" not in data:
                        data = dict(data)
                        data.pop("ds_spend", None)  # legacy cache has no trustworthy day
                    self.data.update(data)
                    if name == 'codex':
                        self._credit_observation = record.get('vouchers', {})
                    self._success_at[name] = stamp
                    if name == 'main':
                        trends = record.get('trends', {})
                        self._radar_trends = {key: value for key, value in trends.items()
                            if key in ('cr_main24', 'cr_main48') and type(value) is int
                            and value in (-1, 1) and finite(data.get(key))} if isinstance(trends, dict) else {}
                except (KeyError, TypeError, ValueError):
                    continue
        except (OSError, ValueError, AttributeError):
            pass

    @staticmethod
    def _source_keys(name):
        return {"kimi": ("k5_", "kw_", "k_plan"),
                "codex": ("c5_", "cw_", "c_plan", "c_window", "cr_credit"),
                "glm": ("g5_", "gw_", "g_plan"), "main": ("cr_main",),
                "deepseek": ("ds_balance", "ds_spend", "ds_granted", "ds_topped_up",
                             "ds_currency", "ds_available", "ds_plan"),
                "tokens": ("ds_tokens_",)}[name]

    def _save_cache(self):
        sources = {name: {"success_at": stamp, "identity": self._source_identities.get(name),
                         "data": {key: value for key, value in self.data.items()
                                  if key.startswith(self._source_keys(name))}}
                   for name, stamp in self._success_at.items()}
        if 'main' in sources:
            sources['main']['trends'] = dict(self._radar_trends)
        if 'codex' in sources:
            sources['codex']['vouchers'] = dict(self._credit_observation)
        atomic_json(CACHE_FILE, {"version": 1, "sources": sources})

    def _on_result(self, name, payload, diagnostics):
        if name in self._source_identities and self._source_identities[name] != source_identity(name):
            # External env/file changes may happen while a worker is running.
            # Never stamp an old response with the newly selected account ID.
            self._sync_credentials()
            if self.root.state() != 'withdrawn':
                self._render()
                self._fit()
            self._write_debug()
            return
        if payload.get("ok"):
            if name == 'codex':
                self._credit_observation = observe_vouchers(
                    self._credit_observation, payload['data'], time.time())
            if name == 'main':
                trends = getattr(self, '_radar_trends', {}).copy()
                for key in ('cr_main24', 'cr_main48'):
                    old, new = self.data.get(key), payload['data'].get(key)
                    if finite(old) and finite(new):
                        if new != old:
                            trends[key] = 1 if new > old else -1
                    else:
                        trends.pop(key, None)
                self._radar_trends = trends
            if name == 'main':
                # A missing window never destroys the previously observed value.
                self.data = merge_radar(self.data, payload['data'])
            else:
                self.data = {k:v for k,v in self.data.items() if not k.startswith(self._source_keys(name))}
                self.data.update(payload["data"])
            self._success_at[name] = time.time()
            self._verified.add(name)
            self.errors.pop(name, None)
            try:
                self._save_cache()
                if self._ui_error == 'CacheWriteFailed':
                    self._ui_error = None
            except OSError:
                self._ui_error = "CacheWriteFailed"
        else:
            self.errors[name] = payload.get("error", "QueryFailed")
        self._diagnostics[name] = diagnostics
        try:
            if self.root.state() != 'withdrawn':
                self._render()
                self._fit()
            self._update_tray()
            if self._ui_error not in ('CacheWriteFailed',):
                self._ui_error = None
        except Exception as ex:
            self._ui_error = type(ex).__name__
        self._write_debug()

    def _write_debug(self):
        try:
            atomic_json(DEBUG_FILE, {
                "app_version": APP_VERSION, "user_agent": USER_AGENT,
                "updated": datetime.now().isoformat(timespec="seconds"), "pid": os.getpid(),
                "ui_thread": threading.get_native_id(),
                "window": {"state": self.root.state(), "geometry": self.root.geometry(),
                           "dpi": self.viewport._dpi},
                "data": self.data, "errors": self.errors, "ui_error": self._ui_error,
                "success_at": {name: datetime.fromtimestamp(ts).isoformat(timespec="seconds")
                               for name, ts in self._success_at.items()},
                "queries": self._diagnostics, "status_text": self.status.cget("text"),
                "update": {"busy": self.updater.busy, "last_error": self.updater.last_error},
                "history_write_failed": self.history.failed,
                "active": [name for name, state in self.scheduler.states.items() if state["worker"]],
                "tray": {"available": bool(self.tray_controller.icon and self.tray_controller.icon.visible),
                         "state": self.tray_controller.state,
                         "title": self.tray_controller.icon.title if self.tray_controller.icon else None}})
        except Exception:
            pass

    def _poll_commands(self, reschedule=True):
        """Cheap UI-only pump: tray restore never waits for the idle query timer.

        No file reads, images or network work while idle. Tk stays on its owner
        thread; tray callbacks only enqueue commands.
        """
        try:
            while not self._commands.empty():
                command = self._commands.get_nowait()
                if command == "quit":
                    self._quit()
                    return
                if command == "show":
                    self._render()
                    self.root.deiconify()
                    self._fit()
                    self.root.lift()
                    self._redraw()
                elif command == "refresh":
                    self.root.after_idle(self.refresh_async)
                elif command == "tray_failed":
                    self.tray_controller.failed = True
                    self.root.deiconify()
            if self.instance and self.instance.requested():
                self._render()
                self.root.deiconify()
                self._fit()
                self.root.lift()
                self._redraw()
        except Exception as ex:
            self._ui_error = type(ex).__name__
        finally:
            if reschedule and not self._closed:
                self.root.after(1000, self._poll_commands)

    def _poll(self):
        """Query/maintenance timer, separate from latency-sensitive UI commands."""
        try:
            if self.tray_controller.thread and not self.tray_controller.thread.is_alive() and not self.tray_controller.failed:
                self.tray_controller.failed = True
                self.root.deiconify()
            tray_state = self.tray_controller.state
            if tray_state != self._last_tray_state:
                self._last_tray_state = tray_state
                self._write_debug()
            active_before = tuple(n for n,s in self.scheduler.states.items() if s['worker'] is not None)
            self.scheduler.tick()
            self.updater.tick()
            if self._closed:
                return
            active_after = tuple(n for n,s in self.scheduler.states.items() if s['worker'] is not None)
            visible = self.root.state() != 'withdrawn'
            if active_before != active_after:
                if visible:
                    self._render()
                    self._fit()
                self._write_debug()
            if visible and self.viewport.update_dpi(self):
                self._fit()
            minute = int(time.time() // 60)
            if minute != self._last_render_minute:
                self._last_render_minute = minute
                self._sync_credentials()
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
            color = base if pct > 30 else (THEMES[self.theme]["WARNING"] if pct > 15 else THEMES[self.theme]["DANGER"])
            pl.config(text=f"{pct}%", fg=color)
            rl.config(text=reset_text if reset_text else "")

    def _set_row_visible(self, key, visible):
        """Show/hide a complete quota row without leaving an empty label."""
        widgets = [self.row_labels[key][0], *self.rows[key]]
        for wgt in widgets:
            (wgt.grid if visible else wgt.grid_remove)()

    def _set_amount(self, key, amount, currency, note="", warn=True, whole_width=3):
        """Render money instead of a percentage (pay-as-you-go balances).

        Both money rows pad their integer part to the same width, so all of them
        share the currency symbol position and the decimal point."""
        pl, rl = self.rows[key]
        if amount is None:
            pl.config(text="--")
            rl.config(text=note)
            return
        symbols = {"CNY": "¥", "USD": "$"}
        symbol = symbols.get(currency, currency + " " if currency else "")
        whole, _, cents = f"{amount:,.2f}".partition(".")
        pad = MONEY_PAD * max(whole_width - len(whole), 0)
        text = "%s%s%s.%s" % (symbol, pad, whole, cents)
        if 0 < amount < .01:
            text = '<' + symbol + '0.01'
        elif amount >= 1000000:
            unit, divisor = ('亿', 100000000) if amount >= 100000000 else ('万', 10000)
            text = f'{symbol}{amount/divisor:,.2f}{unit}'
        base = THEMES[getattr(self, "theme", "dark")]["FG_TEXT"]
        # Money has no natural percentage, so warn on an absolute threshold.
        limit = CFG.get("deepseek_low_balance") or 0
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            limit = 0.0
        color = base
        if warn and limit > 0 and amount <= limit:
            color = THEMES[self.theme]["DANGER"] if amount <= limit / 4 else THEMES[self.theme]["WARNING"]
        pl.config(text=text, fg=color)
        rl.config(text=note)

    def _set_custom(self, key, value, note="", color=None):
        """Rows that are neither a percentage nor money (counts, token volume)."""
        pl, rl = self.rows[key]
        pl.config(text="--" if value is None else str(value),
                  fg=color or THEMES[getattr(self, "theme", "dark")]["FG_TEXT"])
        rl.config(text=note or "")

    def _render_radar(self):
        """Show the selected public reset-radar window."""
        win = CFG.get("radar_window", 24)

        key = "cr_main48" if win == 48 else "cr_main24"
        main_pct = self.data.get(key)
        self._set_row("cr_main", main_pct, f"{win}h概率")
        if main_pct is not None:
            direction = getattr(self, '_radar_trends', {}).get(key, 0)
            color = THEMES[self.theme]['RADAR_UP' if direction > 0 else 'RADAR_DOWN'] if direction else (
                THEMES[self.theme]["WARNING"] if main_pct >= 80 else THEMES[self.theme]["FG_DIM"])
            self.rows["cr_main"][0].config(fg=color)

    def _render(self):
        d = self.data
        today = date.today().isoformat()
        if d.get("ds_tokens_day") != today:
            d.pop("ds_tokens_total", None)
            d.pop("ds_tokens_fresh", None)
        if d.get("ds_spend_day") and d["ds_spend_day"] != today:
            d["ds_spend"] = None
        # The Kimi usage endpoint may omit membership.level. The local display
        # override and renewal date must still be rendered in that case.
        k_plan = CFG.get("kimi_plan_name") or d.get("k_plan") or ""
        if k_plan or CFG.get("renew_kimi"):
            self._set_title("Kimi", "Kimi · " + k_plan)
            self.section_renews["Kimi"].config(
                text="续订 " + CFG.get("renew_kimi", ""), fg=THEMES[self.theme]["KIMI_SOFT"])
        if d.get("c_plan"):
            c_plan = CFG.get("codex_plan_name") or (
                d["c_plan"] + CFG.get("codex_plan_suffix", ""))
            self._set_title("Codex", "Codex · " + c_plan)
            self.section_renews["Codex"].config(
                text="续订 " + CFG.get("renew_codex", ""), fg=THEMES[self.theme]["CODEX_SOFT"])
        if d.get("g_plan"):
            g_title = "GLM" + ((" · " + CFG["glm_plan_name"])
                               if CFG.get("glm_plan_name") else "")
            self._set_title("GLM", g_title)
            renew_g = CFG.get("renew_glm", "")
            self.section_renews["GLM"].config(
                text=("续订 " + renew_g) if renew_g and renew_g != "MM-DD" else "",
                fg=THEMES[self.theme]["GLM_SOFT"])
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
        # Reset vouchers: hide the row when there are none (or when disabled).
        count, expiry, credit_note = credit_status(d)
        show_credits = bool(CFG.get("show_codex_credits", True)) and bool(count or credit_note.startswith('已到期'))
        self._set_row_visible("cr_credit", show_credits)
        if show_credits:
            note = credit_note
            if finite(expiry):
                note = _fmt_day(expiry) + " 到期"
                if credit_note:
                    note = _fmt_day(expiry) + ' ' + credit_note
            new, expiring = voucher_colors(self._credit_observation, time.time(), expiry)
            self._set_custom("cr_credit", f"{int(count or 0)} 张", note,
                             THEMES[self.theme]['DANGER' if new else 'FG_TEXT'])
            self.rows['cr_credit'][1].config(fg=THEMES[self.theme]['DANGER' if expiring else 'FG_DIM'])
        self._set_row("g5", d.get("g5_pct"),
                      _countdown(d.get("g5_reset")) if d.get("g5_reset") else "")
        self._set_row("gw", d.get("gw_pct"), _fmt_reset(d.get("gw_reset")))
        # DeepSeek is pay-as-you-go: the card shows money, not a percentage.
        if d.get("ds_plan") or d.get("ds_balance") is not None:
            self._set_title("DeepSeek", "DeepSeek")
            self.section_renews["DeepSeek"].config(text="按量付费", fg=THEMES[self.theme]["DEEPSEEK_SOFT"])
        # Both money rows share one integer width, so their currency symbols and
        # decimal points line up (¥114.05 / ¥  4.68).
        money = [v for v in (d.get("ds_balance"), d.get("ds_spend"))
                 if isinstance(v, (int, float)) and not isinstance(v, bool)]
        whole_width = max([len(f"{v:,.2f}".partition(".")[0]) for v in money] or [3])
        if d.get("ds_balance") is not None:
            # Use the current clock, not the last balance refresh timestamp.
            if d.get("ds_available", True):
                note, peak = tariff_status(datetime.now(timezone.utc), DEEPSEEK_HOLIDAYS)
            else:
                note = "账号不可用"
                self.rows['ds'][1].config(fg=THEMES[self.theme]['FG_DIM'])
            self._set_amount("ds", d.get("ds_balance"), d.get("ds_currency") or "",
                             note, whole_width=whole_width)
            if d.get('ds_available', True):
                self.rows['ds'][1].config(fg=THEMES[self.theme][
                    'DANGER' if peak else 'RADAR_DOWN' if peak is False else 'FG_DIM'])
        else:
            self._set_amount('ds', None, '')
            self.rows['ds'][1].config(fg=THEMES[self.theme]['FG_DIM'])
        # Today's spend is estimated from balance changes, never colour-warned.
        # Its note shows how many tokens the local Harness used today, when that
        # can be read (see local_harness_tokens); otherwise it stays empty.
        metric = CFG.get("deepseek_token_metric", "total")
        tokens = d.get("ds_tokens_" + ("fresh" if metric == "fresh" else "total"))
        if self._transport_stale("tokens"):
            tokens = None
        token_text = _fmt_tokens(tokens) if metric != "off" else None
        token_note = (token_text + ' tok') if token_text is not None else ''
        if not token_note and metric != 'off' and self.errors.get('tokens'):
            token_note = error_label(self.errors['tokens'])
        self._set_amount("ds_spend", d.get("ds_spend"), d.get("ds_currency") or "",
                         token_note,
                         warn=False, whole_width=whole_width)
        self._render_radar()
        enabled = self._enabled_sources()
        for source, keys in {"kimi": ("k5", "kw"),
                             "codex": ("c5", "cw", "cr_credit"),
                             "glm": ("g5", "gw"), "main": ("cr_main",),
                             "deepseek": ("ds", "ds_spend")}.items():
            if source in ('codex','kimi','glm') and source in enabled and not self._transport_stale(source):
                for key in keys:
                    if key == 'cr_credit':
                        continue
                    if self._window_expired(key) or (source == 'codex' and not any(d.get(k + "_reset") for k in ("c5", "cw"))
                                                    and d.get("c_window_expired")):
                        self.rows[key][1].config(text="窗口已过期")
                        self.rows[key][0].config(fg=THEMES[self.theme]["FG_DIM"])
            elif source in enabled and self._is_stale(source):
                text = error_label(self.errors.get(source), source) or (
                    radar_status(d, CFG.get('radar_window', 24), source in self._verified)['reason']
                    if source == 'main' else self._stale_text(source))
                for key in keys:
                    # Preserve business metadata (especially voucher expiry).
                    value, note_label = self.rows[key]
                    old_value = str(value.cget('text'))
                    if old_value not in ('--', '…'):
                        value.config(text=old_value.removesuffix(' ·旧') + ' ·旧')
                    if source == 'main' or not note_label.cget('text') or note_label.cget('text') == '?':
                        note_label.config(text=text)
                    self.rows[key][0].config(fg=THEMES[self.theme]["FG_DIM"])
        stale = [name for name in enabled if self._is_stale(name)]
        for source, keys in (('deepseek', ('ds','ds_spend')), ('glm', ('g5','gw')), ('kimi', ('k5','kw')), ('codex', ('c5','cw'))):
            if CFG.get('show_'+source) and source not in enabled:
                for key in keys:
                    self.rows[key][0].configure(text='--')
                    if key != 'ds_spend' or not token_note:
                        self.rows[key][1].configure(text='未配置 Key' if source in ('glm','deepseek') else '未登录',
                                                    fg=THEMES[self.theme]['FG_DIM'])
        if d.get('ds_spend_error'):
            self.rows['ds_spend'][0].configure(text='--')
            if not token_text:
                self.rows['ds_spend'][1].configure(text='估算不可用')
        parts = []
        account_times = [self._success_at.get(name) for name in enabled
                         if name in ("kimi", "codex", "glm", "deepseek")]
        loaded = any(self._success_at.get(name) for name in enabled)
        if not enabled:
            parts.append('右键 → 快速设置')
        else:
            if account_times and all(account_times):
                parts.append("刷新时间 "
                             + datetime.fromtimestamp(min(account_times)).strftime("%H:%M"))
            elif not account_times and loaded:
                parts.append('刷新时间 ' + datetime.fromtimestamp(
                    min(self._success_at[n] for n in enabled if self._success_at.get(n))).strftime('%H:%M'))
            active = [n for n,s in self.scheduler.states.items() if s['worker'] is not None]
            enabled_all = set(self._enabled_sources())
            errors = {n:e for n,e in self.errors.items() if n in enabled_all}
            notice = refresh_notice(active, errors, stale,
                                    [n for n in stale if self._data_expired(n)],
                                    [n for n in stale if n not in self._verified and self._success_at.get(n)],
                                    {n: s['due']-time.monotonic() for n,s in self.scheduler.states.items()})
            if notice:
                parts.append(notice)
            elif not loaded:
                parts.append('等待查询')
            if self.tray_controller.failed:
                parts.append("托盘不可用")
        if not parts:
            parts.append("加载中…")
        if CONFIG_ISSUES:
            parts.append('配置异常')
        if self._ui_error == 'CacheWriteFailed' or CONFIG_SAVE_FAILED:
            parts.append('保存失败')
        if self.history.failed:
            parts.append('记录失败')
        self.status.config(text="  ".join(parts),
                           fg=THEMES[self.theme]["DANGER"] if stale else THEMES[self.theme]["FG_DIM"])
        self.theme_painter.update()

    def _network_settings(self):
        from widget_network import show_network
        if show_network(self, CFG, _save_config):
            for state in self.scheduler.states.values():
                if state['worker']:
                    state['worker'].close()
                    state['worker'] = None
            self.scheduler.refresh()
            self.updater.network_changed()
            self.refresh_async()

    def _copy_diagnostics(self):
        from quota_cli import doctor
        report, _ = doctor(sys.modules[__name__])
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.status.config(text='已复制脱敏诊断')

    def run(self):
        self.root.mainloop()


def query_worker(name):
    if sys.stdin.buffer.readline(16) != b"go\n":
        return
    try:
        fn = {"kimi": fetch_kimi, "codex": fetch_codex, "glm": fetch_glm,
              "deepseek": fetch_deepseek, "main": fetch_main_radar, "tokens": fetch_tokens}[name]
        data = validate_result(name, fn())
        payload = {"ok": True, "data": data}
    except Exception as ex:
        code = ex.code if isinstance(ex, urllib.error.HTTPError) else None
        payload = {"ok": False, "error": error_code(ex),
                   "retryable": code not in (400, 401, 403, 404) and not isinstance(ex, FileNotFoundError)
                   and error_code(ex) not in ('PACUnsupported','ProxyUnsupported','UnsafeRedirect','InvalidNetworkSettings','InvalidProxy')}
        if code == 429:
            payload['retry_after'] = retry_after(ex.headers)
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
                prepare_shared_data()
                app = App(instance)
                app.run()
        except Exception as exc:
            try:
                atomic_json(DEBUG_FILE, {'app_version': APP_VERSION,
                    'startup_error': type(exc).__name__})
                ctypes.windll.user32.MessageBoxW(None,
                    '程序未能启动。请重新运行安装器修复环境，或运行 --doctor 获取脱敏诊断。',
                    'AI Quota Widget ' + APP_VERSION, 0x10)
            except Exception:
                pass
            raise
        finally:
            if app:
                app.scheduler.close()
            instance.close()
