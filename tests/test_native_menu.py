"""Keep native popup regressions out of the main test interpreter."""
from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from widget_windows import WindowEffects


class NativeMenuTests(unittest.TestCase):
    def test_native_popup_visibility_and_plan_selection(self):
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler',
             str(Path(__file__).with_name('native_menu_fixture.py'))],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.strip())
        self.assertEqual(evidence, {'completed': 46, 'errors': []})

    def test_native_redraw_never_dispatches_paint_synchronously(self):
        root = Mock()
        root.wm_frame.return_value = '0x123'
        with patch('ctypes.windll.user32.RedrawWindow') as redraw:
            WindowEffects(root)._redraw()
        redraw.assert_called_once_with(0x123, None, None, 0x81)

    def test_legacy_rounding_also_defers_paint(self):
        root = Mock()
        root.wm_frame.return_value = '0x123'
        root.winfo_width.return_value = 200
        root.winfo_height.return_value = 100
        with patch('ctypes.windll.dwmapi.DwmSetWindowAttribute', return_value=-1), \
             patch('ctypes.windll.gdi32.CreateRoundRectRgn', return_value=0x456), \
             patch('ctypes.windll.user32.SetWindowRgn', return_value=1) as assign:
            WindowEffects(root)._round_corners()
        assign.assert_called_once_with(0x123, 0x456, False)


if __name__ == '__main__':
    unittest.main()
