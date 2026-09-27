"""First-machine feedback: single card, high DPI, no key and hit testing."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import test_monitor as fixtures
monitor = fixtures.monitor


class FirstRunTests(unittest.TestCase):
    setUp = fixtures.UITests.setUp
    tearDown = fixtures.UITests.tearDown

    def test_single_card_header_and_notes_fit_at_multiple_dpi(self):
        a = self.app
        a.show_kimi.set(False)
        a.show_codex.set(False)
        a.show_glm.set(False)
        a.show_deepseek.set(True)
        a._apply_visibility(persist=False)
        for dpi in (96, 120, 144, 192, 240, 96):
            with self.subTest(dpi=dpi), patch.object(monitor.ctypes.windll.user32, 'GetDpiForWindow', return_value=dpi):
                a.viewport.update_dpi(a)
                for amount in (None, .08, 105.32, 12345.67):
                    a._set_amount('ds', amount, 'CNY', '梁文谷 时段')
                    a._set_amount('ds_spend', amount, 'CNY', '439M tok')
                    a._fit()
                    a.root.update()
                    head = a.section_renews['DeepSeek']
                    self.assertLessEqual(head.winfo_x()+head.winfo_reqwidth(), head.master.winfo_width())
                    title = a.section_titles['DeepSeek']
                    self.assertLessEqual(title.winfo_reqheight(), title.master.winfo_height())
                    for pl, rl in (a.rows['ds'], a.rows['ds_spend']):
                        for label in (pl, rl):
                            self.assertLessEqual(label.winfo_x()+label.winfo_reqwidth(), label.master.winfo_width())
                    self.assertGreaterEqual(a.content.winfo_width(), a.viewport.canvas.winfo_width()-1)

    def test_glass_has_no_click_through_colour_key(self):
        a = self.app
        a._set_theme('glass')
        a.root.update()
        self.assertEqual(a.root.attributes('-transparentcolor'), '')
        api = ctypes.windll.user32.GetLayeredWindowAttributes
        api.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
                        ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD)]
        color, alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(), wintypes.DWORD()
        self.assertTrue(api(int(a.root.wm_frame(),16), ctypes.byref(color), ctypes.byref(alpha), ctypes.byref(flags)))
        self.assertFalse(flags.value & 1, 'LWA_COLORKEY makes background mouse-transparent')
        self.assertEqual(a.root.cget('bg'), a._cards[-1].cget('bg'))

    def test_startup_writes_diagnostics_without_worker_completion(self):
        path = Path(monitor.DEBUG_FILE)
        self.assertTrue(path.is_file())
        evidence = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(evidence['success_at'], {})
        self.assertIsNone(evidence['ui_error'])

    def test_api_only_install_does_not_wait_for_missing_harness_logs_or_show_codex_tray(self):
        a = self.app
        for name in a.CARD_ORDER:
            getattr(a,'show_'+name).set(name=='deepseek')
        with patch.object(monitor,'DSH_SESSIONS',str(Path(self.tmp.name)/'not-installed')):
            a._apply_visibility(persist=False)
            self.assertEqual(a._enabled_sources(), ['deepseek'])
        a.tray_controller.icon = Mock()
        a.tray_controller.image = Mock()
        a.data['cw_pct']=75
        a._update_tray()
        self.assertIn('DeepSeek 今日估算（非账单） --', a.tray_controller.icon.title)
        self.assertNotIn('Codex', a.tray_controller.icon.title)
        a.tray_controller.image.assert_called_once_with(None, True, amount=True)

    def test_setup_can_be_skipped_and_reopened_without_network_wait(self):
        a = self.app
        with patch('quota_cli.configured', return_value={n:False for n in a.CARD_ORDER}):
            a._setup_sources()
            first = a._setup_window
            a._setup_sources()
            self.assertIs(first, a._setup_window)
            buttons = first.winfo_children()[0].winfo_children()
            next(w for w in buttons if w.winfo_class() == 'TButton' and w.cget('text') == '稍后设置').invoke()
            self.assertFalse(first.winfo_exists())
            a._setup_sources()
            self.assertIsNot(first, a._setup_window)


if __name__ == '__main__':
    unittest.main()
