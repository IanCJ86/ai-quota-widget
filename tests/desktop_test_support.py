"""Run real Tk tests on a private Windows desktop, never the user's desktop.

Call before importing Tk/pystray. We never call SwitchDesktop. Keeping real
mapped windows preserves geometry/event-loop tests without flashing test data
over the production widget. Failure to isolate is a test failure, not fallback.
"""
import atexit
import ctypes
from ctypes import wintypes
import os

_desktop = None


def isolate_desktop():
    global _desktop
    if os.name != "nt" or _desktop is not None:
        return
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    user.CreateDesktopW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                   ctypes.c_void_p, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_void_p]
    user.CreateDesktopW.restype = wintypes.HANDLE
    user.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    user.SetThreadDesktop.restype = wintypes.BOOL
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    original = user.GetThreadDesktop(kernel.GetCurrentThreadId())
    desktop = user.CreateDesktopW("QuotaTests-" + str(os.getpid()), None, None,
                                  0, 0x01FF, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    if not user.SetThreadDesktop(desktop):
        error = ctypes.get_last_error()
        user.CloseDesktop(desktop)
        raise ctypes.WinError(error)
    _desktop = desktop

    def close():
        if user.SetThreadDesktop(original):
            user.CloseDesktop(desktop)
    atexit.register(close)
