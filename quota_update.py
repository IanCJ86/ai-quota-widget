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
from quota_network import stream, NetworkError, error_code, retry_after, strip_proxy_auth
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
                'objects.githubusercontent.com') or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('UnsafeDownloadRedirect')
        return strip_proxy_auth(super().redirect_request(req, fp, code, msg, headers, newurl))


def download_worker():
    """Internal pipe-only helper. DNS/connect/read can all be killed by its owner."""
    import base64
    output = None
    try:
        data = json.loads(sys.stdin.buffer.readline(16385))
        url, target = data['url'], data.get('target')
        if url != API and not url.startswith(ASSETS):
            raise NetworkError('UnsafeRedirect')
        if target:
            _reject_links(Path(target))
            path = Path(target).resolve()
            if (path.parent.parent != Path(tempfile.gettempdir()).resolve() or
                    not path.parent.name.startswith('aiquota-update-') or path.name != 'app.zip'):
                raise ValueError('UnsafeUpdateStage')
            _reject_links(path)
            output = path.open('xb')
        last = [0]
        def progress(size):
            if time.monotonic()-last[0] >= 1:
                print(json.dumps({'bytes': size}), flush=True)
                last[0] = time.monotonic()
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        raw = stream(req, data.get('config', {}), 'updates', limit=data['limit'],
                     budget=data['budget'], output=output, progress=progress if target else None,
                     redirect=SafeRedirect())
        result = dict(ok=True, body=base64.b64encode(raw).decode('ascii'))
    except Exception as exc:
        result = dict(ok=False, error=error_code(exc))
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            result['retry_after'] = retry_after(exc.headers)
    finally:
        if output:
            output.close()
    print(json.dumps(result), flush=True)


def download(url, target=None, limit=2 * 1024 * 1024, *, config=None, cancel=None, progress=None):
    import base64
    from monitor_runtime import KillJob
    from quota_network import settings
    budget = 600 if target else 20
    safe_config = {'network': settings(config or {})}
    if getattr(sys, 'frozen', False):
        command = [str(Path(sys.executable).with_name('quota-cli.exe')), '--network-download']
    else:
        command = [sys.executable, str(Path(__file__).parent/'packaging/cli_entry.py'), '--network-download']
    process = None
    job = KillJob()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, **NO_WINDOW)
        job.assign(process)
        request = json.dumps(dict(url=url, target=str(target) if target else None,
                limit=limit, budget=budget, config=safe_config)).encode('utf-8')+b'\n'
        deadline = time.monotonic()+budget+3
        last_progress = -1
        while True:
            if cancel and cancel.is_set():
                raise NetworkError('Cancelled')
            if time.monotonic() >= deadline:
                raise NetworkError('Timeout')
            try:
                stdout, _ = process.communicate(request, timeout=.2)
                break
            except subprocess.TimeoutExpired as exc:
                request = None
                if progress and exc.output:
                    lines = exc.output.splitlines()
                    for line in reversed(lines[-3:]):
                        try:
                            count = json.loads(line).get('bytes')
                            if isinstance(count, int) and count > last_progress:
                                progress(count)
                                last_progress = count
                                break
                        except (ValueError, TypeError):
                            pass
        result = json.loads(stdout.splitlines()[-1])
        if not result.get('ok'):
            error = NetworkError(result.get('error', 'ConnectionError'))
            error.retry_after = result.get('retry_after', 0)
            raise error
        return base64.b64decode(result['body'], validate=True) if target is None else None
    finally:
        job.close()
        if process:
            if process.poll() is None:
                process.kill()
            process.communicate()


def check_latest(**options):
    return release_info(json.loads(download(API, **options)))


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
            if receipt.get('product') != 'AIQuotaWidget' or receipt.get('version') != path.name[1:]:
                continue
            # Check every descendant before any recursive deletion.
            for child in path.rglob('*'):
                _reject_links(child)
            shutil.rmtree(path)
        except (OSError, ValueError):
            continue


REGISTRATION = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\AIQuotaWidget'


def registration_snapshot(root):
    """Snapshot only this app's non-secret uninstall metadata for rollback."""
    import winreg
    root = Path(root)
    files = {}
    for name in ('uninstall.ps1', '.install-root.json'):
        path = root / name
        _reject_links(path)
        if path.exists() and path.stat().st_size > 1024 * 1024:
            raise ValueError('OversizedRegistrationMetadata')
        files[name] = path.read_bytes() if path.exists() else None
    values = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRATION) as key:
            if Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).resolve() != root.resolve():
                return files, 'foreign'
            values = []
            for i in range(winreg.QueryInfoKey(key)[1]):
                values.append(winreg.EnumValue(key, i))
    except FileNotFoundError:
        pass
    return files, values


def restore_registration(root, snapshot):
    import winreg
    files, values = snapshot
    for name, content in files.items():
        path = Path(root) / name
        _reject_links(path)
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)
    if values == 'foreign':
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRATION) as key:
            if Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).resolve() != Path(root).resolve():
                return
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRATION)
    except FileNotFoundError:
        pass
    if values is not None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRATION) as key:
            for name, value, kind in values:
                winreg.SetValueEx(key, name, 0, kind, value)


def apply_update(plan_path, parent):
    plan_path = Path(plan_path).resolve()
    stage = plan_path.parent
    if stage.parent != Path(tempfile.gettempdir()).resolve() or not stage.name.startswith('aiquota-update-'):
        raise ValueError('UnsafeUpdateStage')
    _reject_links(plan_path)
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    old = Path(plan['old']).resolve()
    if old != Path(sys.executable).resolve().with_name('quota-widget.exe'):
        raise ValueError('WrongUpdateOwner')
    try:
        receipt = json.loads((old.parent / '.install-receipt.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        receipt = {}
    managed = (old.parent.name == 'v' + APP_VERSION and receipt.get('product') == 'AIQuotaWidget'
               and receipt.get('version') == APP_VERSION)
    root = old.parent.parent if managed else Path(os.environ['USERPROFILE']) / '.ai-quota-widget-app'
    shortcuts_enabled = managed and receipt.get('shortcuts', True)
    registration_enabled = managed and receipt.get('registered', True)
    _reject_links(root)
    package = stage / 'package'
    next_version = verify_bundle(package)
    if version(next_version) <= version(APP_VERSION):
        raise ValueError('NotAnUpgrade')
    new = root / ('v' + next_version) / 'quota-widget.exe'
    # Any snapshot failure happens while the old GUI is STILL running.
    shortcuts = {path: path.read_bytes() if path.exists() else None for path in shortcut_paths()} if shortcuts_enabled else {}
    registration = registration_snapshot(root) if registration_enabled else None
    atomic_json(stage / 'owner.json', {'product': 'AIQuotaWidget', 'pid': os.getpid()})
    atomic_json(stage / 'ready.json', {'pid': os.getpid()})
    wait_parent(parent, old)
    launched = None
    try:
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', str(package / 'setup.ps1'), '-Destination', str(root), '-NoLaunch']
        if not shortcuts_enabled:
            command.append('-NoShortcut')
        if not registration_enabled:
            command.append('-NoRegistration')
        result = subprocess.run(command,
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
        if registration is not None:
            restore_registration(root, registration)
        subprocess.Popen([str(old)], cwd=old.parent, **NO_WINDOW)
        ctypes.windll.user32.MessageBoxW(None, '更新未完成，已恢复旧版。个人配置和 Key 未改动。', 'AI 额度监控', 0x10)
        return 1
    finally:
        # Stage is ours, validated above; never follow a subsequently created link.
        try:
            _reject_links(stage)
            for child in stage.rglob('*'):
                _reject_links(child)
            shutil.rmtree(stage)
            pointer = Path(plan['data']) / 'update-stage.json'
            if pointer.is_file():
                _reject_links(pointer)
                if json.loads(pointer.read_text(encoding='utf-8')).get('stage') == str(stage):
                    pointer.unlink()
        except (OSError, ValueError):
            pass


class UpdateController:
    def __init__(self, app, data=None, config=None):
        self.app = app
        self.data = Path(data) if data else None
        self.events = queue.SimpleQueue()
        self.busy = False
        self.available = None
        self.menu_index = None
        self.handoff = None
        self.config = config if config is not None else {}
        self.cancel = threading.Event()
        self.failures = 0
        self.last_error = None
        self.reschedule_after_cancel = False
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
            if not self.handoff:
                self.cancel.set()
            return
        if not self.enabled:
            self.app.status.config(text='源码版请通过 Git 更新')
            return
        self.busy = True
        self.cancel.clear()
        release = None if check_only else self.available
        self.app.menu.entryconfigure(self.menu_index, label='下载中 ·点击取消' if release else '检查中 ·点击取消', state='normal')
        threading.Thread(target=self._work, args=(release,), daemon=True).start()

    def _work(self, release):
        stage = None
        phase = 'check'
        import copy
        config = {'network': copy.deepcopy(self.config.get('network', {}))}
        try:
            if release is None:
                self.events.put(('checked', check_latest(config=config, cancel=self.cancel)))
                return
            phase = 'download'
            stage = Path(tempfile.mkdtemp(prefix='aiquota-update-'))
            atomic_json(stage / 'owner.json', {'product': 'AIQuotaWidget', 'pid': os.getpid()})
            if self.data:
                atomic_json(self.data / 'update-stage.json', {'stage': str(stage)})
            archive = stage / 'app.zip'
            download(release['zip'], archive, limit=128 * 1024 * 1024, config=config, cancel=self.cancel,
                     progress=lambda size: self.events.put(('progress', size)))
            sums = download(release['sums'], config=config, cancel=self.cancel).decode('utf-8-sig')
            phase = 'verify'
            unpack_verified(archive, sums, release['zip'].rsplit('/', 1)[1], stage / 'package')
            if self.cancel.is_set():
                raise NetworkError('Cancelled')
            plan = stage / 'pending.json'
            atomic_json(plan, dict(old=str(Path(sys.executable).with_name('quota-widget.exe')),
                                   data=str(self.data)))
            self.events.put(('ready', str(plan)))
        except Exception as exc:
            if stage:
                try:
                    _reject_links(stage)
                    for child in stage.rglob('*'):
                        _reject_links(child)
                    shutil.rmtree(stage)
                    pointer = self.data / 'update-stage.json' if self.data else None
                    if pointer and pointer.is_file():
                        _reject_links(pointer)
                        if json.loads(pointer.read_text(encoding='utf-8')).get('stage') == str(stage):
                            pointer.unlink()
                except (OSError, ValueError):
                    pass
            self.events.put(('failed', dict(phase=phase, error=error_code(exc),
                                           retry_after=getattr(exc, 'retry_after', 0))))

    def network_changed(self):
        if not self.handoff:
            self.reschedule_after_cancel = self.busy
            self.cancel.set()
            self.next_check = time.monotonic()

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
            self.next_check = time.monotonic() + 86400
            self.request(check_only=True)
        while not self.events.empty():
            event, payload = self.events.get_nowait()
            if event == 'progress':
                self.app.menu.entryconfigure(self.menu_index, label=f'已下载 {payload/1048576:.1f}MB ·点击取消')
                continue
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
                self.failures = 0
                self.last_error = None
                self.available = payload
                self.next_check = time.monotonic() + 86400
                if self.data:
                    try:
                        atomic_json(self.data / 'update-state.json', {'checked_at': time.time()})
                    except OSError:
                        pass
            label = ('更新到 ' + self.available['tag']) if self.available else '检查更新'
            if event == 'failed':
                self.failures += 1
                # Three short retries, then daily budget. No unlimited retry loop.
                delay = (1 if self.reschedule_after_cancel else 86400) if payload['error'] == 'Cancelled' else (60, 300, 900, 86400)[min(self.failures-1, 3)]
                self.reschedule_after_cancel = False
                self.next_check = time.monotonic()+max(delay, payload.get('retry_after', 0))
                self.last_error = payload
                phase = {'check':'检查', 'download':'下载', 'verify':'校验'}[payload['phase']]
                label = '已取消 ·重试' if payload['error'] == 'Cancelled' else f'更新{phase}失败 ·重试'
                from quota_state import error_label
                self.app.status.config(text='旧版保持运行 ·' + error_label(payload['error']))
            self.app.menu.entryconfigure(self.menu_index, label=label, state='normal')
            if hasattr(self.app, '_write_debug'):
                self.app._write_debug()
