"""Refresh explanations and bounded, privacy-safe history; no real accounts."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_monitor as fixtures
import test_release as release_fixtures
from monitor_runtime import QueryHistory, Scheduler
from quota_state import refresh_notice
import quota_cli


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'history.json'
        self.history = QueryHistory(self.path)

    def event(self, **values):
        return dict(at=10000, source='codex', event='result', **values)

    def test_failure_survives_success_and_restart(self):
        self.history.record(self.event(ok=False, error='HTTP401', attempt=1))
        self.history.record(self.event(ok=True))
        rows = QueryHistory(self.path).events
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['error'], 'HTTP401')
        self.assertTrue(rows[1]['ok'])

    def test_capacity_and_privacy(self):
        for i in range(205):
            self.history.record(self.event(ok=False, error='FAKE-SECRET',
                                           data={'balance':987654321}, path='PRIVATE', attempt=i))
        history = QueryHistory(self.path)
        self.assertEqual(len(history.events), 200)
        self.assertEqual(history.events[0]['attempt'], 5)
        text = self.path.read_text()
        for forbidden in ('FAKE-SECRET', '987654321', 'PRIVATE'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(history.events[-1]['error'], 'QueryFailed')

    def test_malformed_history_is_bounded_and_recovers(self):
        for content in ('broken', '{}', ' ' * (QueryHistory.MAX_BYTES+1)):
            self.path.write_text(content)
            history = QueryHistory(self.path)
            self.assertTrue(history.failed)
            history.record(self.event(ok=True))
            self.assertFalse(history.failed)
            self.assertEqual(len(QueryHistory(self.path).events), 1)

    def test_disk_failure_does_not_lose_in_memory_events(self):
        with patch('monitor_runtime.atomic_json', side_effect=PermissionError()):
            self.history.record(self.event(ok=False, error='Timeout'))
        self.assertTrue(self.history.failed)
        self.history.record(self.event(ok=True))
        self.assertFalse(self.history.failed)
        self.assertEqual(len(QueryHistory(self.path).events), 2)

    def test_invalid_and_nonfinite_fields(self):
        for row in (None, [], {}, dict(at=float('nan'),source='codex',event='start'),
                    dict(at=10000,source='PRIVATE',event='start')):
            self.history.record(row)
        self.assertFalse(self.path.exists())
        self.history.record(self.event(ok=False, error={'key':'FAKE'}, duration_seconds=float('inf')))
        row = self.history.events[0]
        self.assertNotIn('duration_seconds', row)
        self.assertEqual(row['error'], 'QueryFailed')


class SchedulerEventTests(unittest.TestCase):
    def test_retries_recovery_idle_and_gap(self):
        clock = fixtures.Clock()
        events = []
        results = []
        s = Scheduler('', lambda *x:results.append(x), factory=fixtures.Worker,
                      monotonic=lambda:clock.now, wall=lambda:clock.wall, on_event=events.append)
        self.addCleanup(s.close)
        s.configure(['codex'])
        for attempt, delay in ((1,2),(2,5),(3,300)):
            s.tick()
            self.assertEqual(events[-1]['event'], 'start')
            self.assertEqual(events[-1]['attempt'], attempt)
            worker = s.states['codex']['worker']
            worker.done = True
            worker.payload = dict(ok=False,error='Timeout')
            s.tick()
            self.assertEqual(events[-1]['retry_in_seconds'], delay)
            count = len(events)
            s.tick()
            self.assertEqual(len(events), count)  # idle polling never writes history
            clock.advance(delay)
        s.tick()
        worker = s.states['codex']['worker']
        worker.done = True
        s.tick()
        self.assertTrue(events[-1]['ok'])
        self.assertEqual(len(results), 4)
        self.assertTrue(any(e['event']=='loop_gap' for e in events))

    def test_diagnostic_callback_cannot_break_query(self):
        def broken(event): raise OSError('disk unavailable')
        s = Scheduler('', lambda *x:None, factory=fixtures.Worker, on_event=broken)
        self.addCleanup(s.close)
        s.configure(['codex']); s.tick()
        s.states['codex']['worker'].done = True
        s.tick()
        self.assertIsNone(s.states['codex']['error'])


class NoticeTests(unittest.TestCase):
    def test_distinguish_states_and_priority(self):
        self.assertEqual(refresh_notice(['codex'], {}), '刷新中:1')
        self.assertEqual(refresh_notice(['codex'], {'codex':'Timeout'}), '请求超时:1·重试中')
        self.assertEqual(refresh_notice([], {'kimi':'HTTP401'}), '需重新认证:1')
        self.assertEqual(refresh_notice([], {'kimi':'HTTP401','codex':'Timeout'}), '部分失败:2')
        self.assertEqual(refresh_notice([], {}, ['codex']), '数据过旧:1')
        self.assertEqual(refresh_notice([], {}, ['codex'], ['codex']), '窗口已过期:1')
        self.assertEqual(refresh_notice([], {}, ['codex'], [], ['codex']), '缓存待核验:1')
        self.assertEqual(refresh_notice([], {}), '')


class HistoryGuiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.UITests(); self.fixture.setUp(); self.app = self.fixture.app
    def tearDown(self): self.fixture.tearDown()

    def test_error_clears_after_success_and_recording_failure_is_separate(self):
        a = self.app
        a._on_result('codex',dict(ok=False,error='URLError'),{})
        self.assertIn('连接失败', a.status.cget('text'))
        a._on_result('codex',dict(ok=True,data={'cw_pct':75}),{})
        self.assertNotIn('连接失败', a.status.cget('text'))
        a.history.failed = True; a._render()
        self.assertIn('记录失败', a.status.cget('text'))
        self.assertFalse(a._is_stale('codex'))

    def test_active_poll_updates_footer_without_waiting_a_minute(self):
        a = self.app
        a.scheduler.configure(['codex'])
        def start(): a.scheduler.states['codex']['worker'] = fixtures.Worker('', 'codex')
        with patch.object(a.scheduler,'tick',side_effect=start), patch.object(a.root,'after'):
            a._poll()
        self.assertIn('刷新中:1', a.status.cget('text'))

    def test_tokens_only_still_has_refresh_status(self):
        a = self.app
        with patch.object(a,'_enabled_sources',return_value=['tokens']):
            a._on_result('tokens',dict(ok=True,data={'ds_tokens_total':1234,
                         'ds_tokens_day':fixtures.monitor.date.today().isoformat()}),{})
            self.assertIn('刷新时间', a.status.cget('text'))
            self.assertNotIn('快速设置', a.status.cget('text'))


class HistoryDoctorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = release_fixtures.CliTests(); self.fixture.setUp()
        self.fixture.flags['deepseek'] = True
    def tearDown(self): self.fixture.doCleanups()

    def test_past_failure_visible_but_does_not_fail_current_health(self):
        path = Path(fixtures.monitor.DEBUG_FILE).with_name('query-history.json')
        path.write_text(json.dumps([dict(at=10000,source='codex',event='result',
                                        ok=False,error='HTTP401',secret='PRIVATE'),
                                   dict(at=10001,source='codex',event='result',ok=True)]))
        with patch.object(quota_cli,'module_available',return_value=True):
            report, code = quota_cli.doctor(fixtures.monitor)
        self.assertEqual(code, 0)
        self.assertIn('需重新认证', report)
        self.assertIn('成功', report)
        self.assertNotIn('PRIVATE', report)
        self.assertIn('历史失败不代表当前仍失败', report)
