"""Exercise actual Win32 popup selection, on our private test desktop only.

Unlike Menu.invoke(), this traverses Tk -> Win32 -> Tk -> Python callbacks.
Synchronous ctypes repaint used to abort Python on this exact path.
"""
import ctypes
from ctypes import wintypes
import faulthandler
import json
import sys

from test_monitor import UITests, monitor


def main():
    faulthandler.enable()
    faulthandler.dump_traceback_later(20, exit=True)
    fixture = UITests()
    fixture.setUp()
    app = fixture.app
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32')
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumThreadWindows.argtypes = [wintypes.DWORD, callback_type, wintypes.LPARAM]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    errors, completed = [], []
    app.root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
    app.show_kimi.set(False)
    app.show_codex.set(False)
    app._apply_visibility()

    def steps(menu, label):
        labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
                  if menu.type(i) != 'separator']
        return [0x28] * (labels.index(label) + 1)  # VK_DOWN, skips separators

    def select(label, submenu=None, item=None):
        windows = []

        @callback_type
        def visit(hwnd, _):
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(hwnd, name, len(name))
            if name.value == '#32768':
                windows.append(hwnd)
            return True

        user.EnumThreadWindows(kernel.GetCurrentThreadId(), visit, 0)
        if len(windows) != 1:
            errors.append('expected one native popup, got ' + str(len(windows)))
            user.EndMenu()
            return
        keys = steps(app.menu, label)
        if submenu is not None:
            # Windows selects the first enabled submenu item on VK_RIGHT.
            keys += [0x27] + steps(submenu, item)[1:]
        keys += [0x0d]  # VK_RETURN
        for key in keys:
            if not user.PostMessageW(windows[0], 0x100, key, 0):
                errors.append('PostMessage failed')
            user.PostMessageW(windows[0], 0x101, key, 0)

    def popup(label, submenu=None, item=None):
        app.root.after(50, lambda: select(label, submenu, item))
        # A single child-widget event must post exactly once. A duplicate
        # toplevel binding would leave a second popup hanging (timeout).
        app.section_titles['DeepSeek'].event_generate(
            '<Button-3>', x=5, y=5, rootx=100, rooty=100)
        app.root.update()
        completed.append(label)
        assert not errors, errors
        assert not app._closed

    try:
        app.root.update()
        theme_index = next(i for i in range(app.menu.index('end') + 1)
                           if app.menu.type(i) == 'cascade'
                           and app.menu.entrycget(i, 'label') == '主题')
        theme_menu = app.menu.nametowidget(app.menu.entrycget(theme_index, 'menu'))
        for theme, palette in monitor.THEMES.items():
            popup('主题', theme_menu, palette['LABEL'])
            assert app.theme == theme
            for expected in (True, False, True, False):
                popup('Kimi Coding Plan')
                assert app.show_kimi.get() == expected
                assert monitor.CFG['show_kimi'] == expected
            popup('Codex')
            assert app.show_codex.get()
            popup('Codex')
            assert not app.show_codex.get()
        for name in ('Moderato', 'Allegro', 'Andante'):
            popup('Kimi Coding Plan 设置', app.settings._provider_menus['kimi'], name)
            assert monitor.CFG['kimi_plan_name'] == name
        app.root.after(50, lambda: select('退出'))
        app.section_titles['DeepSeek'].event_generate(
            '<Button-3>', x=5, y=5, rootx=100, rooty=100)
        if not app._closed:
            app.root.update()
        assert app._closed and not errors, errors
        completed.append('退出')
        print(json.dumps({'completed': len(completed), 'errors': errors}), flush=True)
    finally:
        fixture.tearDown()
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    main()
