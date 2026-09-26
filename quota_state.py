"""Shared, side-effect-free status/config contracts for GUI and headless tools."""
import math
import time

SOURCES = ('kimi', 'codex', 'glm', 'deepseek', 'main', 'tokens')
ACCOUNT_SOURCES = SOURCES[:4]
ERROR_LABELS = {
    'HTTP401': '需重新认证', 'HTTP403': '权限或套餐受限', 'HTTP429': '服务限流',
    'Timeout': '请求超时', 'TimeoutError': '请求超时', 'URLError': '连接失败',
    'ConnectionError': '连接失败', 'InvalidResponse': '接口数据异常',
    'ValueError': '接口数据异常', 'FileNotFoundError': '缺少凭据或运行时',
    'StartFailed': '查询进程启动失败', 'WorkerFailed': '查询进程异常',
    'no_key': '未配置Key', 'no_credentials': '未登录', 'no_runtime': '未安装运行时',
    'no_cache': '暂无数据', 'PermissionError': '本机权限不足',
}

def error_label(error):
    if not error:
        return ''
    if not isinstance(error, str):
        return '查询失败'
    return ERROR_LABELS.get(error, '服务暂不可用' if str(error).startswith('HTTP5') else '查询失败')

def finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False

def window_expired(data, prefix, now=None):
    value = data.get(prefix + '_reset')
    return finite(value) and value <= (time.time() if now is None else now)

def source_status(data, stamp=0, verified=False, error=None, now=None, interval=900):
    now = time.time() if now is None else now
    cached = bool(data) and finite(stamp) and stamp > 0
    stale = not verified or bool(error) or not finite(stamp) or now-stamp > interval+60
    state = 'error' if error else 'unverified' if cached and not verified else 'stale' if cached and stale else 'ok' if cached else 'empty'
    return dict(state=state, stale=stale, cached=cached,
                reason=error_label(error) if error else '缓存待核验' if cached and not verified else '数据已过旧' if cached and stale else '暂无数据' if not cached else '')

def validate_config(raw, defaults):
    result, issues = dict(defaults), []
    if not isinstance(raw, dict):
        return result, ['config: expected object']
    enums = {'theme': ('dark','light','steam','fuel','ink','glass'), 'glm_region': ('cn','intl'),
             'deepseek_token_metric': ('total','fresh','off'), 'radar_window': (24,48),
             'tray_metric': ('cw_pct','c5_pct','kw_pct','k5_pct','gw_pct','g5_pct')}
    for key, value in raw.items():
        valid = True
        if key in enums:
            valid = value in enums[key]
        elif key.startswith('show_') or key in ('lock_position',):
            valid = isinstance(value, bool) or (key == 'show_codex_5h' and value is None)
        elif key in ('window_x','window_y','window_alpha','deepseek_low_balance'):
            valid = finite(value)
        elif key in defaults and isinstance(defaults[key], str):
            valid = isinstance(value, str)
        if valid:
            result[key] = value
        else:
            issues.append(key + ': invalid type/value')
    return result, issues

def credit_status(data, now=None):
    """Do not turn the soonest voucher expiry into expiry of every voucher."""
    now = time.time() if now is None else now
    count = data.get('cr_credit_count')
    count = int(count) if finite(count) and count >= 0 else None
    expiries = data.get('cr_credit_expiries')
    expiry = data.get('cr_credit_expiry')
    if isinstance(expiries, list) and count is not None and len(expiries) == count and all(finite(e) for e in expiries):
        alive = [e for e in expiries if e > now]
        return len(alive), min(alive, default=None), ('已到期' if count and not alive else '')
    if finite(expiry) and expiry <= now:
        return count, expiry, '已到期·待更新' if count == 1 else '部分到期·待更新'
    return count, expiry if finite(expiry) else None, '' if finite(expiry) else '期限未提供'
