"""Capture the real Tk widget on a private desktop using only fixture data.

Usage: python tests/render_themes.py OUTPUT_DIRECTORY [DPI_PERCENT]
Never switches desktops, reads user credentials, or launches the real tray.
PrintWindow captures our HWND, unlike a desktop-grab helper which cannot see
this isolated desktop. Output is for visual QA, not a second UI implementation.
"""
from desktop_test_support import isolate_desktop
isolate_desktop()
import ctypes
from ctypes import wintypes
from pathlib import Path
import struct
import sys
import time
from unittest.mock import patch
from PIL import Image
from test_monitor import UITests, monitor


def capture(root, path, decorated=False):
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    hwnd = int(root.wm_frame(), 16)
    w, h = root.winfo_width(), root.winfo_height()
    if decorated:
        rectangle = wintypes.RECT()
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        if not user.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            raise OSError('GetWindowRect failed')
        w, h = rectangle.right-rectangle.left, rectangle.bottom-rectangle.top
    screen = user.GetDC(hwnd)
    dc = gdi.CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40,w,-h,1,32,0,w*h*4,0,0,0,0))
    bitmap = gdi.CreateDIBSection(screen, info, 0, ctypes.byref(bits), None, 0)
    previous = gdi.SelectObject(dc, bitmap)
    try:
        if not user.PrintWindow(hwnd, dc, 2):
            raise OSError('PrintWindow failed')
        Image.frombytes('RGB', (w,h), ctypes.string_at(bits, w*h*4), 'raw', 'BGRX').save(path)
    finally:
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)
        user.ReleaseDC(hwnd, screen)


if __name__ == '__main__':
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    dpi = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    fixture = UITests()
    # App obtains system DPI early; emulate each monitor scale explicitly.
    with patch.object(monitor.ctypes.windll.user32, 'GetDpiForSystem', return_value=96*dpi//100):
        fixture.setUp()
    dpi_patch = patch.object(monitor.ctypes.windll.user32,'GetDpiForWindow',return_value=96*dpi//100)
    dpi_patch.start()
    try:
        a = fixture.app
        a.root.attributes('-alpha', 1.0)
        monitor.CFG.update(kimi_plan_name='Andante',codex_plan_name='Pro 20x',
                           renew_kimi='10-03',renew_codex='10-05')
        now = time.time()
        for source, data in {
            'kimi': dict(k_plan='Andante',k5_pct=41,k5_reset=now+10000,kw_pct=88,kw_reset=now+86400*4),
            'codex': dict(c_plan='Pro',cw_pct=76,cw_reset=now+86400*5,cr_credit_count=1,cr_credit_expiry=now+86400*20),
            'deepseek': dict(ds_balance=107.27,ds_spend=11.46,ds_currency='CNY'),
            'main': dict(cr_main24=82),
            'tokens': dict(ds_tokens_day=monitor.date.today().isoformat(),ds_tokens_total=439000000),
        }.items():
            a._on_result(source, {'ok':True,'data':data}, {})
        for theme in ('dark','light','steam','fuel','ink'):
            a._set_theme(theme)
            a.root.update()
            a._fit()
            a.root.update()
            canvas = a.theme_painter.canvas
            for item in canvas.find_all():
                if canvas.type(item) == 'text':
                    box = canvas.bbox(item)
                    assert box[0] >= 0 and box[2] <= canvas.winfo_width(), (theme, dpi, box)
                    assert box[1] >= 0 and box[3] <= canvas.winfo_height(), (theme, dpi, box)
            path = output / f'{theme}-{dpi}.png'
            capture(a.root, path)
            print(path)
    finally:
        fixture.tearDown()
        dpi_patch.stop()
