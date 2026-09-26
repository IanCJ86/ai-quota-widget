import ctypes
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter
from tkinter import font as tkfont
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import monitor_runtime as runtime
import quota_monitor as monitor

# zstd is stdlib from 3.14 (compression.zstd) and otherwise a third-party module;
# the local-token test is skipped where neither is available.
try:
    from compression import zstd as _zstd

    HAVE_ZSTD = True
    zstd_compress = _zstd.compress
except Exception:
    try:
        import zstandard as _zstandard

        HAVE_ZSTD = True
        zstd_compress = _zstandard.ZstdCompressor().compress
    except Exception:
        HAVE_ZSTD = False

        def zstd_compress(data):
            raise RuntimeError("no zstd support")


class Clock:
    def __init__(self):
        self.now, self.wall = 1000., 10000.
    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds


class Worker:
    def __init__(self, script, name):
        self.name, self.done, self.closed = name, False, False
        self.payload = {"ok": True, "data": {runtime.PERCENT_KEYS[name][0]: 75}}
    def poll(self):
        return 0 if self.done else None
    def result(self):
        return self.payload
    def close(self):
        self.closed = True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.results = []
        self.scheduler = runtime.Scheduler("unused", lambda *args: self.results.append(args),
                                           factory=Worker, monotonic=lambda: self.clock.now,
                                           wall=lambda: self.clock.wall)
    def test_independent_results_and_bounded_concurrency(self):
        s = self.scheduler
        s.configure(["codex", "kimi", "main", "glm"])
        s.tick()
        self.assertEqual(sum(x["worker"] is not None for x in s.states.values()), 2)
        s.states["kimi"]["worker"].done = True
        s.tick()
        self.assertEqual(self.results[0][0], "kimi")
        self.assertIsNotNone(s.states["main"]["worker"])
        self.assertIsNone(s.states["glm"]["worker"])
    def test_three_attempts_then_backoff_and_recovery(self):
        s = self.scheduler
        s.configure(["codex"])
        for attempt, delay in ((1, 2), (2, 5), (3, 300)):
            s.tick()
            worker = s.states["codex"]["worker"]
            worker.done = True
            worker.payload = {"ok": False, "error": "Timeout"}
            s.tick()
            self.assertTrue(worker.closed)
            self.assertEqual(self.results[-1][2]["attempt"], attempt)
            self.assertEqual(s.states["codex"]["due"] - self.clock.now, delay)
            self.clock.advance(delay)
        s.tick()
        s.states["codex"]["worker"].done = True
        s.tick()
        self.assertTrue(self.results[-1][1]["ok"])
        self.assertEqual(s.states["codex"]["due"] - self.clock.now, 900)
    def test_auth_error_does_not_hammer_endpoint(self):
        s = self.scheduler
        s.configure(["kimi"])
        s.tick()
        w = s.states["kimi"]["worker"]
        w.done = True
        w.payload = {"ok": False, "error": "HTTP401", "retryable": False}
        s.tick()
        self.assertEqual(s.states["kimi"]["due"] - self.clock.now, 900)
    def test_hard_timeout_and_no_duplicate_manual_refresh(self):
        s = self.scheduler
        s.configure(["codex"])
        s.tick()
        w = s.states["codex"]["worker"]
        for _ in range(20):
            s.refresh()
            s.tick()
        self.assertIs(s.states["codex"]["worker"], w)
        self.assertEqual(s.states["codex"]["attempt"], 1)
        self.clock.advance(51)
        s.tick()
        self.assertTrue(w.closed)
        self.assertEqual(self.results[-1][1]["error"], "Timeout")
    def test_resume_without_monotonic_advance_expires_worker(self):
        s = self.scheduler
        s.configure(["codex"])
        s.tick()
        w = s.states["codex"]["worker"]
        self.clock.wall += 3600
        s.tick()
        self.assertTrue(w.closed)
    def test_resume_refreshes_idle_source_and_backward_clock_is_safe(self):
        s = self.scheduler
        s.configure(["codex"])
        s.tick()
        s.states["codex"]["worker"].done = True
        s.tick()
        self.clock.wall -= 3600
        s.tick()
        self.assertFalse(s.active)
        self.clock.wall += 7200
        s.tick()
        self.assertTrue(s.active)
    def test_disable_and_quit_reap_active_workers(self):
        s = self.scheduler
        s.configure(["codex", "kimi"])
        s.tick()
        workers = [x["worker"] for x in s.states.values()]
        s.configure(["codex"])
        self.assertTrue(workers[1].closed)
        s.close()
        self.assertTrue(workers[0].closed)
        s.tick()
        self.assertFalse(s.active)
    def test_malformed_success_retries_not_treated_as_fresh(self):
        s = self.scheduler
        s.configure(["codex"])
        s.tick()
        w = s.states["codex"]["worker"]
        w.done, w.payload = True, {"ok": True, "data": {"cw_pct": None}}
        s.tick()
        self.assertFalse(self.results[-1][1]["ok"])

    def test_successful_source_refreshes_automatically_at_next_interval(self):
        s = self.scheduler
        s.configure(["codex"])
        s.tick()
        first = s.states["codex"]["worker"]
        first.done = True
        s.tick()
        self.clock.advance(899)
        s.tick()
        self.assertFalse(s.active)
        self.clock.advance(1)
        s.tick()
        self.assertTrue(s.active)
        self.assertIsNot(s.states["codex"]["worker"], first)


class DataTests(unittest.TestCase):
    def test_percentage_validation(self):
        for value in (0, 1, 75, 100):
            runtime.validate_result("codex", {"cw_pct": value})
        for value in (-1, 101, float("nan"), True, "75"):
            with self.assertRaises(ValueError):
                runtime.validate_result("codex", {"cw_pct": value})
        # A source must report something: an empty payload is a failure.
        with self.assertRaises(ValueError):
            runtime.validate_result("codex", {"cw_pct": None})
        with self.assertRaises(ValueError):
            runtime.validate_result("main", {})
    def test_atomic_write_failure_keeps_previous_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            runtime.atomic_json(path, {"cw_pct": 75})
            with self.assertRaises(ValueError):
                runtime.atomic_json(path, {"cw_pct": float("nan")})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"cw_pct": 75})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
    def test_codex_five_hour_never_becomes_weekly_and_optional_plan_failure(self):
        result = {"rateLimitsByLimitId": {"codex": {"primary": {
            "usedPercent": 12, "windowDurationMins": 300, "resetsAt": 123}}},
            "rateLimits": {"secondary": {"usedPercent": 99, "windowDurationMins": 10080}}}
        p = Mock()
        p.stdin = io.StringIO()
        p.stdout = io.StringIO("\n".join(json.dumps(x) for x in [
            {"id": 0, "result": {}}, {"id": 1, "result": result},
            {"id": 2, "error": {"message": "unavailable"}}]))
        with patch.object(monitor.subprocess, "Popen", return_value=p):
            data = monitor.fetch_codex()
        self.assertEqual(data["c5_pct"], 88)
        self.assertIsNone(data["cw_pct"])
        p.kill.assert_called_once()

    def _codex_proc(self, result):
        p = Mock()
        p.stdin = io.StringIO()
        p.stdout = io.StringIO("\n".join(json.dumps(x) for x in [
            {"id": 0, "result": {}}, {"id": 1, "result": result},
            {"id": 2, "error": {"message": "unavailable"}}]))
        return p

    def test_codex_reset_credits(self):
        result = {
            "rateLimitsByLimitId": {"codex": {"primary": {
                "usedPercent": 14, "windowDurationMins": 10080,
                "resetsAt": int(time.time()) + 3600}}},
            "rateLimitResetCredits": {"availableCount": 2, "credits": [
                {"status": "available", "title": "Full reset", "expiresAt": 1792700757},
                {"status": "available", "expiresAt": 1790000000},
                {"status": "used", "expiresAt": 1780000000}]},
        }
        with patch.object(monitor.subprocess, "Popen",
                          return_value=self._codex_proc(result)):
            data = monitor.fetch_codex()
        self.assertEqual(data["cr_credit_count"], 2)
        self.assertEqual(data["cr_credit_expiry"], 1790000000)   # soonest first
        runtime.validate_result("codex", data)

    def test_codex_runtime_prefers_newest_versioned_binary(self):
        """An outdated bin\\codex.exe must not shadow the runtime in use.

        The old CLI (found on this machine: 0.130 vs 0.158) has no reset
        credits either, so the row stayed empty."""
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            legacy = bin_dir / "codex.exe"
            old = bin_dir / "aaaa" / "codex.exe"
            new = bin_dir / "bbbb" / "codex.exe"
            for path in (legacy, old, new):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            os.utime(legacy, (1_600_000_000, 1_600_000_000))
            os.utime(old, (1_700_000_000, 1_700_000_000))
            os.utime(new, (1_800_000_000, 1_800_000_000))

            with patch.object(monitor, "CODEX_BIN_DIR", str(bin_dir)), \
                    patch.object(monitor, "CODEX_EXE_CANDIDATES", [str(legacy)]):
                self.assertEqual(monitor._find_codex_exe(), str(new))   # newest wins
                new.unlink()
                self.assertEqual(monitor._find_codex_exe(), str(old))
                old.unlink()
                self.assertEqual(monitor._find_codex_exe(), str(legacy))  # fallback
                legacy.unlink()
                self.assertEqual(monitor._find_codex_exe(), "codex")     # PATH

    def test_day_formatting(self):
        self.assertEqual(monitor._fmt_day("2026-09-24"), "09-24")
        self.assertEqual(monitor._fmt_day(1792700757),
                         time.strftime("%m-%d", time.localtime(1792700757)))
        self.assertEqual(monitor._fmt_day(None), "")

    def test_codex_window_that_already_reset_is_declared(self):
        """The app-server has no capture time, so an ended window is the only
        freshness signal; the payload must say so instead of hiding it."""
        def payload(resets_at):
            node = {"usedPercent": 12, "windowDurationMins": 10080}
            if resets_at is not None:
                node["resetsAt"] = resets_at
            return {"rateLimitsByLimitId": {"codex": {"primary": node}}}

        with patch.object(monitor.subprocess, "Popen",
                          return_value=self._codex_proc(payload(int(time.time()) + 3600))):
            fresh = monitor.fetch_codex()
        with patch.object(monitor.subprocess, "Popen",
                          return_value=self._codex_proc(payload(int(time.time()) - 60))):
            ended = monitor.fetch_codex()
        with patch.object(monitor.subprocess, "Popen",
                          return_value=self._codex_proc(payload(None))):
            unknown = monitor.fetch_codex()

        self.assertFalse(fresh["c_window_expired"])
        self.assertTrue(ended["c_window_expired"])
        self.assertEqual(ended["cw_pct"], 88)      # value kept, but marked
        self.assertFalse(unknown["c_window_expired"])  # unknown is not "ended"


class SecretTests(unittest.TestCase):
    """Provider keys must never end up on disk as plaintext."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "glm-key.dpapi"
        self.deepseek_key_file = Path(self.tmp.name) / "deepseek-key.dpapi"
        self.patches = [patch.object(monitor, "GLM_KEY_FILE", str(self.key_file)),
                        patch.object(monitor, "DEEPSEEK_KEY_FILE",
                                     str(self.deepseek_key_file)),
                        patch.object(monitor, "CFG", dict(monitor.DEFAULT_CONFIG)),
                        patch.object(monitor, "_save_config")]
        for item in self.patches:
            item.start()
        # Some sessions (locked-down CI, non-interactive service accounts) have
        # no usable DPAPI; only the tests that need real encryption skip.
        self.dpapi = runtime.dpapi_protect(b"probe") is not None
    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()
    def require_dpapi(self):
        if os.name != "nt" or not self.dpapi:
            self.skipTest("Windows DPAPI unavailable in this session")

    def test_resolution_order_env_then_encrypted_then_legacy(self):
        self.require_dpapi()
        monitor.CFG["glm_api_key"] = "sk-legacy"
        self.assertEqual(monitor.glm_api_key(), "sk-legacy")
        self.assertTrue(monitor.save_glm_key("sk-encrypted"))
        self.assertEqual(monitor.CFG["glm_api_key"], "")   # plaintext copy dropped
        self.assertEqual(monitor.glm_api_key(), "sk-encrypted")
        with patch.dict(os.environ, {monitor.GLM_KEY_ENV: "sk-env"}):
            self.assertEqual(monitor.glm_api_key(), "sk-env")

    def test_stored_key_is_encrypted_on_disk(self):
        self.require_dpapi()
        self.assertTrue(monitor.save_glm_key("sk-secret-value"))
        raw = self.key_file.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-value", raw)
        self.assertEqual(json.loads(raw)["scheme"], "dpapi")
        self.assertEqual(monitor.glm_api_key(), "sk-secret-value")

    def test_save_refuses_to_fall_back_to_plaintext(self):
        with patch.object(monitor, "dpapi_protect", return_value=None):
            self.assertFalse(monitor.save_glm_key("sk-secret-value"))
        self.assertFalse(self.key_file.exists())
        self.assertEqual(monitor.CFG["glm_api_key"], "")

    def test_clear_removes_both_copies(self):
        self.require_dpapi()
        monitor.CFG["glm_api_key"] = "sk-legacy"
        self.assertTrue(monitor.save_glm_key("sk-encrypted"))
        self.assertTrue(monitor.clear_glm_key())
        self.assertFalse(self.key_file.exists())
        self.assertEqual(monitor.CFG["glm_api_key"], "")
        self.assertEqual(monitor.glm_api_key(), "")

    def test_dpapi_round_trip(self):
        self.require_dpapi()
        blob = runtime.dpapi_protect("sk-round-trip")
        self.assertIsNotNone(blob)
        self.assertEqual(runtime.dpapi_unprotect(blob).decode("utf-8"), "sk-round-trip")
        self.assertIsNone(runtime.dpapi_unprotect(b"not a blob"))

    def test_fetch_glm_uses_the_resolved_key(self):
        seen = {}

        class Response(io.StringIO):
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            seen["auth"] = req.get_header("Authorization")
            return Response(json.dumps({"limits": [
                {"type": "TOKENS_LIMIT", "remaining_percent": 80, "reset_time": 1000},
                {"type": "TOKENS_LIMIT", "remaining_percent": 50, "reset_time": 2000}]}))

        with patch.dict(os.environ, {monitor.GLM_KEY_ENV: "sk-env"}), \
                patch.object(monitor.urllib.request, "urlopen", side_effect=fake_urlopen):
            data = monitor.fetch_glm()
        self.assertEqual(seen["auth"], "sk-env")
        self.assertEqual((data["g5_pct"], data["gw_pct"]), (80, 50))

    def test_deepseek_key_resolution_and_secure_save(self):
        """DeepSeek reuses the encrypted store and accepts DEEPSEEK_API_KEY."""
        blank = {monitor.DEEPSEEK_ENV: "", monitor.DEEPSEEK_KEY_ENV: ""}
        with patch.object(monitor, "_windows_env", return_value=""), \
                patch.dict(os.environ, blank):
            self.assertEqual(monitor.deepseek_api_key(), "")   # nothing configured
            self.assertEqual(monitor.fetch_deepseek(), {})     # no key, no request
        with patch.object(monitor, "_windows_env", return_value=""), \
                patch.dict(os.environ, dict(blank, **{monitor.DEEPSEEK_ENV: "sk-cli-env"})):
            self.assertEqual(monitor.deepseek_api_key(), "sk-cli-env")
        # HKCU\Environment is read directly: a widget started before the variable
        # was added would not see it in os.environ.
        with patch.object(monitor, "_windows_env", return_value="sk-registry"), \
                patch.dict(os.environ, blank):
            self.assertEqual(monitor.deepseek_api_key(), "sk-registry")

        self.require_dpapi()
        with patch.object(monitor, "_windows_env", return_value=""), \
                patch.dict(os.environ, blank):
            monitor.CFG["deepseek_api_key"] = "sk-legacy"
            self.assertEqual(monitor.deepseek_api_key(), "sk-legacy")
            self.assertTrue(monitor.save_deepseek_key("sk-encrypted"))
            self.assertEqual(monitor.CFG["deepseek_api_key"], "")
            self.assertNotIn("sk-encrypted",
                             self.deepseek_key_file.read_text(encoding="utf-8"))
            self.assertEqual(monitor.deepseek_api_key(), "sk-encrypted")
            self.assertTrue(monitor.clear_deepseek_key())
            self.assertFalse(self.deepseek_key_file.exists())
            self.assertEqual(monitor.deepseek_api_key(), "")

    def test_fetch_deepseek_reports_money(self):
        seen = {}

        class Response(io.StringIO):
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            seen["auth"] = req.get_header("Authorization")
            return Response(json.dumps({"is_available": True, "balance_infos": [
                {"currency": "USD", "total_balance": "3.5", "granted_balance": "0",
                 "topped_up_balance": "3.5"},
                {"currency": "CNY", "total_balance": "119.901", "granted_balance": "1.5",
                 "topped_up_balance": "118.401"}]}))

        with patch.object(monitor, "_windows_env", return_value=""), \
                patch.dict(os.environ, {monitor.DEEPSEEK_ENV: "sk-env"}), \
                patch.object(monitor.urllib.request, "urlopen", side_effect=fake_urlopen):
            data = monitor.fetch_deepseek()
        self.assertEqual(seen["auth"], "Bearer sk-env")
        self.assertEqual(data["ds_currency"], "CNY")     # CNY preferred
        self.assertEqual(data["ds_balance"], 119.9)
        self.assertEqual(data["ds_granted"], 1.5)
        self.assertEqual(data["ds_plan"], "按量付费")
        runtime.validate_result("deepseek", data)

    def test_deepseek_balance_validation(self):
        runtime.validate_result("deepseek", {"ds_balance": 119.9, "ds_currency": "CNY"})
        runtime.validate_result("deepseek", {"ds_balance": 0})
        for bad in (-1, "12", True, None):
            with self.assertRaises(ValueError):
                runtime.validate_result("deepseek", {"ds_balance": bad})

    def test_deepseek_without_balance_is_an_error(self):
        class Response(io.StringIO):
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        with patch.object(monitor, "_windows_env", return_value=""), \
                patch.dict(os.environ, {monitor.DEEPSEEK_ENV: "sk-env"}), \
                patch.object(monitor.urllib.request, "urlopen",
                             side_effect=lambda req, timeout=None: Response(
                                 '{"is_available": true, "balance_infos": []}')):
            with self.assertRaises(ValueError):
                monitor.fetch_deepseek()


class DeepSeekTests(unittest.TestCase):
    """Pay-as-you-go balance: money plus a locally estimated daily spend."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.spend_file = Path(self.tmp.name) / "deepseek-spend.json"
        self.patches = [patch.object(monitor, "DEEPSEEK_SPEND_FILE", str(self.spend_file)),
                        patch.object(monitor, "DEEPSEEK_KEY_FILE",
                                     str(Path(self.tmp.name) / "deepseek-key.dpapi")),
                        patch.object(monitor, "CFG", dict(monitor.DEFAULT_CONFIG)),
                        patch.object(monitor, "_save_config"),
                        patch.object(monitor, "_windows_env", return_value="")]
        for item in self.patches:
            item.start()
    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_spend_tracks_drops_and_ignores_top_ups(self):
        day = "2026-09-26"
        self.assertEqual(monitor.deepseek_spend(120.0, today=day), 0.0)   # baseline
        self.assertEqual(monitor.deepseek_spend(119.5, today=day), 0.5)
        self.assertEqual(monitor.deepseek_spend(119.0, today=day), 1.0)
        # A top-up raises the baseline instead of producing negative spend.
        self.assertEqual(monitor.deepseek_spend(169.0, today=day), 1.0)
        self.assertEqual(monitor.deepseek_spend(168.25, today=day), 1.75)
        # A new day starts a fresh baseline.
        self.assertEqual(monitor.deepseek_spend(168.0, today="2026-09-27"), 0.0)

    def test_spend_state_is_written_and_recovers_from_garbage(self):
        monitor.deepseek_spend(50.0, today="2026-09-26")
        self.assertEqual(json.loads(self.spend_file.read_text(encoding="utf-8"))["day"],
                         "2026-09-26")
        self.spend_file.write_text("not json", encoding="utf-8")
        self.assertEqual(monitor.deepseek_spend(49.0, today="2026-09-26"), 0.0)

    def test_fetch_deepseek_reports_today_spend(self):
        class Response(io.StringIO):
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        def payload(balance):
            return ('{"is_available": true, "balance_infos": [{"currency": "CNY",'
                    ' "total_balance": "%s", "granted_balance": "0",'
                    ' "topped_up_balance": "%s"}]}' % (balance, balance))

        with patch.dict(os.environ, {monitor.DEEPSEEK_ENV: "sk-env"}):
            with patch.object(monitor.urllib.request, "urlopen",
                              side_effect=lambda req, timeout=None: Response(payload("10.50"))):
                first = monitor.fetch_deepseek()
            with patch.object(monitor.urllib.request, "urlopen",
                              side_effect=lambda req, timeout=None: Response(payload("10.00"))):
                second = monitor.fetch_deepseek()
        self.assertEqual(first["ds_spend"], 0.0)     # first reading is the baseline
        self.assertEqual(second["ds_balance"], 10.0)
        self.assertEqual(second["ds_spend"], 0.5)
        runtime.validate_result("deepseek", second)


def alive(pid):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return api.WaitForSingleObject(handle, 0) == 258
    finally:
        api.CloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "Windows lifecycle contracts")
class WindowsTests(unittest.TestCase):
    def test_scheduler_timeout_kills_real_hung_worker(self):
        clock = Clock()
        results = []
        s = runtime.Scheduler(str(ROOT / "tests" / "query_fixture.py"), lambda *x: results.append(x),
                              factory=lambda script, name: runtime.QueryProcess(script, "hang"),
                              monotonic=lambda: clock.now, wall=lambda: clock.wall)
        try:
            s.configure(["codex"])
            s.tick()
            pid = s.states["codex"]["worker"].process.pid
            self.assertTrue(alive(pid))
            clock.advance(51)
            s.tick()
            self.assertFalse(alive(pid))
            self.assertEqual(results[-1][1]["error"], "Timeout")
        finally:
            s.close()

    def test_job_reaps_real_child_tree(self):
        p = runtime.QueryProcess(str(ROOT / "tests" / "query_fixture.py"), "tree")
        try:
            child = int(p.process.stdout.readline())
            self.assertTrue(alive(child))
        finally:
            p.close()
        for _ in range(20):
            if not alive(child):
                break
            time.sleep(.05)
        self.assertFalse(alive(child))
    def test_crashed_owner_also_reaps_query_tree(self):
        code = ("import os,sys; sys.path.insert(0,sys.argv[1]); from monitor_runtime import QueryProcess; "
                "p=QueryProcess(sys.argv[2],'tree'); "
                "print(p.process.pid,int(p.process.stdout.readline()),flush=True); os._exit(0)")
        output = subprocess.check_output([sys.executable, "-c", code, str(ROOT),
                                          str(ROOT / "tests" / "query_fixture.py")], timeout=10,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
        parent, child = map(int, output.split())
        for _ in range(20):
            if not alive(parent) and not alive(child):
                break
            time.sleep(.05)
        self.assertFalse(alive(parent))
        self.assertFalse(alive(child))
    def test_second_instance_signals_first_and_can_restart(self):
        name = "QuotaMonitor-test-" + str(os.getpid())
        one, two = runtime.SingleInstance(name), runtime.SingleInstance(name)
        try:
            self.assertFalse(one.existing)
            self.assertTrue(two.existing)
            self.assertTrue(one.requested())
            self.assertFalse(one.requested())
        finally:
            two.close()
            one.close()
        three = runtime.SingleInstance(name)
        self.assertFalse(three.existing)
        three.close()


class UITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(monitor, "CACHE_FILE", str(Path(self.tmp.name) / "cache.json")),
                        patch.object(monitor, "DEBUG_FILE", str(Path(self.tmp.name) / "debug.json")),
                        patch.object(monitor, "_save_config"),
                        patch.object(monitor.App, "_init_tray"),
                        patch.object(runtime.Scheduler, "tick")]
        for item in self.patches:
            item.start()
        real_tk = monitor.tk.Tk
        def hidden_root():
            root = real_tk()
            root.withdraw()
            return root
        with patch.object(monitor.tk, "Tk", side_effect=hidden_root):
            self.app = monitor.App()
    def tearDown(self):
        self.app._quit()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()
    def test_partial_failure_preserves_value_and_original_success_time(self):
        a = self.app
        a._on_result("codex", {"ok": True, "data": {"cw_pct": 75}}, {})
        stamp = a._success_at["codex"]
        a._on_result("codex", {"ok": False, "error": "Timeout"}, {})
        a._on_result("kimi", {"ok": True, "data": {"kw_pct": 90}}, {})
        self.assertEqual(a.data["cw_pct"], 75)
        self.assertEqual(a._success_at["codex"], stamp)
        self.assertTrue(a._is_stale("codex"))
        self.assertTrue(a.rows["cw"][1].cget("text").startswith("旧 "))
        a.data = {}
        a._load_cache()
        self.assertEqual(a.data["cw_pct"], 75)
    def test_tray_renders_only_when_value_or_staleness_changes(self):
        a = self.app
        a.tray = Mock(title="", visible=True)
        a._tray_image = Mock(return_value="image")
        a.data["cw_pct"] = 75
        a._verified.add("codex")
        a._success_at["codex"] = time.time()
        for _ in range(100):
            a._update_tray()
        self.assertEqual(a._tray_image.call_count, 1)
        a.errors["codex"] = "Timeout"
        a._update_tray()
        self.assertEqual(a._tray_image.call_count, 2)
        self.assertIn("旧数据", a.tray.title)
    def test_close_without_tray_does_not_hide_window(self):
        a = self.app
        a.root.deiconify()
        a._minimize_to_tray()
        self.assertNotEqual(a.root.state(), "withdrawn")
    def test_callback_failure_keeps_timer_alive(self):
        a = self.app
        with patch.object(a.scheduler, "tick", side_effect=RuntimeError("test")), patch.object(a.root, "after") as after:
            a._poll()
        after.assert_called_once()
        self.assertEqual(a._ui_error, "RuntimeError")

    def test_cached_values_are_not_fresh_until_verified(self):
        a = self.app
        a._on_result("codex", {"ok": True, "data": {"cw_pct": 75}}, {})
        a.data, a._success_at, a._verified = {}, {}, set()
        a._load_cache()
        self.assertEqual(a.data["cw_pct"], 75)
        self.assertTrue(a._is_stale("codex"))

    def test_codex_expired_snapshot_is_greyed_with_reason(self):
        """An ended window must not be presented as the current value."""
        a = self.app
        a._on_result("codex", {"ok": True, "data": {"cw_pct": 75, "c_window_expired": True}}, {})
        self.assertTrue(a._is_stale("codex"))
        self.assertEqual(a.rows["cw"][1].cget("text"), "窗口已过期")
        self.assertIn("待更新", a.status.cget("text"))
        a._on_result("codex", {"ok": True, "data": {"cw_pct": 75, "c_window_expired": False}}, {})
        self.assertFalse(a._is_stale("codex"))
    def test_glm_menu_exposes_secure_key_commands(self):
        menu = self.app._provider_menus["glm"]
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                  if menu.type(i) != "separator"]
        self.assertIn("安全保存 API Key…", labels)
        self.assertIn("清除已保存的 Key", labels)
    def test_secret_dialog_masks_input(self):
        a = self.app
        seen = {}
        def fill():
            win, value, ok = a._secret_prompt
            seen["show"] = win.children["!entry"].cget("show")
            value.set("sk-typed")
            ok()
        a.root.after(150, fill)
        a.root.after(3000, lambda: a._secret_prompt and a._secret_prompt[0].destroy())
        self.assertEqual(a._ask_secret("GLM API Key", "key:"), "sk-typed")
        self.assertEqual(seen["show"], "•")
    def test_deepseek_card_shows_money_and_warns_when_low(self):
        a = self.app
        a._on_result("deepseek", {"ok": True, "data": {
            "ds_balance": 119.9, "ds_granted": 0.0, "ds_currency": "CNY",
            "ds_available": True, "ds_plan": "按量付费"}}, {})
        self.assertEqual(a.section_titles["DeepSeek"].cget("text"), "DeepSeek")
        self.assertEqual(a.section_renews["DeepSeek"].cget("text"), "按量付费")
        self.assertEqual(a.rows["ds"][0].cget("text"), "¥119.90")
        # the note reports which DeepSeek price regime the refresh fell into
        self.assertIn(a.rows["ds"][1].cget("text"),
                      (monitor.DEEPSEEK_PEAK, monitor.DEEPSEEK_OFFPEAK))
        self.assertNotEqual(a.rows["ds"][0].cget("fg"), "#d08020")
        with patch.dict(monitor.CFG, {"deepseek_low_balance": 200.0}):
            a._render()
            self.assertEqual(a.rows["ds"][0].cget("fg"), "#d08020")   # below limit
        with patch.dict(monitor.CFG, {"deepseek_low_balance": 500.0}):
            a._render()
            self.assertEqual(a.rows["ds"][0].cget("fg"), "#d04040")   # below a quarter
    def test_peak_label_follows_beijing_windows(self):
        """梁文峰 09:00-12:00 and 14:00-18:00 Beijing time on weekdays, 梁文谷
        the rest of the time ( weekends included )."""
        utc = timezone.utc
        peak, off = monitor.DEEPSEEK_PEAK, monitor.DEEPSEEK_OFFPEAK
        cases = [
            (datetime(2026, 9, 28, 1, 30, tzinfo=utc), peak),    # Mon 09:30
            (datetime(2026, 9, 28, 3, 59, tzinfo=utc), peak),    # Mon 11:59
            (datetime(2026, 9, 28, 4, 0, tzinfo=utc), off),      # Mon 12:00
            (datetime(2026, 9, 28, 7, 0, tzinfo=utc), peak),     # Mon 15:00
            (datetime(2026, 9, 28, 10, 0, tzinfo=utc), off),     # Mon 18:00
            (datetime(2026, 9, 26, 2, 0, tzinfo=utc), off),      # Sat 10:00
            (datetime(2026, 9, 27, 7, 0, tzinfo=utc), off),      # Sun 15:00
        ]
        for when, expected in cases:
            self.assertEqual(monitor.deepseek_peak_label(when), expected, when)

    def test_token_formatter(self):
        self.assertEqual(monitor._fmt_tokens(0), "0")
        self.assertEqual(monitor._fmt_tokens(999), "999")
        self.assertEqual(monitor._fmt_tokens(75682437), "75.7M")
        self.assertEqual(monitor._fmt_tokens(347035191), "347M")
        self.assertEqual(monitor._fmt_tokens(1181266882), "1.2B")
        self.assertIsNone(monitor._fmt_tokens(None))
        self.assertIsNone(monitor._fmt_tokens("x"))

    def test_deepseek_spend_row_shows_todays_tokens(self):
        a = self.app
        a._on_result("deepseek", {"ok": True, "data": {
            "ds_balance": 119.9, "ds_spend": 6.64, "ds_currency": "CNY",
            "ds_tokens_total": 314826023, "ds_tokens_fresh": 2352423}}, {})
        self.assertEqual(a.rows["ds_spend"][0].cget("text"),
                         "¥" + monitor.MONEY_PAD * 2 + "6.64")
        self.assertEqual(a.rows["ds_spend"][1].cget("text"), "315M")
        with patch.dict(monitor.CFG, {"deepseek_token_metric": "fresh"}):
            a._render()
            self.assertEqual(a.rows["ds_spend"][1].cget("text"), "2.4M")
        with patch.dict(monitor.CFG, {"deepseek_token_metric": "off"}):
            a._render()
            self.assertEqual(a.rows["ds_spend"][1].cget("text"), "")
        # a later payload without token figures keeps the last known number
        with patch.dict(monitor.CFG, {"deepseek_token_metric": "total"}):
            a._on_result("deepseek", {"ok": True, "data": {
                "ds_balance": 119.9, "ds_spend": 6.64, "ds_currency": "CNY"}}, {})
            self.assertEqual(a.rows["ds_spend"][1].cget("text"), "315M")

    @unittest.skipUnless(HAVE_ZSTD, "needs zstd support")
    def test_local_harness_tokens_sums_only_today(self):
        import datetime as dt
        today = dt.date(2026, 9, 26)
        inside = int(dt.datetime(2026, 9, 26, 12, 0).timestamp() * 1000)
        before = int(dt.datetime(2026, 9, 25, 23, 0).timestamp() * 1000)
        records = [
            {"time": inside, "data": {"usage": {"inputTokens": 100, "outputTokens": 50,
                                                "cacheReadTokens": 900,
                                                "totalTokens": 1050}}},
            {"time": inside, "data": {"usage": {"inputTokens": 10, "outputTokens": 5,
                                                "totalTokens": 15}}},
            {"time": before, "data": {"usage": {"inputTokens": 9999, "outputTokens": 9999,
                                                "totalTokens": 19998}}},
            {"time": inside, "data": {"message": "no usage here"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.v4.jsonl.zstd"
            path.write_bytes(zstd_compress((json.dumps(records[0]) + "\n"
                                            + "\n".join(json.dumps(r)
                                                        for r in records[1:])).encode("utf-8")))
            self.assertEqual(monitor.local_harness_tokens(today, directory),
                             {"total": 1065, "fresh": 165})
            # a directory without logs is not an error, just no figure
            self.assertIsNone(monitor.local_harness_tokens(today, directory + "-missing"))

    def test_fit_does_not_touch_a_layered_window_needlessly(self):
        """Re-applying the geometry/region of an alpha window makes Windows
        rebuild its surface, which is how a stale, partial copy of the panel
        ended up on screen. Unchanged content must not touch it at all."""
        a = self.app
        a.root.deiconify()
        a.root.update()
        calls = {"geometry": 0}

        def count_geometry(*args, **kwargs):
            if args:                      # the getter is called with no arguments
                calls["geometry"] += 1
            return geometry(*args, **kwargs)

        geometry = a.root.geometry
        a.root.geometry = count_geometry
        redraws = []
        a._redraw = lambda: redraws.append(1)

        a._fit()
        first = calls["geometry"], len(redraws)
        for _ in range(4):
            a._fit()
        self.assertEqual((calls["geometry"], len(redraws)), first,
                         "an unchanged layout must not re-apply the geometry or "
                         "force another repaint")
        self.assertEqual(first[0], 1)
        self.assertEqual(first[1], 1, "a real geometry change must force a repaint")

        a.status.config(text="刷新时间 12:34 变更")
        a.root.update_idletasks()
        a._fit()
        self.assertGreaterEqual(calls["geometry"], 1)

        # a real layout change (a card goes away) must be applied again
        try:
            before = calls["geometry"]
            a.show_kimi.set(False)
            a._apply_visibility(persist=False)
            a.root.update_idletasks()
            a._fit()
            self.assertGreater(calls["geometry"], before,
                               "a real layout change must resize the window")
        finally:
            a.show_kimi.set(True)
            a._apply_visibility(persist=False)

    def test_position_lock_and_drag_alpha(self):
        """A locked window must not move at all, and a drag makes it opaque so
        Windows stops tearing the translucent panel while it is moved."""
        a = self.app

        class Event:
            def __init__(self, x, y):
                self.x, self.y = x, y

        a.root.deiconify()
        a.root.geometry("+300+300")
        a.root.update()
        a.lock_position.set(True)
        a._drag_start(Event(10, 10))
        self.assertIsNone(a._drag, "a locked widget must not start a drag")
        a._drag_move(Event(80, 80))
        a.root.update()
        self.assertEqual((a.root.winfo_x(), a.root.winfo_y()), (300, 300))

        a.lock_position.set(False)
        a.alpha_val = 90
        a.root.attributes("-alpha", 0.9)
        a._drag_start(Event(10, 10))
        self.assertIsNotNone(a._drag)
        self.assertAlmostEqual(float(a.root.attributes("-alpha")), 1.0, places=2)
        a._drag_end()
        self.assertAlmostEqual(float(a.root.attributes("-alpha")), 0.9, places=2)

    def test_hidden_cards_are_not_queried(self):
        """A card that is switched off must cost nothing: no worker, no API call.
        The tray follows the visible cards so it never points at a stale source."""
        a = self.app
        try:
            for name in ("kimi", "codex", "glm", "deepseek"):
                getattr(a, "show_" + name).set(False)
            a._apply_visibility(persist=False)
            self.assertEqual(a._enabled_sources(), [])

            a.show_codex.set(True)
            a._apply_visibility(persist=False)
            self.assertEqual(a._enabled_sources(), ["codex", "main"])
            self.assertEqual(monitor.CFG["tray_metric"], "cw_pct")

            # Codex goes away: neither its worker nor its tray figure may remain
            a.show_codex.set(False)
            a.show_kimi.set(True)
            a._apply_visibility(persist=False)
            self.assertEqual(a._enabled_sources(), ["kimi"])
            self.assertEqual(monitor.CFG["tray_metric"], "kw_pct")
            self.assertEqual([metric for metric, _l in a._visible_tray_choices()],
                             ["k5_pct", "kw_pct"])
        finally:
            # the UI tests share one App, so put the cards back afterwards
            for name in ("kimi", "codex", "glm", "deepseek"):
                getattr(a, "show_" + name).set(True)
            monitor.CFG["tray_metric"] = "cw_pct"
            a._tray_var.set("cw_pct")
            a._apply_visibility(persist=False)

    def test_transparency_and_position_are_remembered(self):
        """The alpha buttons and a dragged window are written back to config."""
        a = self.app
        monitor.CFG.pop("window_alpha", None)
        a._alpha_step(-3)
        self.assertEqual(monitor.CFG["window_alpha"], a.alpha_val)
        self.assertLess(a.alpha_val, 94)
        for _ in range(30):                         # clamps at 40
            a._alpha_step(-3)
        self.assertEqual(a.alpha_val, 40)
        self.assertEqual(monitor.CFG["window_alpha"], 40)

        a._drag = (0, 0)
        a._drag_end()
        self.assertIn("window_x", monitor.CFG)
        self.assertIn("window_y", monitor.CFG)

    def test_remembered_position_is_clamped_on_screen(self):
        # mostly off-screen (monitor changed): fall back to the default corner
        self.assertIsNone(monitor.clamp_position(1900, 100, 200, 300, 1920, 1080))
        self.assertIsNone(monitor.clamp_position(100, 1070, 200, 300, 1920, 1080))
        self.assertEqual(monitor.clamp_position(100, 200, 200, 300, 1920, 1080),
                         (100, 200))
        # hanging off an edge is pulled back inside
        self.assertEqual(monitor.clamp_position(-1, 100, 200, 300, 1920, 1080),
                         (0, 100))
        self.assertEqual(monitor.clamp_position(1800, 900, 200, 300, 1920, 1080),
                         (1712, 732))

    def test_money_rows_align_on_symbol_and_decimal_point(self):
        """Balance and spend must line up like a ledger: the currency symbol and
        the decimal point sit at the same place in both rows."""
        a = self.app
        a._on_result("deepseek", {"ok": True, "data": {
            "ds_balance": 113.83, "ds_spend": 4.9, "ds_currency": "CNY",
            "ds_available": True, "ds_plan": "按量付费"}}, {})
        balance = a.rows["ds"][0].cget("text")
        spend = a.rows["ds_spend"][0].cget("text")
        self.assertEqual(balance, "¥113.83")
        # the short amount is padded with figure-width spaces, not plain ones
        self.assertEqual(spend, "¥" + monitor.MONEY_PAD * 2 + "4.90")
        self.assertEqual(balance.index("."), spend.index("."))
        # ...and those spaces really are one digit wide, so the amounts share
        # the symbol position and the decimal point in pixels too
        font = tkfont.Font(font=a.rows["ds"][0].cget("font"))
        self.assertEqual(font.measure(balance.split(".")[0]),
                         font.measure(spend.split(".")[0]))
        self.assertEqual(font.measure(monitor.MONEY_PAD), font.measure("0"))

    def test_every_theme_repaints_the_card_header(self):
        """The card header row is built from its own frames; if the theme pass
        forgets them, the light theme shows dark blocks behind the titles."""
        a = self.app
        for theme in ("dark", "light", "glass"):
            a._set_theme(theme)
            expected = monitor.THEMES[theme]["BG_CARD"]
            for frame in a._card_frames:
                self.assertEqual(frame.cget("bg"), expected,
                                 "%s theme left a card frame unpainted" % theme)
            for lbl in list(a.section_titles.values()) + list(a.section_renews.values()):
                self.assertEqual(lbl.cget("bg"), expected,
                                 "%s theme left a header label unpainted" % theme)
            for card in a._cards:
                self.assertEqual(card.cget("bg"), expected)

    def test_renewal_date_sits_at_the_notes_column(self):
        """The renewal date shares the title's row but must line up with the
        notes column underneath it, on every card."""
        a = self.app
        for name in ("kimi", "codex", "deepseek"):
            a._on_result(name, {"ok": True, "data": {
                "kw_pct": 100, "cw_pct": 82, "cr_credit_count": 1,
                "cr_credit_expiry": 1792700757, "ds_balance": 113.83,
                "ds_spend": 4.9, "ds_currency": "CNY"}}, {})
        a._fit()
        a._fit()
        positions = set()
        for card_name in ("Kimi", "Codex", "DeepSeek"):
            card = a.section_renews[card_name].master.master
            label_w = card.grid_columnconfigure(0)["minsize"]
            value_w = card.grid_columnconfigure(1)["minsize"]
            head_x = a.section_renews[card_name].master.winfo_x() or 7
            expected = label_w + value_w + 9 - head_x      # notes cell + padding
            self.assertEqual(int(a.section_renews[card_name].place_info()["x"]),
                             expected, "%s's renewal date is off" % card_name)
            positions.add(expected)
        self.assertEqual(len(positions), 1, "cards disagree: %s" % positions)

    def test_short_titles_are_left_alone(self):
        """Titles and the renewal date are packed left/right, so a normal title
        is never shortened (only an over-long one is)."""
        a = self.app
        with patch.dict(monitor.CFG, {"kimi_plan_name": "Pro"}):
            a._on_result("kimi", {"ok": True, "data": {"kw_pct": 100, "k_plan": "Pro"}}, {})
            a._on_result("deepseek", {"ok": True, "data": {
                "ds_balance": 1.0, "ds_currency": "CNY", "ds_available": True}}, {})
            a._fit()
            a._fit()
            self.assertEqual(a.section_titles["Kimi"].cget("text"), "Kimi · Pro")
            self.assertEqual(a.section_titles["DeepSeek"].cget("text"), "DeepSeek")

    def test_long_plan_name_is_shortened_to_fit(self):
        """Titles and the renewal date are packed left/right so they cannot
        overlap; this only pins down the trimming helper and the render path."""
        a = self.app
        font = tkfont.Font(font=monitor.FONT_TITLE)
        self.assertEqual(a._ellipsize(font, "Kimi · Andante", 500), "Kimi · Andante")
        trimmed = a._ellipsize(font, "Kimi · Allegretto 年度版 超级加长版", 120)
        self.assertTrue(trimmed.endswith("…"))
        self.assertLessEqual(font.measure(trimmed), 120)
        with patch.dict(monitor.CFG, {"kimi_plan_name": "Allegretto 年度版 超级加长版"}):
            a._on_result("kimi", {"ok": True, "data": {"kw_pct": 100, "k_plan": "Pro"}}, {})
            a._fit()
            a._fit()
            self.assertTrue(a.section_titles["Kimi"].cget("text").endswith("…"),
                            "long title was not shortened: %r"
                            % a.section_titles["Kimi"].cget("text"))

    def test_every_card_shares_the_same_three_columns(self):
        """The three columns are found by x position, so they must match across
        cards; a card whose content merely exceeded the minimum used to grow and
        break that."""
        a = self.app
        for name, payload in (("kimi", {"k5_pct": 100, "kw_pct": 100}),
                              ("codex", {"cw_pct": 82, "cr_credit_count": 1,
                                         "cr_credit_expiry": 1792700757}),
                              ("deepseek", {"ds_balance": 113.83, "ds_spend": 4.9,
                                            "ds_currency": "CNY"})):
            a._on_result(name, {"ok": True, "data": payload}, {})
        a._fit()
        a.root.update_idletasks()
        label_x, value_x, note_x = set(), set(), set()
        for card in a._cards:
            if not card.winfo_manager():
                continue
            for key, (value, note) in a.rows.items():
                if value.master is card and value.winfo_manager():
                    label_x.add(a.row_labels[key][0].winfo_x())
                    value_x.add(value.winfo_x())
                    note_x.add(note.winfo_x())
        self.assertEqual(len(label_x), 1, "label column differs: %s" % label_x)
        self.assertEqual(len(value_x), 1, "value column differs: %s" % value_x)
        self.assertEqual(len(note_x), 1, "note column differs: %s" % note_x)

    def test_money_labels_fit_their_column(self):
        """Regression: "¥118.73" was clipped because Tk width=4 means four
        average characters, which is narrower than the money string."""
        a = self.app
        for balance in (118.73, 1234.56, 99999.99):
            a._on_result("deepseek", {"ok": True, "data": {
                "ds_balance": balance, "ds_spend": 3.5, "ds_currency": "CNY",
                "ds_available": True, "ds_plan": "按量付费"}}, {})
            a.root.update_idletasks()
            for key in ("ds", "ds_spend"):
                label = a.rows[key][0]
                text = label.cget("text")
                font = tkfont.Font(font=label.cget("font"))
                self.assertLessEqual(font.measure(text), label.winfo_reqwidth(),
                                     "%s is clipped in row %s" % (text, key))

    def test_codex_credit_row_follows_count_and_toggle(self):
        a = self.app
        def shown(widget):
            return bool(widget.winfo_manager())
        a._on_result("codex", {"ok": True, "data": {
            "cw_pct": 86, "cr_credit_count": 1,
            "cr_credit_expiry": time.time() + 30 * 86400}}, {})
        self.assertTrue(shown(a.rows["cr_credit"][0]))
        self.assertEqual(a.rows["cr_credit"][0].cget("text"), "1 张")
        self.assertTrue(a.rows["cr_credit"][1].cget("text").endswith("到期"))
        # Expiring inside a week is flagged.
        a._on_result("codex", {"ok": True, "data": {
            "cw_pct": 86, "cr_credit_count": 1,
            "cr_credit_expiry": time.time() + 3 * 86400}}, {})
        self.assertEqual(a.rows["cr_credit"][0].cget("fg"), "#d08020")
        # No vouchers left: the row disappears instead of showing 0.
        a._on_result("codex", {"ok": True, "data": {"cw_pct": 86, "cr_credit_count": 0}}, {})
        self.assertFalse(shown(a.rows["cr_credit"][0]))
        with patch.dict(monitor.CFG, {"show_codex_credits": False}):
            a._on_result("codex", {"ok": True, "data": {
                "cw_pct": 86, "cr_credit_count": 2}}, {})
            self.assertFalse(shown(a.rows["cr_credit"][0]))

    def test_deepseek_spend_row_is_never_colour_warned(self):
        a = self.app
        a._on_result("deepseek", {"ok": True, "data": {
            "ds_balance": 8.0, "ds_spend": 0.5, "ds_currency": "CNY",
            "ds_available": True, "ds_plan": "按量付费"}}, {})
        self.assertEqual(a.rows["ds"][0].cget("text"), "¥8.00")
        self.assertEqual(a.rows["ds_spend"][0].cget("text"), "¥0.50")
        # 8.00 is under the default 20 limit (but above a quarter of it), so the
        # balance warns while the spend row (always small) stays neutral.
        self.assertEqual(a.rows["ds"][0].cget("fg"), "#d08020")
        self.assertNotEqual(a.rows["ds_spend"][0].cget("fg"), "#d08020")

    def test_dividers_need_a_visible_card_on_both_sides(self):
        a = self.app
        def shown(widget):
            return bool(widget.winfo_manager())
        with patch.dict(monitor.CFG, {}, clear=False):
            for name in ("show_kimi", "show_glm", "show_codex", "show_deepseek"):
                getattr(a, name).set(True)
            a._apply_visibility()
            self.assertTrue(all(shown(d) for d in a._dividers))
            # Hiding a card in the middle keeps the divider between the two
            # cards that remain neighbours.
            a.show_glm.set(False)
            a._apply_visibility()
            self.assertFalse(shown(a._dividers[0]))
            self.assertTrue(shown(a._dividers[1]))
            self.assertTrue(shown(a._dividers[2]))
            # A single visible card needs no dividers at all.
            a.show_kimi.set(False)
            a.show_deepseek.set(False)
            a._apply_visibility()
            self.assertFalse(any(shown(d) for d in a._dividers))


class EventLoopTests(unittest.TestCase):
    def test_real_tk_loop_refreshes_twice_without_manual_trigger(self):
        events = []
        real_tk = monitor.tk.Tk
        def hidden_root():
            root = real_tk()
            root.withdraw()
            return root
        def scheduler(script, callback, interval):
            def record(*args):
                events.append(args)
                callback(*args)
            return runtime.Scheduler(str(ROOT / "tests" / "query_fixture.py"), record, interval=.3)
        # Only Codex is enabled: the source set must not depend on whichever
        # API keys this machine happens to have (env vars are read live).
        cfg = dict(monitor.DEFAULT_CONFIG, show_kimi=False, show_glm=False,
                   show_deepseek=False, show_radar=False)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(monitor, "CFG", cfg), \
                patch.object(monitor, "CACHE_FILE", str(Path(directory) / "cache.json")), \
                patch.object(monitor, "DEBUG_FILE", str(Path(directory) / "debug.json")), \
                patch.object(monitor, "_save_config"), \
                patch.object(monitor, "Scheduler", side_effect=scheduler), \
                patch.object(monitor.App, "_init_tray"), \
                patch.object(monitor.tk, "Tk", side_effect=hidden_root):
            app = monitor.App()
            try:
                app.root.after(2500, app._quit)
                app.run()
                self.assertGreaterEqual(len(events), 2)
                self.assertTrue(all(event[1]["ok"] for event in events))
                self.assertFalse(app.scheduler.active)
            finally:
                app._quit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
