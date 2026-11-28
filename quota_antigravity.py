"""Official-interface Antigravity quota snapshot & public global reset monitor.

Standard library only; no Tk, Pillow, tray, credential scraping, browser cookies,
or undocumented local RPC access.
"""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time

AG_RESET_URL = "https://gemini-resets.com/api/v1/status"
AG_SNAPSHOT_NAME = "antigravity-snapshot.json"
AG_CLI_DIR = os.path.expanduser(r"~\.gemini\antigravity-cli")
AG_CLI_SETTINGS = os.path.join(AG_CLI_DIR, "settings.json")
AG_EXE_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe"),
]
AG_RESET_PHASES = ("recorded", "empty")
AG_RESET_TYPES = ("full", "partial", "banked")
AG_RESET_VERIFICATIONS = ("confirmed", "provisional", "unverified")
AG_MAX_SNAPSHOT_BYTES = 256 * 1024


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _stamp(value):
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            value = parsed.timestamp()
        return value if _finite(value) and 0 < value < 253402300800 else None
    except (ValueError, OverflowError, OSError):
        return None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _fraction_pct(value):
    if not _finite(value) or not 0.0 <= value <= 1.0:
        return None
    return max(0, min(100, int(round(value * 100))))


def _sanitize_token(value, allowed=None, limit=24, default=""):
    if not isinstance(value, str):
        return default
    text = value.strip().lower()[:limit]
    if allowed is not None:
        return text if text in allowed else default
    return text if all(c.isalnum() or c in ("-", "_", " ") for c in text) else default


def parse_ag_reset(payload, now=None):
    """Parse public gemini-resets.com/api/v1/status JSON without fake forecasting.

    Cadence stats such as avg_interval_days are intentionally ignored so
    historical intervals can never be presented as a reset forecast.
    Raw social text and URLs are never persisted.
    """
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("invalid antigravity reset response")
    data = payload["data"]
    meta = _mapping(payload.get("meta"))
    generated = _stamp(meta.get("generated_at"))
    latest = data.get("latest_reset")
    if latest is None:
        return {
            "ag_reset_phase": "empty",
            "ag_reset_at": None,
            "ag_reset_type": None,
            "ag_reset_scope": None,
            "ag_reset_verified": None,
            "ag_reset_updated": generated,
            "ag_reset_checked_at": now,
        }
    if not isinstance(latest, dict):
        raise ValueError("invalid antigravity latest_reset")
    reset_at = _stamp(latest.get("announced_at"))
    if reset_at is None or reset_at > now + 300:
        raise ValueError("invalid antigravity reset time")
    reset_type = _sanitize_token(latest.get("reset_type"), AG_RESET_TYPES)
    if not reset_type:
        raise ValueError("invalid antigravity reset type")
    scope = _sanitize_token(latest.get("scope"), default="all") or "all"
    verified = _sanitize_token(latest.get("verification"), AG_RESET_VERIFICATIONS, default="unverified")
    return {
        "ag_reset_phase": "recorded",
        "ag_reset_at": reset_at,
        "ag_reset_type": reset_type,
        "ag_reset_scope": scope,
        "ag_reset_verified": verified,
        "ag_reset_updated": generated,
        "ag_reset_checked_at": now,
    }


def ag_reset_view(data, now=None):
    """Pure clock-driven view of the latest official Antigravity global reset."""
    now = time.time() if now is None else now
    phase = data.get("ag_reset_phase")
    if phase not in AG_RESET_PHASES:
        return None
    reset_at = _stamp(data.get("ag_reset_at"))
    if phase == "empty" or reset_at is None:
        return {"recent": False, "kind": "empty", "value": "--", "note": "暂无记录"}
    reset_type = data.get("ag_reset_type") or "full"
    elapsed = max(0.0, now - reset_at)
    local = datetime.fromtimestamp(reset_at).astimezone()
    if elapsed <= 86400:
        label = {"full": "已重置", "partial": "部分重置", "banked": "已发券"}.get(reset_type, "已重置")
        return {
            "recent": True,
            "kind": reset_type,
            "value": label,
            "note": local.strftime("%m-%d %H:%M"),
        }
    days = max(1, int(elapsed // 86400))
    tag = {"full": "全员", "partial": "部分", "banked": "发券"}.get(reset_type, "重置")
    return {
        "recent": False,
        "kind": "history",
        "value": f"{days}天前",
        "note": f"{local.strftime('%m-%d')} {tag}",
    }


def ag_reset_status(data, verified=False, error=None, now=None):
    """Freshness contract for the public Antigravity global reset feed."""
    from quota_state import error_label
    now = time.time() if now is None else now
    view = ag_reset_view(data, now)
    checked = _stamp(data.get("ag_reset_checked_at"))
    updated = _stamp(data.get("ag_reset_updated"))
    reason = error_label(error, "ag_reset") if error else ""
    if not reason:
        if view is None:
            reason = "暂无数据"
        elif not verified:
            reason = "缓存待核验"
        elif not checked or now - checked > 960 or checked > now + 60:
            reason = "数据待更新"
        elif not updated:
            reason = "信源时间未提供"
        elif updated > now + 300 or now - updated > 6 * 3600:
            reason = "信源记录过旧" if updated <= now else "信源时间异常"
    return {"stale": bool(reason), "state": "stale" if reason else "ok", "reason": reason}


def _bucket_reset(bucket, now):
    reset_at = _stamp(bucket.get("reset_time"))
    if reset_at is not None:
        return reset_at
    secs = bucket.get("reset_in_seconds")
    if _finite(secs) and 0 <= secs <= 365 * 86400:
        return now + float(secs)
    return None


def _is_partner_bucket(key):
    lower = key.lower()
    return any(tok in lower for tok in ("claude", "3p", "third", "partner", "gpt", "anthropic", "openai"))


def _is_five_hour_bucket(key, bucket):
    lower = key.lower()
    if any(tok in lower for tok in ("5h", "5_h", "5-h", "five", "short", "burst")):
        return True
    if any(tok in lower for tok in ("week", "7d", "weekly")):
        return False
    secs = bucket.get("reset_in_seconds")
    return _finite(secs) and 0 < secs <= 6 * 3600


def parse_statusline_payload(payload, now=None, use_g1_credits=None):
    """Parse documented agy CLI statusLine JSON into sanitized quota fields.

    Strictly ignores email, cwd, conversation_id, transcript_path, workspace,
    and VCS details so personal metadata never enters cache or diagnostics.
    """
    now = time.time() if now is None else now
    if not isinstance(payload, dict):
        raise ValueError("invalid antigravity payload")
    captured = _stamp(payload.get("captured_at")) or now
    quota = payload.get("quota")
    if not isinstance(quota, dict):
        raise ValueError("missing antigravity quota")

    a5_pct = a5_reset = aw_pct = aw_reset = None
    a5_disabled = False
    a3p_pct = a3p_reset = a3p5_pct = a3p5_reset = None
    credits = None

    for raw_key, bucket in quota.items():
        if not isinstance(raw_key, str) or not isinstance(bucket, dict):
            continue
        key = raw_key.strip().lower()
        if "credit" in key or (bucket.get("remaining_amount") is not None and bucket.get("remaining_fraction") is None):
            amt = bucket.get("remaining_amount")
            if _finite(amt) and 0 <= amt <= 1e12:
                credits = round(float(amt), 4)
            continue
        pct = _fraction_pct(bucket.get("remaining_fraction"))
        if pct is None:
            continue
        reset_at = _bucket_reset(bucket, captured)
        disabled = bool(bucket.get("disabled")) if isinstance(bucket.get("disabled"), bool) else False
        if _is_partner_bucket(key):
            if _is_five_hour_bucket(key, bucket):
                a3p5_pct = pct if a3p5_pct is None else min(a3p5_pct, pct)
                if reset_at is not None:
                    a3p5_reset = reset_at if a3p5_reset is None else min(a3p5_reset, reset_at)
            else:
                a3p_pct = pct if a3p_pct is None else min(a3p_pct, pct)
                if reset_at is not None:
                    a3p_reset = reset_at if a3p_reset is None else min(a3p_reset, reset_at)
        else:
            if _is_five_hour_bucket(key, bucket):
                a5_pct = pct if a5_pct is None else min(a5_pct, pct)
                if reset_at is not None:
                    a5_reset = reset_at if a5_reset is None else min(a5_reset, reset_at)
                a5_disabled = a5_disabled or disabled
            else:
                aw_pct = pct if aw_pct is None else min(aw_pct, pct)
                if reset_at is not None:
                    aw_reset = reset_at if aw_reset is None else min(aw_reset, reset_at)

    if a5_pct is None and aw_pct is None and a3p_pct is None and a3p5_pct is None and credits is None:
        raise ValueError("empty antigravity quota")

    raw_plan = payload.get("plan_tier")
    plan = ""
    if isinstance(raw_plan, str):
        cleaned = raw_plan.strip()[:40]
        if cleaned:
            plan = cleaned
    if credits is None and _finite(payload.get("ai_credits")) and 0 <= payload["ai_credits"] <= 1e12:
        credits = round(float(payload["ai_credits"]), 4)
    if aw_pct == 0 and a5_pct == 0:
        a5_disabled = True

    result = {
        "a5_pct": a5_pct,
        "a5_reset": a5_reset,
        "a5_disabled": bool(a5_disabled),
        "aw_pct": aw_pct,
        "aw_reset": aw_reset,
        "a3p_pct": a3p_pct,
        "a3p_reset": a3p_reset,
        "a3p5_pct": a3p5_pct,
        "a3p5_reset": a3p5_reset,
        "a_credits": credits,
        "a_plan": plan,
        "a_captured_at": captured,
    }
    if isinstance(use_g1_credits, bool):
        result["a_credits_enabled"] = use_g1_credits
    return result


def read_cli_use_g1_credits(settings_path=None):
    path = Path(settings_path or AG_CLI_SETTINGS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict) and isinstance(raw.get("useG1Credits"), bool):
            return raw["useG1Credits"]
    except (OSError, ValueError):
        pass
    return None


def find_agy_exe():
    for candidate in AG_EXE_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("agy") or ""


def snapshot_path_for(data_dir, custom_path=""):
    custom = (custom_path or "").strip()
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    return os.path.join(str(data_dir), AG_SNAPSHOT_NAME)


def read_ag_snapshot(snapshot_path, settings_path=None, now=None):
    """Load the locally captured official agy statusLine quota snapshot."""
    path = Path(snapshot_path)
    if not path.is_file():
        raise FileNotFoundError("antigravity snapshot not found")
    raw_bytes = path.read_bytes()[:AG_MAX_SNAPSHOT_BYTES + 1]
    if len(raw_bytes) > AG_MAX_SNAPSHOT_BYTES:
        raise ValueError("antigravity snapshot too large")
    payload = json.loads(raw_bytes.decode("utf-8-sig"))
    use_g1 = read_cli_use_g1_credits(settings_path)
    if isinstance(payload, dict) and "quota" in payload:
        return parse_statusline_payload(payload, now=now, use_g1_credits=use_g1)
    if isinstance(payload, dict) and payload.get("schema") == "antigravity-snapshot-v1" and isinstance(payload.get("data"), dict):
        data = dict(payload["data"])
        if use_g1 is not None and "a_credits_enabled" not in data:
            data["a_credits_enabled"] = use_g1
        return data
    raise ValueError("invalid antigravity snapshot")


def capture_statusline_stdin(snapshot_path, raw_text, now=None):
    """Sanitize a statusLine JSON payload from stdin and persist atomically."""
    from monitor_runtime import atomic_json
    now = time.time() if now is None else now
    payload = json.loads(raw_text)
    data = parse_statusline_payload(payload, now=now, use_g1_credits=read_cli_use_g1_credits())
    target = Path(snapshot_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, {"schema": "antigravity-snapshot-v1", "captured_at": now, "data": data})
    return data


def install_agy_statusline_bridge(command_str, settings_path=None):
    """Safely register the official agy statusLine command with stack_with_default=True."""
    from monitor_runtime import atomic_json
    path = Path(settings_path or AG_CLI_SETTINGS)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                current = loaded
            else:
                raise ValueError("settings root is not object")
        except (OSError, ValueError):
            backup = path.with_name(f"{path.name}.bak-{time.time_ns()}")
            shutil.copy2(path, backup)
            current = {}
    current["statusLine"] = {
        "type": "command",
        "command": command_str,
        "enabled": True,
        "stack_with_default": True,
    }
    atomic_json(path, current)
    return str(path)


def snapshot_identity(snapshot_path):
    return hashlib.sha256(os.path.abspath(str(snapshot_path)).lower().encode("utf-8")).hexdigest()
