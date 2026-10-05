"""Real offline upgrade engine + two frozen GUIs on a private desktop.

NewBundle must be a PRIVATE fixture with a greater version, never a public RC.
No real keys, account queries, desktop shortcuts or user data are used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if sys.argv[1:2] == ['--engine']:
    old_cli, plan, pid = sys.argv[2:]
    sys.executable = old_cli  # engine ownership points to the frozen fixture pair
    from quota_update import apply_update
    raise SystemExit(apply_update(plan, int(pid)))

from desktop_test_support import isolate_desktop
isolate_desktop()
from ctypes import wintypes
import ctypes


def wait(check, seconds=30):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=check()
        if result: return result
        time.sleep(.1)
    raise AssertionError('Update smoke deadline')


def desktop_startup():
    user=ctypes.WinDLL('user32'); kernel=ctypes.WinDLL('kernel32')
    user.GetThreadDesktop.argtypes=[wintypes.DWORD];user.GetThreadDesktop.restype=wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    name=ctypes.create_unicode_buffer(256)
    assert user.GetUserObjectInformationW(user.GetThreadDesktop(kernel.GetCurrentThreadId()),2,name,ctypes.sizeof(name),None)
    assert name.value.startswith('QuotaTests-')
    startup=subprocess.STARTUPINFO();startup.lpDesktop='WinSta0\\'+name.value
    return startup


def smoke(old_bundle, new_bundle):
    startup=desktop_startup()
    with tempfile.TemporaryDirectory(prefix='quota-update-smoke-') as temp:
        root=Path(temp); data=root/'data'; data.mkdir()
        (data/'config.json').write_text(json.dumps(dict(show_kimi=False,show_codex=False,
            show_glm=False,show_deepseek=False,show_radar=False,theme='glass')),encoding='utf-8')
        original=(data/'config.json').read_bytes()
        old_version=json.loads((old_bundle/'bundle-manifest.json').read_text())['version']
        new_version=json.loads((new_bundle/'bundle-manifest.json').read_text())['version']
        installed=root/'install'/('v'+old_version)
        shutil.copytree(old_bundle,installed)
        (installed/'.install-receipt.json').write_text(json.dumps(dict(product='AIQuotaWidget',version=old_version,shortcuts=False,registered=False)))
        env={k:v for k,v in os.environ.items() if k not in ('DEEPSEEK_API_KEY','GLM_API_KEY') and not k.startswith('AI_QUOTA_WIDGET_')}
        env.update(USERPROFILE=str(root),HOME=str(root),CODEX_HOME=str(root/'codex'),
                   AI_QUOTA_WIDGET_DATA_DIR=str(data))
        old=subprocess.Popen([str(installed/'quota-widget.exe')],env=env,startupinfo=startup)
        helper=None; new_pid=None
        stage=Path(tempfile.mkdtemp(prefix='aiquota-update-'))
        try:
            wait(lambda:(data/'debug.txt').is_file())
            assert old.poll() is None
            shutil.copytree(new_bundle,stage/'package')
            plan=stage/'pending.json';plan.write_text(json.dumps(dict(old=str(installed/'quota-widget.exe'),data=str(data))))
            helper=subprocess.Popen([sys.executable,str(Path(__file__)),'--engine',str(installed/'quota-cli.exe'),str(plan),str(old.pid)],
                                    env=env,startupinfo=startup,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            wait(lambda:(stage/'ready.json').is_file())
            # Exact test-owned parent only; never a name-based kill.
            old.terminate();old.wait(timeout=10)
            stdout,stderr=helper.communicate(timeout=60)
            assert helper.returncode==0,(stdout,stderr)
            state=json.loads((data/'debug.txt').read_text(encoding='utf-8'))
            new_pid=state['pid']
            assert state['app_version']==new_version and state['ui_error'] is None,state
            assert (data/'config.json').read_bytes()==original
            assert not stage.exists(), 'Update stage leaked'
            print(json.dumps(dict(old=old_version,new=new_version,verified_handoff=True,
                                  real_offline_install=True,frozen_gui_started=True,config_preserved=True,stage_cleaned=True)))
        finally:
            if helper and helper.poll() is None:helper.terminate();helper.wait(timeout=10)
            if old.poll() is None:old.terminate();old.wait(timeout=10)
            if new_pid:
                expected=root/'install'/('v'+new_version)/'quota-widget.exe'
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
                kernel.OpenProcess.restype=wintypes.HANDLE
                kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
                kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
                kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
                kernel.CloseHandle.argtypes=[wintypes.HANDLE]
                handle=kernel.OpenProcess(0x100000|0x1000|1,False,new_pid)
                assert handle
                try:
                    name=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(name))
                    assert kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(length))
                    assert Path(name.value).resolve()==expected.resolve()
                    assert kernel.TerminateProcess(handle,0)
                    assert kernel.WaitForSingleObject(handle,10000)==0
                finally:kernel.CloseHandle(handle)
            if stage.exists():shutil.rmtree(stage)


if __name__=='__main__':
    smoke(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
