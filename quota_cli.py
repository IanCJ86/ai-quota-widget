"""Headless commands. Standard library only; no Tk, tray or scheduler imports."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
from datetime import datetime
from app_version import APP_VERSION
from quota_state import SOURCES, ACCOUNT_SOURCES, source_status, window_expired, error_label, finite, credit_status

PUBLIC_FIELDS = {
    'kimi': ('k5_pct','kw_pct','k5_reset','kw_reset'),
    'codex': ('c5_pct','cw_pct','c5_reset','cw_reset','cr_credit_count','cr_credit_expiry','cr_credit_expiries','c_window_expired'),
    'glm': ('g5_pct','gw_pct','g5_reset','gw_reset'),
    'deepseek': ('ds_balance','ds_spend','ds_spend_day','ds_currency','ds_available'),
    'main': ('cr_main24','cr_main48'),
    'tokens': ('ds_tokens_total','ds_tokens_fresh','ds_tokens_day'),
}

def safe_data(name, data):
    output = {}
    for key in PUBLIC_FIELDS[name]:
        value = data.get(key)
        if value is None or finite(value) or isinstance(value, bool):
            output[key] = value
        elif key.endswith('_day') and isinstance(value, str):
            try:
                output[key] = datetime.strptime(value, '%Y-%m-%d').date().isoformat()
            except ValueError:
                pass
        elif key == 'ds_currency' and value in ('CNY','USD'):
            output[key] = value
        elif key == 'cr_credit_expiries' and isinstance(value, list) and all(finite(x) for x in value):
            output[key] = value
    return output

def configured(m):
    return dict(kimi=os.path.isfile(m.KIMI_CRED),
                codex=os.path.isfile(os.path.join(m.CODEX_HOME, 'auth.json')),
                glm=bool(m.glm_api_key()), deepseek=bool(m.deepseek_api_key()))

def read_json(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def collect(m, fresh=False, factory=None):
    from monitor_runtime import QueryProcess, validate_result
    flags = configured(m)
    flags['main'] = bool(m.CFG.get('show_radar')) and flags['codex']
    flags['tokens'] = flags['deepseek'] and m.CFG.get('deepseek_token_metric','total') != 'off' and os.path.isdir(m.DSH_SESSIONS)
    cache = read_json(m.CACHE_FILE).get('sources', {})
    if not isinstance(cache, dict):
        cache = {}
    sources, errors = {}, {}
    now = time.time()
    for name in SOURCES:
        if not flags[name]:
            sources[name] = dict(ok=False, stale=False, state='not_configured', error=None, data={})
            continue
        record = cache.get(name, {})
        record = record if isinstance(record, dict) else {}
        data = record.get('data', {})
        stamp = record.get('success_at', 0)
        if not finite(stamp) or not 0 < stamp <= now+60:
            data, stamp = {}, 0
        try:
            validate_result(name, data)
            data = safe_data(name, data)
        except (ValueError, TypeError, KeyError):
            data, stamp = {}, 0
        error, verified = None, False
        if fresh:
            worker = None
            try:
                worker = (factory or QueryProcess)(str(Path(m.__file__).resolve()), name)
                deadline = time.monotonic() + (65 if name == 'kimi' else 50 if name == 'codex' else 25)
                while worker.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    time.sleep(.05)
                result = worker.result()
                if result.get('ok'):
                    validate_result(name, result['data'])
                    data, stamp, verified = safe_data(name, result['data']), time.time(), True
                else:
                    error = error_label(result.get('error'))
            except Exception as exc:
                error = error_label(type(exc).__name__)
            finally:
                if worker is not None:
                    worker.close()
        status = source_status(data, stamp, verified, error, now=time.time())
        prefix = {'kimi':('k5','kw'),'codex':('c5','cw'),'glm':('g5','gw')}.get(name, ())
        expired = [p for p in prefix if window_expired(data, p)]
        if expired:
            status.update(stale=True, state='window_expired', reason='窗口已过期')
        if name == 'deepseek' and data.get('ds_spend_day') != datetime.now().date().isoformat():
            data.pop('ds_spend', None)
        if name == 'tokens' and data.get('ds_tokens_day') != datetime.now().date().isoformat():
            data.pop('ds_tokens_total', None)
            data.pop('ds_tokens_fresh', None)
            status.update(stale=True, state='stale', reason='统计日期已过期')
        if name == 'codex' and data:
            count, expiry, note = credit_status(data)
            data.update(cr_credit_count=count, cr_credit_expiry=expiry)
        if not data and not error:
            error = '暂无数据'
        if error:
            errors[name] = error
        sources[name] = dict(ok=bool(data) and not error, stale=status['stale'], state=status['state'],
            error=error, last_success=datetime.fromtimestamp(stamp).astimezone().isoformat() if stamp else None,
            expired_windows=expired, data=data)
    active = [v for k,v in sources.items() if k in ACCOUNT_SOURCES and v['state'] != 'not_configured']
    useful = any(v['data'] for v in active)
    code = 2 if not useful else 1 if errors or m.CONFIG_ISSUES or any(v['stale'] for v in active) else 0
    return dict(schema=1,app_version=APP_VERSION,generated_at=datetime.now().astimezone().isoformat(),
                source='fresh' if fresh else 'cache',sources=sources,errors=errors), code

def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ModuleNotFoundError):
        return False

def doctor(m):
    from quota_install import source_paths, running
    code_root, assets = source_paths()
    manifest = (assets/'runtime-files.txt').read_text(encoding='utf-8').splitlines()
    missing = [n for n in manifest if not (module_available(n[:-3]) if getattr(sys,'frozen',False) else (code_root/n).is_file())]
    deps = {'tkinter':module_available('tkinter'),'Pillow':module_available('PIL'),
            'pystray':module_available('pystray'),
            'zstd':module_available('compression.zstd' if sys.version_info >= (3,14) else 'backports.zstd')}
    flags = configured(m)
    snapshot, _ = collect(m)
    debug = read_json(m.DEBUG_FILE)
    recent_errors = debug.get('errors', {})
    recent_errors = recent_errors if isinstance(recent_errors, dict) else {}
    lines = [f'AI Quota Widget {APP_VERSION} | 临界思潮',
             f'Python {sys.version.split()[0]} / {sys.platform}',
             '依赖可发现（不代表已实测GUI）：' + '  '.join(k+(' OK' if v else ' 缺失') for k,v in deps.items()),
             f'运行模块 {len(manifest)-len(missing)}/{len(manifest)}' + (' 缺失：'+','.join(missing) if missing else ' 齐全'),
             '配置：' + ('异常，请检查config.json字段类型/文件格式' if m.CONFIG_ISSUES else '可读/使用默认值'),
             '本机实例：' + ('运行中' if running() else '未运行'),
             '此报告离线，不测试网络、不显示密钥、路径、账号或余额。']
    for name in ACCOUNT_SOURCES:
        state = snapshot['sources'][name]
        label = '凭据存在' if flags[name] else '未配置（可跳过）'
        lines.append(f'{name}: {label}; {state["state"]}; 上次成功={state.get("last_success") or "无"}; '
                     f'最后错误={error_label(recent_errors.get(name)) or "无记录"}')
    lines.append('雷达：codexreset.org，第三方预测，非OpenAI官方；本次未联网核验。')
    lines.append('今日金额为本机余额差额估算，token仅统计本机Harness，均非官方账单。')
    if debug.get('startup_error') or debug.get('ui_error'):
        lines.append('最近界面/启动异常：' + error_label(debug.get('startup_error') or debug.get('ui_error')))
    if not any(flags.values()):
        lines.append('未检测到已登录的AI CLI或API Key：请登录Kimi/Codex，或配置GLM/DeepSeek Key。')
        code = 1  # configuration pending, not a broken installation
    else:
        code = 1 if missing or not all(deps.values()) or m.CONFIG_ISSUES or recent_errors or debug.get('startup_error') or debug.get('ui_error') else 0
    return '\n'.join(lines), code

def summary(snapshot):
    lines = [f'AI Quota Widget {APP_VERSION} · 临界思潮 · {snapshot["source"]}']
    labels = {'k5_pct':'5小时剩余','kw_pct':'每周剩余','c5_pct':'5小时剩余',
              'cw_pct':'每周剩余','g5_pct':'5小时剩余','gw_pct':'每周剩余',
              'cr_credit_count':'重置券','ds_balance':'余额','ds_spend':'今日估算',
              'ds_tokens_total':'今日总token','ds_tokens_fresh':'今日非缓存token',
              'cr_main24':'24小时预测','cr_main48':'48小时预测'}
    states = {'ok':'已查询','unverified':'缓存待核验','stale':'旧数据','window_expired':'窗口已过期','empty':'暂无数据'}
    for name, row in snapshot['sources'].items():
        if row['state'] == 'not_configured':
            continue
        values = []
        for key, label in labels.items():
            value = row['data'].get(key)
            if value is not None:
                suffix = '%' if key.endswith('_pct') or key.startswith('cr_main') else '张' if key == 'cr_credit_count' else ''
                prefix = ('¥' if row['data'].get('ds_currency') == 'CNY' else '$') if key in ('ds_balance','ds_spend') else ''
                values.append(f'{label} {prefix}{value}{suffix}')
        lines.append(f'{name}: {"  ".join(values) or "--"}  [{row["error"] or states.get(row["state"], row["state"])}]')
    if len(lines) == 1:
        lines.append('未检测到已登录的AI CLI或API Key；请登录Kimi/Codex或配置GLM/DeepSeek。')
    lines.append('今日金额为本机余额差额估算，token仅统计本机Harness，均非官方账单。雷达为第三方预测。')
    return '\n'.join(lines)

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='AI Quota Widget | 临界思潮 · Windows额度监控')
    mode = parser.add_mutually_exclusive_group()
    for flag in ('doctor','json','once','install','version','launch-check'):
        mode.add_argument('--'+flag, action='store_true')
    parser.add_argument('--fresh', action='store_true', help='显式联网查询（仅json/once）')
    parser.add_argument('--data-dir', help='本机状态目录，不输出到诊断')
    parser.add_argument('--dest', help='安装位置')
    parser.add_argument('--no-autostart', action='store_true')
    parser.add_argument('--skip-deps', action='store_true')
    args = parser.parse_args(argv)
    if args.fresh and not (args.json or args.once):
        parser.error('--fresh需要--json或--once')
    if (args.dest or args.no_autostart or args.skip_deps) and not args.install:
        parser.error('安装选项需要--install')
    if args.version:
        print(APP_VERSION)
        return 0
    if args.launch_check:
        if getattr(sys, 'frozen', False):
            import tkinter, PIL, pystray
            return 0
        import subprocess
        check = subprocess.run([sys.executable,'-c','import tkinter,PIL,pystray'], capture_output=True)
        if check.returncode:
            print('启动环境缺少Tk/Pillow/pystray。请重新运行install.ps1修复；--doctor可生成诊断。')
            return 2
        return 0
    if args.data_dir:
        os.environ['AI_QUOTA_WIDGET_DATA_DIR'] = str(Path(args.data_dir).resolve())
    if args.install:
        from quota_install import install
        try:
            print(install(args.dest, skip_deps=args.skip_deps))
            return 0
        except Exception as exc:
            print('安装未完成：'+str(exc), file=sys.stderr)
            return 2
    if not (args.doctor or args.json or args.once):
        parser.print_help()
        return 0
    # Imported with a headless flag even when invoked via a package entry point.
    if '--doctor' not in sys.argv and not any(x in sys.argv for x in ('--json','--once')):
        sys.argv.append('--doctor')
    import quota_monitor as m
    if args.doctor:
        report, code = doctor(m)
        print(report)
    else:
        report, code = collect(m, args.fresh)
        print(json.dumps(report, ensure_ascii=False, allow_nan=False) if args.json else summary(report))
    return code
