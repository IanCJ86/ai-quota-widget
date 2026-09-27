"""DSH-only presentation; synthetic state, no credentials or real tray."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import json
from pathlib import Path
import queue
import time
import unittest
from unittest.mock import Mock, patch
import test_monitor as fixtures
from widget_tray import TrayIcon, rounded_amount
from quota_state import validate_config

monitor = fixtures.monitor


class MoneyIconTests(unittest.TestCase):
    def test_half_up_and_invalid(self):
        for value, expected in ((0,0),(.01,0),(.49,0),(.5,1),(2.5,3),(99.5,100),
                                (100.5,101),(1000,1000),(-1,None),(None,None),
                                (float('nan'),None),(float('inf'),None),(True,None)):
            self.assertEqual(rounded_amount(value),expected)

    def test_amount_not_low_percentage_alarm_and_large_amount_fits(self):
        import widget_tray
        with patch.object(widget_tray.ImageDraw,'Draw') as painter:
            draw=painter.return_value
            draw.textbbox.return_value=(0,0,50,36)
            for value,expected in ((.49,'0'),(.5,'1'),(2.5,'3'),(100.5,'101'),(1000,'999+'),(None,'--')):
                TrayIcon.image(value,amount=True)
                self.assertEqual(draw.text.call_args.args[1],expected)
                self.assertEqual(draw.text.call_args.kwargs['fill'],(77,107,254,255))
            TrayIcon.image(2.5,True,amount=True)
            self.assertEqual(draw.text.call_args.kwargs['fill'],(155,155,165,255))

    def test_config_accepts_new_metric(self):
        cfg,issues=validate_config({'tray_metric':'ds_spend'},monitor.DEFAULT_CONFIG)
        self.assertEqual(cfg['tray_metric'],'ds_spend')
        self.assertFalse(issues)

    def test_registration_is_starting_not_failed(self):
        tray=TrayIcon(queue.SimpleQueue())
        self.assertEqual(tray.state,'not_started')
        tray.thread=Mock();tray.thread.is_alive.return_value=True
        tray.icon=Mock(visible=False)
        self.assertEqual(tray.state,'starting')
        tray.icon.visible=True
        self.assertEqual(tray.state,'ready')
        tray.failed=True
        self.assertEqual(tray.state,'failed')


class DshOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.UITests();self.fixture.setUp();self.app=self.fixture.app
        for source in ('kimi','codex','glm'):
            getattr(self.app,'show_'+source).set(False)
        self.app.show_deepseek.set(True)
        self.app._apply_visibility(persist=False)
        self.app.tray_controller.icon=Mock(title='',visible=True)
        self.app.tray_controller.image=Mock(return_value='image')

    def tearDown(self): self.fixture.tearDown()

    def good(self):
        self.app._on_result('deepseek',dict(ok=True,data=dict(ds_balance=102.23,ds_spend=2.5,
                           ds_currency='CNY',ds_spend_day=monitor.date.today().isoformat())),{})

    def test_only_deepseek_auto_selects_spend_and_precise_tooltip(self):
        self.assertEqual(monitor.CFG['tray_metric'],'ds_spend')
        self.good();a=self.app;a._update_tray()
        self.assertEqual(a.tray_controller.image.call_args.args,(2.5,False))
        self.assertEqual(a.tray_controller.image.call_args.kwargs,{'amount':True})
        self.assertIn('今日估算（非账单） 2.50 CNY',a.tray_controller.icon.title)
        self.assertNotIn('%',a.tray_controller.icon.title)

    def test_midnight_error_and_missing_baseline_never_show_old_spend_as_today(self):
        for fields in ({'ds_spend_day':'2000-01-01'}, {'ds_spend_error':'SpendWriteFailed'},
                       {'ds_spend':None}, {'ds_spend':float('nan')}):
            self.good();a=self.app;a.data.update(fields);a._update_tray()
            self.assertIsNone(a.tray_controller.image.call_args.args[0])
            self.assertIn('--',a.tray_controller.icon.title)

    def test_failure_preserves_old_amount_but_marks_stale(self):
        self.good();a=self.app
        a._on_result('deepseek',dict(ok=False,error='Timeout'),{});a._update_tray()
        self.assertEqual(a.tray_controller.image.call_args.args,(2.5,True))
        self.assertIn('旧数据',a.tray_controller.icon.title)

    def test_no_key_has_no_fake_zero(self):
        a=self.app
        with patch.object(monitor,'deepseek_api_key',return_value=''):
            a._sync_credentials();a._update_tray()
            self.assertIsNone(a.tray_controller.image.call_args.args[0])

    def test_icon_not_allocated_on_every_poll(self):
        self.good();a=self.app;a._update_tray()
        calls=a.tray_controller.image.call_count
        for _ in range(50):a._update_tray()
        self.assertEqual(a.tray_controller.image.call_count,calls)

    def test_glass_keeps_colors_without_acrylic_or_color_key(self):
        a=self.app
        with patch.object(a,'_apply_acrylic',return_value=False) as effect:
            a._set_theme('glass')
        effect.assert_called_once_with(False)
        self.good();a.root.update_idletasks()
        p=monitor.THEMES['glass']
        self.assertFalse(a._acrylic_on)
        self.assertEqual(a.root.attributes('-transparentcolor'),'')
        self.assertEqual(a.section_titles['DeepSeek'].cget('fg'),p['BRANDS']['DeepSeek'])
        self.assertEqual(a.section_renews['DeepSeek'].cget('fg'),p['DEEPSEEK_SOFT'])
        self.assertEqual(a.rows['ds'][0].cget('fg'),p['FG_TEXT'])
        self.assertEqual(a.rows['ds'][1].cget('fg'),p['FG_DIM'])
        self.assertNotEqual(p['FG_DIM'],p['FG_TEXT'])

    def test_debug_tray_registration_state_updates_without_query(self):
        a=self.app;a.tray_controller.thread=Mock()
        a.tray_controller.thread.is_alive.return_value=True
        a.tray_controller.icon.visible=False
        a._write_debug()
        path=Path(monitor.DEBUG_FILE)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['tray']['state'],'starting')
        a.tray_controller.icon.visible=True
        with patch.object(a.root,'after'):a._poll()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['tray']['state'],'ready')


class SpendContinuityTests(unittest.TestCase):
    def test_same_day_gap_recovered_but_new_day_or_topup_cannot_reconstruct(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(monitor,'DEEPSEEK_SPEND_FILE',str(Path(directory)/'spend.json')):
            read=lambda balance,day:monitor.deepseek_spend(balance,today=day,scope='synthetic')
            self.assertEqual(read(100,'2026-09-27'),0)
            self.assertEqual(read(90,'2026-09-27'),10)  # restart/gap, same saved baseline
            self.assertEqual(read(80,'2026-09-28'),0)   # cannot allocate midnight gap
            self.assertEqual(read(95,'2026-09-28'),0)   # topup+consumption cannot be split
