"""Offline contracts for adapters; never read real credentials or use network."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quota_monitor as monitor
from monitor_runtime import validate_result


def response(value):
    return io.StringIO(json.dumps(value))


class KimiAdapterTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cred = Path(folder.name) / "fake-credentials.json"
        self.cred.write_text(json.dumps({"access_token": "fake-old", "refresh_token": "fake-refresh",
                                         "expires_at": time.time() + 3600}), encoding="utf-8")
        cred_patch = patch.object(monitor, "KIMI_CRED", str(self.cred))
        cred_patch.start()
        self.addCleanup(cred_patch.stop)
        http_patch = patch.object(monitor, "account_request")
        self.http = http_patch.start()
        self.addCleanup(http_patch.stop)

    def test_usage_windows_and_optional_membership(self):
        self.http.return_value = response({"usage": {"used": 25, "limit": 100, "resetTime": "2030-01-08T00:00:00Z"},
            "limits": [{"window": {"duration": 60}, "detail": {"used": 99, "limit": 100}},
                       {"window": {"duration": 300}, "detail": {"remaining": 40, "limit": 80,
                                                                  "resetTime": "2030-01-01T05:00:00Z"}}]})
        result = validate_result("kimi", monitor.fetch_kimi())
        self.assertEqual((result["kw_pct"], result["k5_pct"]), (75, 50))
        self.assertEqual((result["kw_reset"], result["k5_reset"]), (1894060800, 1893474000))
        self.assertEqual(result["k_plan"], "")
        self.assertEqual(self.http.call_args.args[0].get_header("Authorization"), "Bearer fake-old")
        self.assertEqual(self.http.call_args.args[0].get_header("User-agent"), monitor.USER_AGENT)

    def test_zero_or_malformed_limit_is_unknown_not_full_quota(self):
        self.http.return_value = response({"usage": {"used": 1, "limit": 0},
            "limits": [{"window": {"duration": "bad"}, "detail": {"used": 0, "limit": 100}}]})
        with self.assertRaises(ValueError):
            validate_result("kimi", monitor.fetch_kimi())

    def test_refresh_fallback_persists_rotation_only_to_fake_file(self):
        self.cred.write_text(json.dumps({"access_token": "fake-old", "refresh_token": "fake-refresh",
                                         "expires_at": 1}), encoding="utf-8")
        error = HTTPError("https://example.invalid", 404, "missing", {}, None)
        self.addCleanup(error.close)
        self.http.side_effect = [error,
            response({"access_token": "fake-new", "refresh_token": "fake-rotated", "expires_in": 1000}),
            response({"usage": {"used": 20, "limit": 100}})]
        self.assertEqual(monitor.fetch_kimi()["kw_pct"], 80)
        self.assertEqual(json.loads(self.cred.read_text())["refresh_token"], "fake-rotated")
        self.assertEqual(self.http.call_args.args[0].get_header("Authorization"), "Bearer fake-new")
        self.assertEqual(self.http.call_count, 3)
        for call in self.http.call_args_list:
            self.assertEqual(call.args[0].get_header("User-agent"), monitor.USER_AGENT)

    def test_failed_refresh_keeps_existing_credential_file(self):
        self.cred.write_text(json.dumps({"access_token": "fake-old", "refresh_token": "fake-refresh",
                                         "expires_at": 1}), encoding="utf-8")
        original = self.cred.read_bytes()
        self.http.side_effect = [TimeoutError(), TimeoutError(), response({"usage": {"used": 1, "limit": 2}})]
        self.assertEqual(monitor.fetch_kimi()["kw_pct"], 50)
        self.assertEqual(self.cred.read_bytes(), original)

    def test_usage_auth_error_is_propagated(self):
        self.http.side_effect = HTTPError("https://example.invalid", 401, "invalid", {}, None)
        self.addCleanup(self.http.side_effect.close)
        with self.assertRaises(HTTPError):
            monitor.fetch_kimi()
        self.assertEqual(self.http.call_count, 1)


class RadarAdapterTests(unittest.TestCase):
    def test_uses_display_percentages_not_raw_or_model_probabilities(self):
        body = json.dumps({'probabilities': {'rounded_24h': 50, 'rounded_48h': 75,
            'raw_24h': .18, 'model_24h': 18, 'model_48h': 33},
            'updated_at': '2026-10-16T18:26:26.280Z'}).encode()
        with patch.object(monitor, "_fetch_public_text", return_value=body) as fetch:
            result = validate_result("main", monitor.fetch_main_radar())
        self.assertEqual((result["cr_main24"], result["cr_main48"]), (50, 75))
        self.assertAlmostEqual(result['cr_main_updated'], 1792175186.28)
        fetch.assert_called_once_with('https://codex-reset.com/api/forecast', 'application/json')

    def test_missing_or_bad_probabilities_fail_without_fake_zero(self):
        for value in (b"<html>maintenance</html>",
                      b'[]', b'{}', b'{"probabilities": []}',
                      b'{"probabilities":{"rounded_24h":101}}',
                      b'{"probabilities":{"rounded_24h":true}}',
                      b'{"probabilities":{"rounded_48h":"75"}}',
                      b'{"probabilities":{"rounded_48h":NaN}}',
                      b'{"probabilities":{"rounded_24h":-1}}'):
            with self.subTest(value=value), patch.object(monitor, "_fetch_public_text", return_value=value):
                with self.assertRaises(ValueError):
                    monitor.fetch_main_radar()

    def test_partial_response_does_not_copy_one_window_to_the_other(self):
        with patch.object(monitor, "_fetch_public_text", return_value=
                          b'{"probabilities":{"rounded_48h":0}}'):
            result = validate_result("main", monitor.fetch_main_radar())
        self.assertIsNone(result["cr_main24"])
        self.assertEqual(result["cr_main48"], 0)
        self.assertIsNone(result['cr_main24_at'])
        self.assertIsNotNone(result['cr_main48_at'])

    def test_missing_invalid_or_naive_timestamp_never_becomes_query_time(self):
        for stamp in (None, True, 0, 'bad', '2026-10-17T09:00:00'):
            with self.subTest(stamp=stamp), patch.object(monitor, '_fetch_public_text',
                    return_value=json.dumps({'probabilities': {'rounded_24h': 100},
                                             'updated_at': stamp}).encode()):
                self.assertIsNone(monitor.fetch_main_radar()['cr_main_updated'])

    def test_cache_identity_changes_with_radar_source(self):
        current = monitor.source_identity('main')
        self.assertIsNotNone(current)
        with patch.object(monitor, 'CODEX_RADAR_URL', 'https://old.invalid/'):
            self.assertNotEqual(monitor.source_identity('main'), current)

    def test_public_request_has_no_credentials_and_has_size_limit(self):
        with patch('quota_network.open_request', return_value=io.BytesIO(b"ok")) as http:
            self.assertEqual(monitor._fetch_public_text(monitor.CODEX_RADAR_URL, "application/json"), b"ok")
            req = http.call_args.args[0]
            self.assertIsNone(req.get_header("Authorization"))
            self.assertIsNone(req.get_header("Cookie"))
            self.assertEqual(req.get_header("User-agent"), monitor.USER_AGENT)
            self.assertLessEqual(http.call_args.kwargs["timeout"], 8)
        with patch('quota_network.open_request', return_value=io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))):
            with self.assertRaises(OSError):
                monitor._fetch_public_text(monitor.CODEX_RADAR_URL, "application/json")

    def test_timeout_remains_a_failure(self):
        with patch('quota_network.open_request', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                monitor.fetch_main_radar()


class PricingCalendarTests(unittest.TestCase):
    def test_holidays_and_weekend_makeup_days_are_offpeak(self):
        for month, day in ((1, 2), (2, 16), (4, 6), (5, 4), (6, 19),
                           (9, 25), (10, 1), (10, 7), (10, 10)):
            with self.subTest(month=month, day=day):
                self.assertEqual(monitor.deepseek_peak_label(
                    datetime(2026, month, day, 2, tzinfo=timezone.utc)), monitor.DEEPSEEK_OFFPEAK)

    def test_holiday_edges_use_beijing_date_and_normal_hours_remain(self):
        utc = timezone.utc
        self.assertEqual(monitor.deepseek_peak_label(datetime(2026, 9, 30, 2, tzinfo=utc)), monitor.DEEPSEEK_PEAK)
        self.assertEqual(monitor.deepseek_peak_label(datetime(2026, 10, 8, 2, tzinfo=utc)), monitor.DEEPSEEK_PEAK)
        self.assertEqual(monitor.deepseek_peak_label(datetime(2026, 9, 30, 17, tzinfo=utc)), monitor.DEEPSEEK_OFFPEAK)

    def test_unknown_calendar_year_does_not_assert_peak(self):
        self.assertEqual(monitor.deepseek_peak_label(datetime(2027, 1, 4, 2, tzinfo=timezone.utc)), "")
        self.assertEqual(monitor.deepseek_peak_label(datetime(2027, 1, 4, 12, tzinfo=timezone.utc)), monitor.DEEPSEEK_OFFPEAK)
