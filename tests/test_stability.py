"""Regression coverage for malformed responses, local logs and secret cleanup."""
from desktop_test_support import isolate_desktop
isolate_desktop()
from datetime import date, datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness_stats as stats
import quota_monitor as monitor
import monitor_runtime as runtime

try:
    from compression.zstd import compress
except ImportError:
    from backports.zstd import compress


class StabilityTests(unittest.TestCase):
    def test_invalid_balance_never_writes_spend(self):
        for bad in (None, "", "oops", "NaN", "Infinity", -1, True):
            with self.subTest(balance=bad), \
                    patch.object(monitor, "deepseek_api_key", return_value="fake"), \
                    patch.object(monitor, "deepseek_spend") as spend, \
                    patch.object(monitor.urllib.request, "urlopen", return_value=io.StringIO(
                        json.dumps({"balance_infos": [{"currency": "CNY", "total_balance": bad}]}))):
                with self.assertRaises((ValueError, TypeError)):
                    monitor.fetch_deepseek()
                spend.assert_not_called()
        for bad in (float("nan"), float("inf"), -1, True):
            with self.assertRaises(ValueError):
                runtime.validate_result("deepseek", {"ds_balance": bad})

    def test_balance_query_never_reads_logs(self):
        with patch.object(monitor, "deepseek_api_key", return_value="fake"), \
                patch.object(monitor, "deepseek_spend", return_value=0), \
                patch.object(monitor, "local_harness_tokens", side_effect=AssertionError("scan")), \
                patch.object(monitor.urllib.request, "urlopen", return_value=io.StringIO(
                    '{"balance_infos":[{"currency":"CNY","total_balance":"5"}]}')):
            self.assertEqual(monitor.fetch_deepseek()["ds_balance"], 5)

    def test_save_reports_failed_plaintext_cleanup(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, "CFG", dict(glm_api_key="fake-legacy")), \
                patch.object(monitor, "dpapi_protect", return_value=b"fake-ciphertext"), \
                patch.object(monitor, "_save_config", return_value=False):
            path = Path(folder) / "key.dpapi"
            self.assertFalse(monitor.save_provider_key(path, "glm_api_key", "fake"))
            self.assertTrue(path.exists())
            self.assertEqual(monitor.CFG["glm_api_key"], "fake-legacy")

    def test_save_config_propagates_status_and_cleans_legacy(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, "CONFIG_FILE", str(Path(folder) / "config.json")), \
                patch.object(monitor, "SETTINGS_FILE", str(Path(folder) / "settings.json")), \
                patch.object(monitor, "CFG", dict(glm_api_key="old")):
            with patch.object(monitor, "atomic_json", side_effect=PermissionError):
                self.assertFalse(monitor._save_config({}))
            Path(monitor.SETTINGS_FILE).write_text('{"glm_api_key":"old", "keep":1}', encoding="utf-8")
            self.assertTrue(monitor._clear_plaintext_key("glm_api_key"))
            self.assertEqual(json.loads(Path(monitor.SETTINGS_FILE).read_text()),
                             {"glm_api_key": "", "keep": 1})

    def test_codex_refresh_scheduled_at_reset_not_fifteen_minutes(self):
        callback = Mock()
        s = runtime.Scheduler("unused", callback, monotonic=lambda: 100, wall=lambda: 1000)
        s.configure(["codex"])
        state = s.states["codex"]
        s._finish("codex", state, {"ok": True, "data": {"cw_pct": 50, "cw_reset": 1010}}, 100)
        self.assertEqual(state["due"], 111)
        s._finish("codex", state, {"ok": True, "data": {"cw_pct": 50, "cw_reset": 900}}, 100)
        self.assertEqual(state["due"], 1000)  # expired snapshots cannot create tight loops


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / "test.jsonl.zstd"
        self.cache = self.root / "cache.json"
        self.day = date.today()

    def record(self, tokens):
        return (json.dumps({"time": datetime.now().timestamp() * 1000,
                            "data": {"usage": {"totalTokens": tokens, "inputTokens": 3,
                                               "outputTokens": 2}}}) + "\n").encode()

    def test_multiframe_cache_append_and_rewrite(self):
        self.log.write_bytes(compress(b'{"header":1}\n') + compress(self.record(100)))
        expected = {"total": 100, "fresh": 5}
        self.assertEqual(stats.totals(self.root, cache_path=self.cache), expected)
        with patch.object(stats, "open_log", side_effect=AssertionError("cache miss")):
            self.assertEqual(stats.totals(self.root, cache_path=self.cache), expected)
        with self.log.open("ab") as stream:
            stream.write(compress(self.record(50)))
        self.assertEqual(stats.totals(self.root, cache_path=self.cache), {"total": 150, "fresh": 10})
        self.log.write_bytes(compress(self.record(7)))
        self.assertEqual(stats.totals(self.root, cache_path=self.cache), {"total": 7, "fresh": 5})

    def test_multiframe_on_installed_python_codec(self):
        self.log.write_bytes(compress(self.record(1)) + compress(self.record(2)))
        self.assertEqual(stats.totals(self.root), {"total": 3, "fresh": 10})

    def test_corrupt_log_does_not_report_partial_success(self):
        self.log.write_bytes(compress(self.record(100)))
        (self.root / "bad.jsonl.zstd").write_bytes(b"broken")
        self.assertIsNone(stats.totals(self.root, cache_path=self.cache))

    def test_budget_exhaustion_and_empty_day(self):
        self.log.write_bytes(compress(self.record(100)))
        self.assertIsNone(stats.totals(self.root, budget=0))
        self.assertEqual(stats.totals(self.root, date(2100, 1, 1)), {"total": 0, "fresh": 0})

    def test_cache_contains_no_conversation_text(self):
        self.log.write_bytes(compress(self.record(10)))
        stats.totals(self.root, cache_path=self.cache)
        text = self.cache.read_text()
        self.assertNotIn(str(self.log), text)
        self.assertNotIn('"usage"', text)

    def test_bad_usage_and_truncated_stream_are_not_zero(self):
        self.log.write_bytes(compress(self.record(-1)))
        self.assertIsNone(stats.totals(self.root))
        self.log.write_bytes(compress(self.record(100))[:-4])
        self.assertIsNone(stats.totals(self.root))
