"""New optimisation contracts; actual codecs, only synthetic transcripts."""
from desktop_test_support import isolate_desktop
isolate_desktop()
from datetime import datetime, date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import harness_stats as stats
import test_monitor as fixtures


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.log=self.root/'session.jsonl.zstd'
        self.cache=self.root/'totals.json'
        self.compress=stats._codec().compress

    def row(self,n):
        return (json.dumps(dict(time=datetime.now().timestamp()*1000,
            data=dict(usage=dict(totalTokens=n,inputTokens=2,outputTokens=3))))+'\n').encode()

    def scan(self):
        return stats.totals(self.root,cache_path=self.cache,strict=True)

    def test_append_decodes_only_new_frames_and_same_file_is_a_cache_hit(self):
        first=self.compress(self.row(10))*100
        self.log.write_bytes(first)
        self.assertEqual(self.scan(),dict(total=1000,fresh=500))
        with self.log.open('ab') as f:f.write(self.compress(self.row(7)))
        with patch.object(stats,'_scan_frames',wraps=stats._scan_frames) as scan:
            self.assertEqual(self.scan(),dict(total=1007,fresh=505))
            self.assertEqual(scan.call_args.args[4],len(first))
        with patch.object(stats,'_scan_frames',side_effect=AssertionError('should be cached')):
            self.assertEqual(self.scan(),dict(total=1007,fresh=505))

    def test_middle_rewrite_with_growth_and_truncation_force_full_recount(self):
        block=self.compress(self.row(10))
        first=block*10
        self.log.write_bytes(first);self.scan()
        self.log.write_bytes(block*5+self.compress(self.row(8))+block*4+self.compress(self.row(6)))
        with patch.object(stats,'_scan_frames',wraps=stats._scan_frames) as scan:
            self.assertEqual(self.scan(),dict(total=104,fresh=55))
            self.assertEqual(scan.call_args.args[4],0)
        self.log.write_bytes(self.compress(self.row(1)))
        self.assertEqual(self.scan(),dict(total=1,fresh=5))

    def test_split_json_across_frames_and_newline_checkpoint(self):
        row=self.row(9)
        self.log.write_bytes(self.compress(row[:20])+self.compress(row[20:]))
        self.assertEqual(self.scan(),dict(total=9,fresh=5))
        with self.log.open('ab') as f:f.write(self.compress(self.row(3)))
        self.assertEqual(self.scan(),dict(total=12,fresh=10))

    def test_no_newline_eof_never_double_counts_after_append(self):
        self.log.write_bytes(self.compress(self.row(9).rstrip(b'\n')))
        self.assertEqual(self.scan(),dict(total=9,fresh=5))
        with self.log.open('ab') as f:f.write(self.compress(b'\n'+self.row(3)))
        self.assertEqual(self.scan(),dict(total=12,fresh=10))

    def test_truncated_append_never_publishes_partial_usage(self):
        first=self.compress(self.row(9));tail=self.compress(self.row(3))
        self.log.write_bytes(first);self.scan()
        self.log.write_bytes(first+tail[:-3])
        with self.assertRaises(stats.UsageReadError):self.scan()
        self.log.write_bytes(first+tail)
        self.assertEqual(self.scan(),dict(total=12,fresh=10))

    def test_old_day_or_bad_cache_are_recomputed_without_transcript_storage(self):
        self.log.write_bytes(self.compress(self.row(9)))
        self.cache.write_text(json.dumps(dict(version=3,day=date.today().isoformat(),files={'fake':'bad'})))
        self.assertEqual(self.scan(),dict(total=9,fresh=5))
        cache=self.cache.read_text()
        self.assertNotIn('totalTokens',cache);self.assertNotIn(str(self.log),cache)
        self.assertEqual(stats.totals(self.root,day=date.today()+timedelta(days=1)),dict(total=0,fresh=0))


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.UITests()
        self.fixture.setUp()
        self.app=self.fixture.app

    def tearDown(self):
        self.fixture.tearDown()

    def test_hidden_result_keeps_tray_current_without_layout_or_dpi_work(self):
        a=self.app;a.root.withdraw()
        with patch.object(a,'_render') as render,patch.object(a,'_fit') as fit,patch.object(a,'_update_tray') as tray:
            a._on_result('codex',dict(ok=True,data=dict(cw_pct=50)),{})
            render.assert_not_called();fit.assert_not_called();tray.assert_called_once()
        with patch.object(a.viewport,'update_dpi') as dpi,patch.object(a,'_fit') as fit:
            a._poll();dpi.assert_not_called();fit.assert_not_called()

    def test_native_message_drain_never_creates_a_duplicate_fallback_timer(self):
        a=self.app
        a._commands.put('show')
        with patch.object(a.root,'after') as after:
            a._poll_commands(reschedule=False)
        after.assert_not_called()

    def test_failed_native_wakeup_still_keeps_queued_command_and_fallback(self):
        a=self.app
        a.root.withdraw()
        with patch.object(a._commands,'post',side_effect=OSError('fixture')):
            a._commands.put('show')
        a._poll_commands()
        self.assertNotEqual(a.root.state(),'withdrawn')
        self.assertEqual(a._commands.window.state(),'withdrawn')

    def test_brand_and_renewal_no_longer_consume_green_status(self):
        a=self.app
        for name,palette in fixtures.monitor.THEMES.items():
            a._set_theme(name)
            self.assertNotEqual(palette['CODEX_SOFT'],palette['RADAR_DOWN'])
            if name in ('dark','glass'):
                self.assertEqual(a.section_titles['Codex'].cget('fg'),'#d8dfea')


class EventTests(unittest.TestCase):
    def test_real_tk_mainloop_wakes_promptly_and_closes_during_queued_events(self):
        result=subprocess.run([sys.executable,'-X','faulthandler',str(Path(__file__).with_name('command_event_fixture.py'))],
            capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        evidence=json.loads(result.stdout.strip())
        self.assertEqual(evidence['commands'],50)
        self.assertLess(evidence['max_delay'],.3)
        self.assertTrue(evidence['main_thread_only'])
