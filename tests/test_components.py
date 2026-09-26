"""Component boundaries and identity checks; no real credentials or network."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import ast
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app_version
import quota_monitor as monitor
import widget_tray
import widget_windows


class IdentityTests(unittest.TestCase):
    def test_theme_contract_and_opaque_text_contrast(self):
        self.assertEqual([p['LABEL'] for k, p in monitor.THEMES.items() if k != 'glass'],
                         ['月之暗面', '月之亮面', '蒸汽算力机', 'Token 加油站', '电子墨水账本'])
        def luminance(color):
            values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
            values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
            return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722)))
        for theme, palette in monitor.THEMES.items():
            for color in [palette[k] for k in ('FG_TEXT', 'FG_DIM', 'WARNING', 'DANGER')] + list(palette['BRANDS'].values()):
                a, b = sorted((luminance(color), luminance(palette['BG_CARD'])))
                self.assertGreaterEqual((b + .05) / (a + .05), 4.5, (theme, color))

    def test_cli_version_without_ui_import_or_config_read(self):
        code = (
            "import runpy,sys; sys.argv=['quota_monitor.py','--version']; "
            "\ntry: runpy.run_path('quota_monitor.py',run_name='__main__')"
            "\nexcept SystemExit as e: assert e.code == 0"
            "\nassert 'tkinter' not in sys.modules and 'monitor_runtime' not in sys.modules"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10,
                                **monitor._NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), app_version.APP_VERSION)

    def test_query_mode_does_not_import_ui_components(self):
        code = (
            "import runpy,sys; sys.argv=['quota_monitor.py','--query','unused']; "
            "runpy.run_path('quota_monitor.py',run_name='test_worker_import'); "
            "assert not any(n in sys.modules for n in "
            "('tkinter','pystray','PIL','widget_dialogs','widget_settings','widget_tray','widget_windows','widget_themes'))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10,
                                **monitor._NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_distribution_manifest_covers_every_runtime_module(self):
        files = (ROOT / "runtime-files.txt").read_text().splitlines()
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(set(files), {p.name for p in ROOT.glob('*.py')})

    def test_version_format_and_rpc_identity(self):
        self.assertRegex(app_version.APP_VERSION, r'^\d+\.\d+\.\d+(?:-dev)?$')
        self.assertEqual(app_version.USER_AGENT, 'ai-quota-widget/' + app_version.APP_VERSION)
        tree = ast.parse((ROOT / 'quota_monitor.py').read_text(encoding='utf-8'))
        # RPC is a local process, not HTTP: it must use the same identity source.
        initializers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
                        and n.args[1].value == 'initialize']
        self.assertEqual(len(initializers), 1)
        self.assertIn('APP_VERSION', ast.unparse(initializers[0]))

    def test_authenticated_http_adapters_use_versioned_ua(self):
        cases = [
            ('glm_api_key', monitor.fetch_glm, {'limits': []}),
            ('deepseek_api_key', monitor.fetch_deepseek,
             {'balance_infos': [{'currency': 'CNY', 'total_balance': '10'}]}),
        ]
        for key_name, fetch, payload in cases:
            with self.subTest(provider=key_name), patch.object(monitor, key_name, return_value='fake'), \
                    patch.object(monitor, 'deepseek_spend', return_value=0), \
                    patch.object(monitor.urllib.request, 'urlopen',
                                 return_value=io.StringIO(json.dumps(payload))) as http:
                fetch()
                self.assertEqual(http.call_args.args[0].get_header('User-agent'), app_version.USER_AGENT)


class TrayComponentTests(unittest.TestCase):
    def test_missing_dependency_keeps_tray_unavailable(self):
        tray = widget_tray.TrayIcon(queue.SimpleQueue())
        with patch.object(widget_tray, 'pystray', None):
            tray.start()
        self.assertTrue(tray.failed)
        self.assertFalse(tray.available)
        tray.stop()

    def test_native_callbacks_only_enqueue_commands(self):
        commands = queue.SimpleQueue()
        tray = widget_tray.TrayIcon(commands)
        with patch.object(widget_tray.pystray, 'Icon') as icon, \
                patch.object(widget_tray.threading, 'Thread') as thread:
            tray.start()
            menu = icon.call_args.args[3]
            for item in menu.items:
                item(icon.return_value)
            self.assertEqual([commands.get_nowait() for _ in range(3)], ['show', 'refresh', 'quit'])
            thread.return_value.start.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            tray.stop()
            icon.return_value.stop.assert_called_once()

    def test_tray_thread_failure_uses_queue(self):
        commands = queue.SimpleQueue()
        tray = widget_tray.TrayIcon(commands)
        tray.icon = Mock()
        tray.icon.run.side_effect = RuntimeError('test-only')
        tray._run()
        self.assertEqual(commands.get_nowait(), 'tray_failed')


class NativeEffectsTests(unittest.TestCase):
    def test_acrylic_uses_pointer_sized_window_handle(self):
        from ctypes import wintypes
        root = Mock()
        root.wm_frame.return_value = hex(2**40 + 7)
        api = Mock(return_value=1)
        with patch.object(widget_windows.ctypes.windll.user32, 'SetWindowCompositionAttribute', api):
            self.assertTrue(widget_windows.WindowEffects(root)._apply_acrylic(True))
        self.assertEqual(api.argtypes[0], wintypes.HWND)
        self.assertEqual(api.call_args.args[0], 2**40 + 7)

    def test_failed_native_effects_have_safe_fallback(self):
        root = Mock()
        root.wm_frame.side_effect = RuntimeError('unsupported')
        effects = widget_windows.WindowEffects(root)
        self.assertFalse(effects._apply_acrylic(True))
        effects._redraw()
        effects._round_corners()
