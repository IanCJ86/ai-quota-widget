import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import monitor_runtime as runtime
import quota_monitor as monitor


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
        s.configure(["codex", "kimi", "main", "community"])
        s.tick()
        self.assertEqual(sum(x["worker"] is not None for x in s.states.values()), 2)
        s.states["kimi"]["worker"].done = True
        s.tick()
        self.assertEqual(self.results[0][0], "kimi")
        self.assertIsNotNone(s.states["main"]["worker"])
        self.assertIsNone(s.states["community"]["worker"])
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
    def test_percentage_validation_and_explicit_no_watch(self):
        for value in (0, 1, 75, 100):
            runtime.validate_result("codex", {"cw_pct": value})
        for value in (-1, 101, float("nan"), True, "75"):
            with self.assertRaises(ValueError):
                runtime.validate_result("codex", {"cw_pct": value})
        runtime.validate_result("community", {"cr_resets_pct": None, "cr_resets_mode": "no_watch"})
        with self.assertRaises(ValueError):
            runtime.validate_result("community", {"cr_resets_pct": None})
    def test_community_one_percent_is_not_one_hundred(self):
        with patch.object(monitor, "_fetch_public_text", side_effect=[b"no headline", json.dumps(
                {"data": {"active_watch": {"reset_chance_percent": 1}}}).encode()]):
            self.assertEqual(monitor.fetch_community_radar()["cr_resets_pct"], 1)
    def test_community_schema_error_is_not_empty_watch(self):
        with patch.object(monitor, "_fetch_public_text", side_effect=[b"no headline", b'{"data":{}}']):
            with self.assertRaises(ValueError):
                monitor.fetch_community_radar()
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

    def test_no_watch_clears_previous_probability_but_failure_does_not(self):
        a = self.app
        a._on_result("community", {"ok": True, "data": {"cr_resets_pct": 89}}, {})
        a._on_result("community", {"ok": False, "error": "Timeout"}, {})
        self.assertEqual(a.data["cr_resets_pct"], 89)
        a._on_result("community", {"ok": True, "data": {
            "cr_resets_pct": None, "cr_resets_mode": "no_watch"}}, {})
        self.assertIsNone(a.data["cr_resets_pct"])
        self.assertEqual(a.rows["cr_resets"][1].cget("text"), "暂无投票")


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
        self.assertEqual(a.rows["ds"][1].cget("text"), "可用")
        self.assertNotEqual(a.rows["ds"][0].cget("fg"), "#d08020")
        with patch.dict(monitor.CFG, {"deepseek_low_balance": 200.0}):
            a._render()
            self.assertEqual(a.rows["ds"][0].cget("fg"), "#d08020")   # below limit
        with patch.dict(monitor.CFG, {"deepseek_low_balance": 500.0}):
            a._render()
            self.assertEqual(a.rows["ds"][0].cget("fg"), "#d04040")   # below a quarter
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
