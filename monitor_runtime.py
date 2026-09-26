"""Bounded, independent query processes. No network or GUI work in the scheduler."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def atomic_json(path, value):
    """Keep the previous file intact if serialization/replacement fails."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(name, data):
    """Call CryptProtectData/CryptUnprotectData for the current Windows user.

    Returns None on any failure (non-Windows, empty input, API error) so callers
    can decide what to do instead of silently storing a plaintext secret.
    """
    if os.name != "nt" or not data:
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        call = getattr(crypt32, name)
        call.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(_DataBlob)]
        call.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        source = ctypes.create_string_buffer(data, len(data))
        in_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DataBlob()
        if not call(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))
    except Exception:
        return None


def dpapi_protect(secret):
    """Encrypt a secret (str/bytes) for the current user; None when unavailable."""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return _dpapi("CryptProtectData", bytes(secret or b""))


def dpapi_unprotect(blob):
    """Decrypt a blob produced by dpapi_protect; None when unavailable/corrupt."""
    return _dpapi("CryptUnprotectData", bytes(blob or b""))


class KillJob:
    """Windows closes the entire owned query tree, even if the GUI crashes."""
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            err = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(err)

    def assign(self, process):
        if self.handle and not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class SingleInstance:
    """Second launch asks the existing window to show, then exits."""
    def __init__(self, name):
        self.mutex = self.event = None
        self.existing = False
        if os.name != "nt":
            return
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        for method in ("CreateMutexW", "CreateEventW"):
            getattr(self.api, method).restype = wintypes.HANDLE
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.SetEvent.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.mutex = self.api.CreateMutexW(None, False, "Local\\" + name)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.existing = ctypes.get_last_error() == 183
        self.event = self.api.CreateEventW(None, False, False, "Local\\" + name + "-show")
        if not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if self.existing:
            self.api.SetEvent(self.event)

    def requested(self):
        return bool(self.event and self.api.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        for attr in ("event", "mutex"):
            handle = getattr(self, attr)
            if handle:
                self.api.CloseHandle(handle)
                setattr(self, attr, None)


PERCENT_KEYS = {
    "kimi": ("k5_pct", "kw_pct"), "codex": ("c5_pct", "cw_pct"),
    "glm": ("g5_pct", "gw_pct"), "main": ("cr_main24", "cr_main48"),
    "community": ("cr_resets_pct",),
    # Pay-as-you-go accounts have no percentage quota; they report money.
    "deepseek": (),
}

# Sources that report amounts instead of (or in addition to) percentages.
REQUIRED_KEYS = {"deepseek": ("ds_balance",)}


def validate_result(name, data):
    if not isinstance(data, dict):
        raise ValueError("invalid response")
    values = [data.get(key) for key in PERCENT_KEYS[name]]
    for value in values:
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not 0 <= value <= 100):
            raise ValueError("invalid percentage")
    for key in REQUIRED_KEYS.get(name, ()):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("invalid amount")
    # Explicitly no active community watch is valid data, not a network error.
    if all(value is None for value in values) and not REQUIRED_KEYS.get(name) and not (
            name == "community" and data.get("cr_resets_mode") == "no_watch"):
        raise ValueError("missing quota/probability")
    return data


class QueryProcess:
    def __init__(self, script, name):
        self.process = None
        self.job = KillJob()
        try:
            executable = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
            self.process = subprocess.Popen(
                [executable, "-u", script, "--query", name], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            # Worker cannot start network/spawn Codex before ownership is secured.
            self.job.assign(self.process)
            self.process.stdin.write(b"go\n")
            self.process.stdin.close()
        except Exception:
            self.close()
            raise

    def poll(self):
        return self.process.poll()

    def result(self):
        # A descendant must not keep the stdout pipe open after its worker exits.
        self.job.close()
        return json.loads(self.process.stdout.read(32768).decode("utf-8"))

    def close(self):
        self.job.close()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            if os.name == "nt":
                # Popen may cache the exit code before Windows signals complete teardown.
                self.job.api.WaitForSingleObject(int(self.process._handle), 1000)
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()


class Scheduler:
    """At most two workers; each attempt has a hard deadline; one schedule/source."""
    def __init__(self, script, on_result, interval=900, factory=QueryProcess,
                 monotonic=time.monotonic, wall=time.time):
        self.script, self.on_result, self.interval = script, on_result, interval
        self.factory, self.monotonic, self.wall = factory, monotonic, wall
        self.states = {}
        self.closed = False
        self.last_mono, self.last_wall = monotonic(), wall()

    def configure(self, names):
        for name in list(self.states):
            if name not in names:
                state = self.states.pop(name)
                if state.get("worker"):
                    state["worker"].close()
        for name in names:
            self.states.setdefault(name, dict(due=0, attempt=0, worker=None))

    def refresh(self):
        # Repeated clicks cannot spawn duplicates or reset active timeouts.
        for state in self.states.values():
            if state["worker"] is None:
                state.update(due=0, attempt=0)

    @property
    def active(self):
        return any(s["worker"] is not None for s in self.states.values())

    def _finish(self, name, state, payload, now):
        worker = state["worker"]
        state["worker"] = None
        if worker:
            worker.close()
        if payload.get("ok"):
            try:
                validate_result(name, payload.get("data"))
            except (ValueError, TypeError):
                payload = dict(ok=False, error="InvalidResponse", retryable=True)
        success = bool(payload.get("ok"))
        if success:
            state.update(attempt=0, due=now + self.interval)
        elif payload.get("retryable", True) and state["attempt"] < 3:
            state["due"] = now + (2 if state["attempt"] == 1 else 5)
        else:
            # Exhausted rounds back off five minutes; auth errors wait normal interval.
            state.update(attempt=0, due=now + (300 if payload.get("retryable", True) else self.interval))
        state["error"] = None if success else payload.get("error", "QueryFailed")
        self.on_result(name, payload, dict(
            duration_seconds=round(now - state.get("started", now), 2),
            retry_in_seconds=round(state["due"] - now),
            attempt=state.get("last_attempt", 0)))

    def tick(self):
        if self.closed:
            return
        now, wall = self.monotonic(), self.wall()
        # Windows monotonic clocks can exclude suspend time. Detect that separately.
        suspended = max(0, (wall - self.last_wall) - (now - self.last_mono))
        self.last_mono, self.last_wall = now, wall
        if suspended > 30:
            for state in self.states.values():
                state["due"] -= suspended
                if state["worker"]:
                    state["started"] -= suspended
        for name, state in list(self.states.items()):
            worker = state["worker"]
            if worker is None:
                continue
            timeout = 65 if name == "kimi" else 50 if name == "codex" else 25
            if now - state["started"] >= timeout:
                self._finish(name, state, dict(ok=False, error="Timeout", retryable=True), now)
            elif worker.poll() is not None:
                try:
                    payload = worker.result()
                    if not isinstance(payload, dict):
                        raise ValueError()
                except Exception:
                    payload = dict(ok=False, error="WorkerFailed", retryable=True)
                self._finish(name, state, payload, now)
        capacity = 2 - sum(s["worker"] is not None for s in self.states.values())
        for name, state in self.states.items():
            if capacity <= 0:
                break
            if state["worker"] is not None or state["due"] > now:
                continue
            state["attempt"] += 1
            state.update(started=now, last_attempt=state["attempt"])
            try:
                state["worker"] = self.factory(self.script, name)
                capacity -= 1
            except Exception:
                self._finish(name, state, dict(ok=False, error="StartFailed", retryable=True), now)

    def close(self):
        self.closed = True
        for state in self.states.values():
            if state["worker"]:
                state["worker"].close()
                state["worker"] = None
