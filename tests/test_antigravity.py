"""Antigravity quota snapshot, agy statusLine bridge, global reset monitor & UI tests."""
from desktop_test_support import isolate_desktop
isolate_desktop()
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import quota_antigravity as ag
import quota_cli as cli
import quota_monitor as monitor
from monitor_runtime import validate_result
import test_monitor as fixtures

NOW = datetime(2026, 11, 28, 2, 15, tzinfo=timezone.utc).timestamp()


def sample_reset_payload(announced_at=None, reset_type="full", generated_at=None):
    return {
        "data": {
            "latest_reset": {
                "id": "2125851902009311306",
                "kind": "reset",
                "reset_type": reset_type,
                "scope": "all",
                "announced_at": announced_at or "2026-11-26T07:19:24.000Z",
                "text": "PUBLIC_SOCIAL_POST_SHOULD_NOT_BE_STORED",
                "verification": "provisional",
                "source": {"type": "x_post", "author": "_mohansolo", "url": "https://x.com/example"},
            },
            "stats": {
                "total": 17,
                "days_since_last": 1,
                "avg_interval_days": 11.8,
                "longest_wait_days": 44,
            },
        },
        "meta": {
            "api_version": "v1",
            "generated_at": generated_at or "2026-11-28T02:13:19.646Z",
        },
    }


def sample_statusline_payload():
    return {
        "cwd": "C:/Secret/Workspace",
        "session_id": "secret-session-id",
        "conversation_title": "Private Title",
        "transcript_path": "C:/Users/secret/transcript.jsonl",
        "email": "private@example.com",
        "product": "antigravity",
        "plan_tier": "Pro",
        "quota": {
            "gemini-5h": {
                "remaining_fraction": 0.86,
                "reset_time": "2026-11-28T05:30:00Z",
                "reset_in_seconds": 11700,
                "disabled": False,
            },
            "gemini-weekly": {
                "remaining_fraction": 0.9378,
                "reset_time": "2026-12-03T07:50:32Z",
                "reset_in_seconds": 452000,
            },
            "claude-5h": {
                "remaining_fraction": 0.42,
                "reset_in_seconds": 9000,
            },
            "claude-weekly": {
                "remaining_fraction": 0.68,
                "reset_time": "2026-12-02T00:00:00Z",
            },
            "ai-credits": {
                "remaining_amount": 42,
            },
        },
    }


class AntigravityResetTests(unittest.TestCase):
    def test_parses_confirmed_reset_without_social_text_or_fake_forecast(self):
        data = validate_result("ag_reset", ag.parse_ag_reset(sample_reset_payload(), now=NOW))
        self.assertEqual(data["ag_reset_phase"], "recorded")
        self.assertEqual(data["ag_reset_type"], "full")
        self.assertEqual(data["ag_reset_scope"], "all")
        self.assertNotIn("PUBLIC_SOCIAL_POST", str(data))
        self.assertNotIn("https://", str(data))
        self.assertNotIn("11.8", str(data))
        self.assertFalse(ag.ag_reset_status(data, verified=True, now=NOW)["stale"])

    def test_recent_vs_historical_view_and_banked_distinction(self):
        recent_iso = datetime.fromtimestamp(NOW - 3600, tz=timezone.utc).isoformat()
        full = ag.parse_ag_reset(sample_reset_payload(recent_iso, "full"), now=NOW)
        self.assertEqual(ag.ag_reset_view(full, now=NOW)["value"], "已重置")
        self.assertTrue(ag.ag_reset_view(full, now=NOW)["recent"])

        banked = ag.parse_ag_reset(sample_reset_payload(recent_iso, "banked"), now=NOW)
        self.assertEqual(ag.ag_reset_view(banked, now=NOW)["value"], "已发券")

        partial = ag.parse_ag_reset(sample_reset_payload(recent_iso, "partial"), now=NOW)
        self.assertEqual(ag.ag_reset_view(partial, now=NOW)["value"], "部分重置")

        old_iso = datetime.fromtimestamp(NOW - 3 * 86400, tz=timezone.utc).isoformat()
        hist = ag.parse_ag_reset(sample_reset_payload(old_iso, "full"), now=NOW)
        view = ag.ag_reset_view(hist, now=NOW)
        self.assertFalse(view["recent"])
        self.assertEqual(view["value"], "3天前")
        self.assertTrue(view["note"].endswith("全员"))

    def test_bad_schema_future_time_and_stale_generated_at(self):
        for bad in (None, [], {}, {"data": {"latest_reset": "bad"}},
                    sample_reset_payload(announced_at=datetime.fromtimestamp(NOW + 400, tz=timezone.utc).isoformat()),
                    sample_reset_payload(reset_type="unknown")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ag.parse_ag_reset(bad, now=NOW)
        stale_gen = datetime.fromtimestamp(NOW - 7 * 3600, tz=timezone.utc).isoformat()
        data = ag.parse_ag_reset(sample_reset_payload(generated_at=stale_gen), now=NOW)
        self.assertEqual(ag.ag_reset_status(data, verified=True, now=NOW)["reason"], "信源记录过旧")
        no_gen = sample_reset_payload()
        no_gen["meta"]["generated_at"] = None
        data2 = ag.parse_ag_reset(no_gen, now=NOW)
        self.assertEqual(ag.ag_reset_status(data2, verified=True, now=NOW)["reason"], "信源时间未提供")


class AntigravitySnapshotTests(unittest.TestCase):
    def test_statusline_parser_strips_private_fields_and_parses_pools(self):
        data = validate_result("antigravity", ag.parse_statusline_payload(
            sample_statusline_payload(), now=NOW, use_g1_credits=True))
        self.assertEqual(data["a5_pct"], 86)
        self.assertEqual(data["aw_pct"], 94)
        self.assertEqual(data["a3p5_pct"], 42)
        self.assertEqual(data["a3p_pct"], 68)
        self.assertEqual(data["a_credits"], 42.0)
        self.assertTrue(data["a_credits_enabled"])
        self.assertEqual(data["a_plan"], "Pro")
        text = json.dumps(data)
        for secret in ("private@example.com", "Secret/Workspace", "Private Title", "transcript.jsonl"):
            self.assertNotIn(secret, text)

    def test_weekly_zero_marks_five_hour_paused(self):
        payload = {
            "plan_tier": "Pro",
            "quota": {
                "gemini-5h": {"remaining_fraction": 0.0, "reset_in_seconds": 3600},
                "gemini-weekly": {"remaining_fraction": 0.0, "reset_in_seconds": 86400},
            },
        }
        data = ag.parse_statusline_payload(payload, now=NOW)
        self.assertTrue(data["a5_disabled"])

    def test_capture_and_read_snapshot_and_bridge_install(self):
        with tempfile.TemporaryDirectory() as folder:
            snap = Path(folder) / "antigravity-snapshot.json"
            settings = Path(folder) / "settings.json"
            settings.write_text(json.dumps({"useG1Credits": True, "theme": "tokyo"}), encoding="utf-8")
            ag.capture_statusline_stdin(snap, json.dumps(sample_statusline_payload()), now=NOW)
            raw_saved = snap.read_text(encoding="utf-8")
            self.assertNotIn("private@example.com", raw_saved)
            loaded = validate_result("antigravity", ag.read_ag_snapshot(snap, settings, now=NOW))
            self.assertEqual(loaded["aw_pct"], 94)
            self.assertTrue(loaded["a_credits_enabled"])
            ag.install_agy_statusline_bridge('"quota-cli.exe" --agy-statusline', settings)
            updated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["theme"], "tokyo")
            self.assertTrue(updated["statusLine"]["stack_with_default"])
            self.assertEqual(updated["statusLine"]["command"], '"quota-cli.exe" --agy-statusline')

    def test_headless_agy_statusline_flag_has_no_gui_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {**__import__("os").environ, "AI_QUOTA_WIDGET_DATA_DIR": folder}
            result = subprocess.run(
                [sys.executable, str(ROOT / "quota_monitor.py"), "--agy-statusline"],
                input=json.dumps(sample_statusline_payload()),
                text=True, capture_output=True, timeout=15, env=env, **monitor._NO_WINDOW,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snap = Path(folder) / ag.AG_SNAPSHOT_NAME
            self.assertTrue(snap.is_file())
            saved = json.loads(snap.read_text(encoding="utf-8"))
            self.assertEqual(saved["data"]["aw_pct"], 94)
            self.assertNotIn("private@example.com", snap.read_text(encoding="utf-8"))


class AntigravityUITests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.UITests()
        self.fixture.setUp()
        self.app = self.fixture.app

    def tearDown(self):
        self.fixture.tearDown()

    def test_antigravity_card_renders_pools_credits_and_reset_monitor_without_bloat(self):
        a = self.app
        a.show_antigravity.set(True)
        a._apply_visibility(persist=False)
        now = time.time()
        # Before agy snapshot arrives, personal rows honestly say 待接入 agy while reset works.
        a._on_result("ag_reset", {"ok": True, "data": ag.parse_ag_reset(
            sample_reset_payload(datetime.fromtimestamp(now - 1800, tz=timezone.utc).isoformat(),
                                 "full", datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()), now)}, {})
        self.assertEqual(a.rows["aw"][0].cget("text"), "--")
        self.assertEqual(a.rows["aw"][1].cget("text"), "待接入 agy")
        self.assertEqual(a.rows["ag_reset"][0].cget("text"), "已重置")
        self.assertFalse(a.rows["a3p"][0].winfo_manager())
        self.assertFalse(a.rows["a_credits"][0].winfo_manager())

        # Once agy snapshot arrives, optional 3P pool and AI credits appear cleanly.
        snap_data = {
            "a5_pct": 86, "a5_reset": now + 7200, "a5_disabled": False,
            "aw_pct": 94, "aw_reset": now + 86400 * 4,
            "a3p_pct": 68, "a3p_reset": now + 86400 * 3, "a3p5_pct": 42,
            "a_credits": 42.0, "a_credits_enabled": True, "a_plan": "Pro",
        }
        with patch.object(monitor, "available_sources", return_value={
            "kimi": True, "codex": True, "glm": False, "deepseek": True,
            "antigravity": True, "main": True, "ag_reset": True, "tokens": False,
        }):
            a._on_result("antigravity", {"ok": True, "data": snap_data}, {})
            self.assertEqual(a.section_titles["Antigravity"].cget("text"), "Antigravity · Pro")
            self.assertEqual(a.rows["a5"][0].cget("text"), "86%")
            self.assertEqual(a.rows["aw"][0].cget("text"), "94%")
            self.assertTrue(a.rows["a3p"][0].winfo_manager())
            self.assertEqual(a.rows["a3p"][0].cget("text"), "68%")
            self.assertIn("5h 42%", a.rows["a3p"][1].cget("text"))
            self.assertTrue(a.rows["a_credits"][0].winfo_manager())
            self.assertEqual(a.rows["a_credits"][0].cget("text"), "42")
            self.assertEqual(a.rows["a_credits"][1].cget("text"), "超额已开")
            self.assertTrue(a._bars["aw"].winfo_manager())

        # Free plan hides 5h window automatically unless explicitly overridden.
        a.settings._set_plan("antigravity", "Free")
        self.assertFalse(a.show_antigravity_5h.get())
        a.settings._set_plan("antigravity", "Pro")
        self.assertTrue(a.show_antigravity_5h.get())

    def test_cli_summary_formats_antigravity_and_reset_cleanly(self):
        now = time.time()
        reset_data = ag.parse_ag_reset(sample_reset_payload(
            datetime.fromtimestamp(now - 300, tz=timezone.utc).isoformat(),
            "full", datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()), now)
        report = cli.summary({
            "source": "fresh",
            "sources": {
                "antigravity": {"state": "ok", "error": None, "data": {"a5_pct": 86, "aw_pct": 94, "a_credits": 42}},
                "ag_reset": {"state": "ok", "error": None, "data": cli.safe_data("ag_reset", reset_data)},
            },
        })
        self.assertIn("antigravity: 5小时剩余 86%  每周剩余 94%  AI积分 42", report)
        self.assertIn("ag_reset: 已重置", report)


if __name__ == "__main__":
    unittest.main()
