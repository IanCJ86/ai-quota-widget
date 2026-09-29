"""Standalone Windows package smoke; empty profile, PATH without Python/Node.

Run only with the real widget closed (same single-instance contract). Tests
create no user shortcut, show no user-desktop windows, and query no real keys.
"""
from desktop_test_support import isolate_desktop
isolate_desktop()
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor_runtime import QueryProcess


def wait_for(check, seconds=15):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        value = check()
        if value: return value
        time.sleep(.1)
    raise AssertionError('bounded wait failed')


def smoke(bundle):
    assert (bundle/'quota-widget.exe').is_file()
    api = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32')
    api.GetThreadDesktop.argtypes=[wintypes.DWORD]
    api.GetThreadDesktop.restype=wintypes.HANDLE
    desktop = api.GetThreadDesktop(kernel.GetCurrentThreadId())
    api.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    name = ctypes.create_unicode_buffer(256)
    assert api.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),None)
    assert name.value.startswith('QuotaTests-')
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    api.EnumDesktopWindows.argtypes=[wintypes.HANDLE,callback,wintypes.LPARAM]
    api.EnumThreadWindows.argtypes=[wintypes.DWORD,callback,wintypes.LPARAM]
    api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    api.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    api.IsWindowVisible.argtypes=[wintypes.HWND]
    with tempfile.TemporaryDirectory(prefix='quota-frozen-test-') as temp:
        root = Path(temp)
        env = {k:v for k,v in os.environ.items() if not k.startswith('AI_QUOTA_WIDGET_') and k not in ('DEEPSEEK_API_KEY','GLM_API_KEY','ZAI_API_KEY','PYTHONHOME','PYTHONPATH')}
        env.update(USERPROFILE=temp, LOCALAPPDATA=str(root/'local'), CODEX_HOME=str(root/'codex'),
                   AI_QUOTA_WIDGET_DATA_DIR=str(root/'data'), PATH=os.path.join(os.environ['SystemRoot'],'System32'),
                   PYTHONIOENCODING='utf-8')
        env.update(DEEPSEEK_API_KEY='',AI_QUOTA_WIDGET_DEEPSEEK_API_KEY='',AI_QUOTA_WIDGET_GLM_API_KEY='')
        env['PSMODULEPATH']=os.path.join(os.environ['SystemRoot'],'System32/WindowsPowerShell/v1.0/Modules')
        (root/'local').mkdir()
        (root/'data').mkdir()
        (root/'.dsh/sessions').mkdir(parents=True)
        def run(args, codes=(0,)):
            result = subprocess.run(args,env=env,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode in codes, (result.returncode,result.stdout.decode('utf-8','replace'),result.stderr.decode('utf-8','replace'))
            return result.stdout.decode('utf-8','replace')
        cli = bundle/'quota-cli.exe'
        version=run([str(cli),'--version']).strip()
        report=run([str(cli),'--doctor'],(1,))
        assert '16/16' in report and '未检测到' in report and ' 缺失' not in report, report
        run([str(cli),'--launch-check'])
        # Exercise the real frozen worker command, pipes, job object and payload.
        with patch.dict(os.environ,env,clear=True), patch.object(sys,'frozen',True,create=True), patch.object(sys,'executable',str(bundle/'quota-widget.exe')):
            worker = QueryProcess('unused','tokens')
            try:
                wait_for(lambda: worker.poll() is not None)
                result = worker.result()
                assert result['ok'] and result['data']['ds_tokens_total']==0, result
            finally:
                worker.close()
        powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        destination=root/'安装 with spaces'
        started=time.monotonic()
        install_output=run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
                           '-Destination',str(destination),'-NoLaunch','-NoShortcut'])
        install_seconds=time.monotonic()-started
        installed=destination/('v'+version)
        assert (installed/'quota-widget.exe').is_file()
        # Default install must be visible outside an agent's AppData virtualization.
        run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
             '-NoLaunch','-NoShortcut'])
        assert (root/'.ai-quota-widget-app'/('v'+version)/'quota-widget.exe').is_file()
        # Empty first run must produce diagnostics and open Chinese setup.
        startup=subprocess.STARTUPINFO()
        startup.lpDesktop='WinSta0\\'+name.value
        process=subprocess.Popen([str(installed/'quota-widget.exe')],env=env,startupinfo=startup,
                                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def windows():
            found={}
            @callback
            def visit(hwnd,_):
                pid=wintypes.DWORD()
                api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value == process.pid:
                    title=ctypes.create_unicode_buffer(256)
                    api.GetWindowTextW(hwnd,title,len(title))
                    found[title.value]=hwnd
                return True
            ctypes.set_last_error(0)
            tid=json.loads((root/'data/debug.txt').read_text(encoding='utf-8')).get('ui_thread')
            result = api.EnumThreadWindows(tid,visit,0) if tid else api.EnumDesktopWindows(desktop,visit,0)
            if not result and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            return found
        try:
            debug=root/'data/debug.txt'
            wait_for(debug.is_file)
            assert 'startup_error' not in json.loads(debug.read_text(encoding='utf-8')), debug.read_text(encoding='utf-8')
            try:
                setup=wait_for(lambda: windows().get('额度监控 · 快速设置'))
            except AssertionError:
                print(json.dumps({'pid':process.pid,'exit':process.poll(),'windows':windows(),
                                  'debug':json.loads(debug.read_text(encoding='utf-8'))},ensure_ascii=False))
                raise
            assert api.IsWindowVisible(setup)
            snapshot=json.loads(debug.read_text(encoding='utf-8'))
            assert snapshot['app_version']==version and snapshot['success_at']=={} and snapshot['active']==[]
            assert snapshot['ui_error'] is None, snapshot
            blocked = run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
                           '-Destination',str(destination),'-NoLaunch','-NoShortcut'],(1,))
            assert process.poll() is None, 'installer must not terminate a running widget'
            api.PostMessageW(setup,0x10,0,0)  # close setup = skip, without a forced key
            cfg=root/'data/config.json'
            wait_for(cfg.is_file)
            original=cfg.read_bytes()
            main=wait_for(lambda: windows().get('Quota'))
            api.PostMessageW(main,0x10,0,0)
            time.sleep(.3)
            # A second launch restores the existing window, then exits itself.
            again=subprocess.Popen([str(installed/'quota-widget.exe')],env=env,startupinfo=startup,
                                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            assert again.wait(timeout=10)==0
            wait_for(lambda: api.IsWindowVisible(main))
            assert cfg.read_bytes()==original
        finally:
            if process.poll() is None: process.terminate()
            process.wait(timeout=10)
        # Idempotent offline install must preserve personal files byte for byte.
        before=hashlib.sha256(cfg.read_bytes()).hexdigest()
        run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
             '-Destination',str(destination),'-NoLaunch','-NoShortcut'])
        assert hashlib.sha256(cfg.read_bytes()).hexdigest()==before
        license_file=installed/'LICENSE'
        license_file.write_bytes(b'fixture changed file')
        run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
             '-Destination',str(destination),'-NoLaunch','-NoShortcut'],(1,))
        assert license_file.read_bytes()==b'fixture changed file', 'must not overwrite a conflicting existing version'
        old=root/'old source'; old.mkdir()
        (old/'config.json').write_bytes(b'{"theme":"steam"}')
        (old/'deepseek-key.dpapi').write_bytes(b'not-a-real-key-fixture')
        migration = [str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(bundle/'setup.ps1'),
                     '-Destination',str(root/'migrated program'),'-ExistingDataDir',str(old),'-NoLaunch','-NoShortcut']
        run(migration)
        for filename in ('config.json','deepseek-key.dpapi'):
            assert (old/filename).read_bytes()==(root/'.ai-quota-widget'/filename).read_bytes()
        run(migration)  # identical completed migration is safe to retry
        (root/'.ai-quota-widget/config.json').write_bytes(b'{"theme":"ink"}')
        run(migration,(1,))  # newer personal data must never be replaced
        print(json.dumps(dict(version=version,offline_install_seconds=round(install_seconds,2),
            no_python_path=True,worker_pipe=True,chinese_setup=True,startup_debug=True,
            skip_setup=True,second_launch=True,config_preserved=True,migration=True,conflict_rejected=True)))


if __name__ == '__main__':
    smoke(Path(sys.argv[1]).resolve())
