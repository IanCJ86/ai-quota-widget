"""One verified installer core, used by CLI and the PowerShell bootstrap."""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from app_version import APP_VERSION

def source_paths():
    root = Path(__file__).resolve().parent
    if (root/'runtime-files.txt').is_file():
        return root, root
    import quota_assets
    return root, Path(quota_assets.__file__).resolve().parent

def running():
    if os.name != 'nt':
        return False
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenMutexW.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
    api.OpenMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenMutexW(0x100000, False, 'Local\\IanQuotaMonitor-v2')
    if handle:
        api.CloseHandle(handle)
    return bool(handle)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(args, stage='检查'):
    # Redirected pip output otherwise uses the system ANSI codepage on Windows.
    # English Windows + a Chinese destination can fail *after* installing deps.
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    process = subprocess.run(args, capture_output=True, timeout=240,
                             env=env, creationflags=0x08000000 if os.name == 'nt' else 0)
    if process.returncode:
        # Do not echo pip output, URLs with credentials or arbitrary exception text.
        stderr=process.stderr.decode('utf-8','replace')
        categories=[name for name in ('ModuleNotFoundError','ImportError','PermissionError',
                    'UnicodeEncodeError','SSLError','ProxyError','ConnectionError','TclError') if name in stderr]
        reason='/'.join(categories) or '环境或网络错误'
        raise RuntimeError(f'{stage}失败（退出码{process.returncode}，{reason}）。请检查Python/Tk、网络和pip；原程序文件未替换。')
    return process

def install(destination=None, skip_deps=False):
    if os.name != 'nt':
        raise RuntimeError('当前安装器仅支持Windows。')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None,False,'Local\\AIQuotaWidget-Installer')
    exists = ctypes.get_last_error() == 183
    if not handle:
        raise RuntimeError('无法建立安装互斥锁，请检查本机权限。')
    try:
        if exists:
            raise RuntimeError('另一个安装任务正在运行，请等待完成。')
        return _install(destination,skip_deps)
    finally:
        kernel.CloseHandle(handle)

def _install(destination=None, skip_deps=False):
    if sys.version_info < (3,10):
        raise RuntimeError('需要Python 3.10或更新版本（包含Tk）。')
    if running():
        raise RuntimeError('额度监控仍在运行。请右键菜单“退出”后重新安装；不会强制结束进程。')
    source, assets = source_paths()
    modules = (assets/'runtime-files.txt').read_text(encoding='utf-8').splitlines()
    if not modules or len(modules) != len(set(modules)) or any(not re.fullmatch(r'[a-z_]+\.py', f) for f in modules):
        raise RuntimeError('运行文件清单无效。请重新下载完整Release。')
    entries = {name:source/name for name in modules}
    entries.update({name:assets/name for name in ('runtime-files.txt','requirements.txt','README.md','LICENSE','config.json')})
    if any(not p.is_file() for p in entries.values()):
        raise RuntimeError('安装包缺少文件。请重新下载完整Release。')
    dest = Path(destination or Path.home()/'Desktop'/'quota-widget').resolve()
    if dest == source or dest == Path.home() or dest == Path(dest.anchor):
        raise RuntimeError('请选择独立安装目录，不要覆盖源码根目录或用户根目录。')
    dest.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() or p.is_junction() if hasattr(p,'is_junction') else p.is_symlink() for p in [dest,*dest.parents]):
        raise RuntimeError('安装目录包含重解析链接，请选择普通本机目录。')
    # Transaction staging stays on the target volume. Keep previous app intact
    # through dependency checks; never copy personal files into release assets.
    with tempfile.TemporaryDirectory(prefix='.quota-stage-',dir=dest) as staging:
        stage = Path(staging)
        for name, path in entries.items():
            shutil.copy2(path, stage/name)
            if digest(path) != digest(stage/name):
                raise RuntimeError('文件校验失败，原版本保持不变。')
        python = Path(sys.executable)
        if not skip_deps:
            environment = dest/('.venv-'+APP_VERSION)
            if not (environment/'Scripts/python.exe').is_file():
                # A permanent venv must not bind itself to an ephemeral uvx venv.
                run([getattr(sys,'_base_executable',sys.executable),'-m','venv',str(environment)],stage='创建持久环境')
            python = environment/'Scripts/python.exe'
            run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(stage/'requirements.txt')],stage='安装依赖')
        run([str(python),'-c',"import sys,tkinter,PIL,pystray; assert sys.version_info >= (3,10); __import__('compression.zstd' if sys.version_info >= (3,14) else 'backports.zstd')"],stage='检查GUI与压缩运行时')
        run([str(python),'-m','py_compile',*[str(stage/n) for n in modules]],stage='检查程序模块')
        pythonw = python.with_name('pythonw.exe')
        if not pythonw.exists():
            pythonw = python
        launcher = ('@echo off\r\nchcp 65001 >nul\r\n'
                    f'"{python}" "%~dp0quota_monitor.py" --launch-check\r\n'
                    'if errorlevel 1 (pause & exit /b 2)\r\n'
                    f'start "" "{pythonw}" "%~dp0quota_monitor.py"\r\n')
        # UTF-8 after chcp supports names outside the current Windows ANSI page.
        (stage/'start.bat').write_bytes(launcher.encode('utf-8'))
        entries['start.bat'] = stage/'start.bat'
        originals = {}
        changed = []
        try:
            if running():
                raise RuntimeError('安装期间检测到程序启动。请退出后再试。')
            for name in entries:
                target = dest/name
                if name == 'config.json' and target.exists():
                    continue
                if target.is_symlink():
                    raise RuntimeError('目标文件为链接，拒绝覆盖。')
                originals[name] = target.read_bytes() if target.exists() else None
                os.replace(stage/name, target)
                changed.append(name)
                expected = hashlib.sha256(launcher.encode()).hexdigest() if name == 'start.bat' else digest(entries[name])
                if digest(target) != expected:
                    raise RuntimeError('安装后校验失败。')
        except Exception:
            for name in reversed(changed):
                target = dest/name
                if originals[name] is None:
                    target.unlink(missing_ok=True)
                else:
                    restore = stage/(name+'.restore')
                    restore.write_bytes(originals[name])
                    os.replace(restore, target)
            raise
    return f'安装完成：{len(modules)}/{len(modules)}运行模块已校验。个人配置保留。运行start.bat启动。'
