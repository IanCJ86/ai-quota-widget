"""Stable-only updater. Network and installation never run on Tk's thread.

The old CLI waits for its own GUI to exit, installs into a new version directory,
checks startup, and restores shortcuts/old app on failure. Personal data stays put.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from app_version import APP_VERSION, USER_AGENT
from monitor_runtime import atomic_json
from quota_paths import _reject_links

REPO = 'IanCJ86/ai-quota-widget'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
ASSETS = f'https://github.com/{REPO}/releases/download/'
NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('NotStableVersion')
    return tuple(int(v) for v in value.removeprefix('v').split('.'))


def release_info(data, current=APP_VERSION):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('NotStableRelease')
    tag = data.get('tag_name')
    if version(tag) <= version(current):
        return None
    if tag != 'v' + '.'.join(map(str, version(tag))):
        raise ValueError('BadReleaseTag')
    names = (f'ai-quota-widget-{tag}-windows-x64.zip', 'SHA256SUMS.txt')
    output = dict(tag=tag)
    for key, name in zip(('zip', 'sums'), names):
        assets = [a for a in data.get('assets', []) if isinstance(a, dict) and a.get('name') == name]
        if len(assets) != 1 or assets[0].get('browser_download_url') != ASSETS + tag + '/' + name:
            raise ValueError('BadReleaseAsset')
        output[key] = assets[0]['browser_download_url']
    return output


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in (
                'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
                'objects.githubusercontent.com') or parsed.username or parsed.password:
            raise ValueError('UnsafeDownloadRedirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, target=None, limit=2 * 1024 * 1024):
    opener = urllib.request.build_opener(SafeRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    deadline = time.monotonic() + 900
    with opener.open(req, timeout=30) as response:
        result = bytearray() if target is None else None
        output = open(target, 'xb') if target is not None else None
        try:
            size = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                size += len(block)
                if size > limit or time.monotonic() > deadline:
                    raise ValueError('DownloadLimitExceeded')
                if output:
                    output.write(block)
                else:
                    result.extend(block)
        finally:
            if output:
                output.close()
        return bytes(result) if result is not None else None


def check_latest():
    return release_info(json.loads(download(API)))


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def cleanup_interrupted_download(data):
    """Reap a recorded app-owned stage only after its owning process is gone."""
    if os.name != 'nt' or not data:
        return
    pointer = Path(data) / 'update-stage.json'
    try:
        _reject_links(pointer)
        stage = Path(json.loads(pointer.read_text(encoding='utf-8'))['stage']).resolve()
        if stage.parent != Path(tempfile.gettempdir()).resolve() or not stage.name.startswith('aiquota-update-'):
            return
        if not stage.exists():
            pointer.unlink()
            return
        _reject_links(stage)
        owner = json.loads((stage / 'owner.json').read_text(encoding='utf-8'))
        if owner.get('product') != 'AIQuotaWidget' or type(owner.get('pid')) is not int or owner['pid'] <= 0:
            return
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, owner['pid'])
        if handle:
            kernel.CloseHandle(handle)
            return
        if ctypes.get_last_error() != 87:
            return  # unknown/access denied is not proof that the owner exited
        for child in stage.rglob('*'):
            _reject_links(child)
        shutil.rmtree(stage)
        pointer.unlink()
    except (OSError, ValueError, KeyError, TypeError):
        pass


def unpack_verified(archive, sums, name, destination):
    matches = re.findall(r'^([a-fA-F0-9]{64})\s+' + re.escape(name) + r'\s*$', sums, re.M)
    if len(matches) != 1 or file_hash(archive) != matches[0].lower():
        raise ValueError('DownloadChecksumMismatch')
    destination = Path(destination)
    destination.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if len(entries) > 5000 or sum(e.file_size for e in entries) > 256 * 1024 * 1024:
            raise ValueError('ArchiveLimitExceeded')
        seen = set()
        for item in entries:
            path = Path(item.filename)
            if ('\\' in item.orig_filename or '\x00' in item.orig_filename or ':' in item.filename or item.filename.startswith('/') or path.is_absolute() or
                    '..' in path.parts or (item.external_attr >> 16) & 0o170000 == 0o120000 or
                    any(part != part.rstrip(' .') or part.split('.')[0].upper() in
                        {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
                        for part in path.parts) or item.filename.casefold() in seen):
                raise ValueError('UnsafeArchivePath')
            seen.add(item.filename.casefold())
        zipped.extractall(destination)
    manifest = json.loads((destination / 'bundle-manifest.json').read_text(encoding='utf-8'))
    if name != f'ai-quota-widget-v{manifest["version"]}-windows-x64.zip':
        raise ValueError('BundleVersionMismatch')
    verify_bundle(destination)


def verify_bundle(folder):
    folder = Path(folder).resolve()
    _reject_links(folder)
    manifest = json.loads((folder / 'bundle-manifest.json').read_text(encoding='utf-8'))
    version(manifest['version'])
    files = manifest.get('files')
    if not isinstance(files, dict) or not {'quota-widget.exe', 'quota-cli.exe', 'setup.ps1'} <= files.keys():
        raise ValueError('IncompleteBundle')
    for relative, digest in files.items():
        path = folder / relative
        if path.resolve() == folder or folder not in path.resolve().parents or ':' in relative:
            raise ValueError('UnsafeManifestPath')
        _reject_links(path)
        if not isinstance(digest, str) or file_hash(path) != digest:
            raise ValueError('BundleChecksumMismatch')
    return manifest['version']


def shortcut_paths():
    if os.name != 'nt':
        return []
    output = []
    for special in (0x10, 0x02):  # actual Desktop and Start-menu Programs, including redirection
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, special, None, 0, buffer) == 0:
            output.append(Path(buffer.value) / 'AI 额度监控.lnk')
    return output


def wait_parent(pid, old, timeout=30):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # parent already exited
            return
        raise OSError('CannotVerifyParent')
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) or Path(buffer.value).resolve() != old.resolve():
            raise ValueError('WrongParentProcess')
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise TimeoutError('ParentDidNotExit')
    finally:
        kernel.CloseHandle(handle)


def trim_versions(root, keep):
    """Only installer-receipted directories; legacy/manual installs are untouched."""
    root = Path(root).resolve()
    for path in root.iterdir():
        if path.name in keep or not re.fullmatch(r'v\d+\.\d+\.\d+', path.name) or not path.is_dir():
            continue
        try:
            _reject_links(path)
            receipt = json.loads((path / '.install-receipt.json').read_text(encoding='utf-8-sig'))
            if receipt != {'product': 'AIQuotaWidget', 'version': path.name[1:]}:
                continue
            # Check every descendant before any recursive deletion.
            for child in path.rglob('*'):
                _reject_links(child)
            shutil.rmtree(path)
        except (OSError, ValueError):
            continue


def apply_update(plan_path, parent):
    plan_path = Path(plan_path).resolve()
    stage = plan_path.parent
    if stage.parent != Path(tempfile.gettempdir()).resolve() or not stage.name.startswith('aiquota-update-'):
        raise ValueError('UnsafeUpdateStage')
    _reject_links(plan_path)
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    old = Path(plan['old']).resolve()
    if old != Path(sys.executable).resolve().with_name('quota-widget.exe') or old.parent.name != 'v' + APP_VERSION:
        raise ValueError('WrongUpdateOwner')
    root = old.parent.parent
    _reject_links(root)
    package = stage / 'package'
    next_version = verify_bundle(package)
    if version(next_version) <= version(APP_VERSION):
        raise ValueError('NotAnUpgrade')
    new = root / ('v' + next_version) / 'quota-widget.exe'
    atomic_json(stage / 'owner.json', {'product': 'AIQuotaWidget', 'pid': os.getpid()})
    atomic_json(stage / 'ready.json', {'pid': os.getpid()})
    wait_parent(parent, old)
    shortcuts = {path: path.read_bytes() if path.exists() else None for path in shortcut_paths()}
    launched = None
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(package / 'setup.ps1'), '-Destination', str(root), '-NoLaunch'],
                                timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW)
        if result.returncode:
            raise RuntimeError('UpdateInstallFailed')
        subprocess.run([str(new), '--launch-check'], check=True, timeout=20, **NO_WINDOW)
        launched = subprocess.Popen([str(new)], cwd=new.parent, **NO_WINDOW)
        # Only startup is a gate. Offline/API errors must not roll back a healthy UI.
        deadline = time.monotonic() + 15
        healthy = False
        debug = Path(plan['data']) / 'debug.txt'
        while time.monotonic() < deadline and launched.poll() is None:
            try:
                state = json.loads(debug.read_text(encoding='utf-8'))
                healthy = state.get('pid') == launched.pid and state.get('app_version') == next_version and not state.get('startup_error')
            except (OSError, ValueError):
                pass
            if healthy:
                break
            time.sleep(.2)
        if not healthy:
            raise RuntimeError('UpdatedAppDidNotStart')
        trim_versions(root, {old.parent.name, new.parent.name})
        return 0
    except Exception:
        if launched and launched.poll() is None:
            # This is the exact child we started, never a process-name kill.
            launched.terminate()
            launched.wait(timeout=10)
        for path, content in shortcuts.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                temp = path.with_suffix('.update-rollback.tmp')
                temp.write_bytes(content)
                os.replace(temp, path)
        subprocess.Popen([str(old)], cwd=old.parent, **NO_WINDOW)
        ctypes.windll.user32.MessageBoxW(None, '更新未完成，已恢复旧版。个人配置和 Key 未改动。', 'AI 额度监控', 0x10)
        return 1
    finally:
        # Stage is ours, validated above; never follow a subsequently created link.
        try:
            for child in stage.rglob('*'):
                _reject_links(child)
            shutil.rmtree(stage)
        except OSError:
            pass


class UpdateController:
    def __init__(self, app, data=None):
        self.app = app
        self.data = Path(data) if data else None
        self.events = queue.SimpleQueue()
        self.busy = False
        self.available = None
        self.menu_index = None
        self.handoff = None
        self.next_check = time.monotonic() + 60
        self.enabled = bool(getattr(sys, 'frozen', False))
        if self.enabled and self.data:
            cleanup_interrupted_download(self.data)
            try:
                last = json.loads((self.data / 'update-state.json').read_text(encoding='utf-8'))['checked_at']
                remaining = last + 86400 - time.time()
                if isinstance(last, (int, float)) and 0 < remaining <= 86400:
                    self.next_check = time.monotonic() + remaining
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def request(self, check_only=False):
        if self.busy:
            return
        if not self.enabled:
            self.app.status.config(text='源码版请通过 Git 更新')
            return
        self.busy = True
        release = None if check_only else self.available
        self.app.menu.entryconfigure(self.menu_index, label='下载更新中…' if release else '检查更新中…', state='disabled')
        threading.Thread(target=self._work, args=(release,), daemon=True).start()

    def _work(self, release):
        stage = None
        try:
            if release is None:
                self.events.put(('checked', check_latest()))
                return
            stage = Path(tempfile.mkdtemp(prefix='aiquota-update-'))
            atomic_json(stage / 'owner.json', {'product': 'AIQuotaWidget', 'pid': os.getpid()})
            if self.data:
                atomic_json(self.data / 'update-stage.json', {'stage': str(stage)})
            archive = stage / 'app.zip'
            download(release['zip'], archive, limit=128 * 1024 * 1024)
            sums = download(release['sums']).decode('utf-8-sig')
            unpack_verified(archive, sums, release['zip'].rsplit('/', 1)[1], stage / 'package')
            plan = stage / 'pending.json'
            atomic_json(plan, dict(old=str(Path(sys.executable).with_name('quota-widget.exe')),
                                   data=str(self.data)))
            self.events.put(('ready', str(plan)))
        except Exception:
            if stage:
                try:
                    for child in stage.rglob('*'):
                        _reject_links(child)
                    shutil.rmtree(stage)
                except OSError:
                    pass
            self.events.put(('failed', None))

    def tick(self):
        if self.handoff:
            child, plan, deadline = self.handoff
            try:
                state = json.loads((Path(plan).parent / 'ready.json').read_text(encoding='utf-8'))
                ready = state.get('pid') == child.pid and child.poll() is None
            except (OSError, ValueError):
                ready = False
            if ready:
                self.app._quit()
                return
            if child.poll() is not None or time.monotonic() > deadline:
                if child.poll() is None:
                    child.terminate()
                self.handoff = None
                self.busy = False
                self.app.menu.entryconfigure(self.menu_index, label='更新启动失败 ·重试', state='normal')
                self.app.status.config(text='更新未启动，旧版保持运行')
            return
        if self.enabled and not self.busy and time.monotonic() >= self.next_check:
            self.next_check = time.monotonic() + 86400  # one small request/day, no toast
            self.request(check_only=True)
        while not self.events.empty():
            event, payload = self.events.get_nowait()
            self.busy = False
            if event == 'ready':
                try:
                    child = subprocess.Popen([str(Path(sys.executable).with_name('quota-cli.exe')),
                                      '--apply-update', payload, '--parent-pid', str(os.getpid())], **NO_WINDOW)
                except OSError:
                    self.app.status.config(text='无法启动更新，旧版保持运行')
                    self.app.menu.entryconfigure(self.menu_index, label='重试更新', state='normal')
                else:
                    self.busy = True
                    self.handoff = (child, payload, time.monotonic() + 25)
                return
            if event == 'checked':
                self.available = payload
                self.next_check = time.monotonic() + 86400
                if self.data:
                    try:
                        atomic_json(self.data / 'update-state.json', {'checked_at': time.time()})
                    except OSError:
                        pass
            label = ('更新到 ' + self.available['tag']) if self.available else '检查更新'
            if event == 'failed':
                label = '更新查询失败 ·重试'
            self.app.menu.entryconfigure(self.menu_index, label=label, state='normal')
