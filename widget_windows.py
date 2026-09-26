"""Best-effort native effects. No config, account or application-state access."""
import ctypes


class WindowEffects:
    def __init__(self, root):
        self.root = root

    def _redraw(self):
        """Queue a whole-window repaint, without re-entering Tk from ctypes.

        RDW_UPDATENOW dispatches paint messages synchronously. Inside a native
        popup callback that can re-enter Tk with its Python thread state
        detached and abort the interpreter. Let Tk's event loop paint instead.
        """
        try:
            from ctypes import wintypes
            hwnd = int(self.root.wm_frame(), 16)
            redraw = ctypes.windll.user32.RedrawWindow
            redraw.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.HRGN, wintypes.UINT]
            redraw.restype = wintypes.BOOL
            redraw(hwnd, None, None, 0x0001 | 0x0080)
        except Exception:
            pass

    def _round_corners(self, radius=8):
        """Rounded corners: prefer Win11 DWM native rounding (antialiased)."""
        try:
            from ctypes import wintypes
            hwnd = int(self.root.wm_frame(), 16)
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
            pref = ctypes.c_int(2)
            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            dwm.restype = ctypes.c_long
            ok = dwm(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            if ok == 0:
                return  # DWM handled rounding
        except Exception:
            pass
        # fallback for older Windows: region-based rounding (aliased)
        try:
            from ctypes import wintypes
            hwnd = int(self.root.wm_frame(), 16)
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            create = ctypes.windll.gdi32.CreateRoundRectRgn
            create.argtypes = [ctypes.c_int] * 6
            create.restype = wintypes.HRGN
            assign = ctypes.windll.user32.SetWindowRgn
            assign.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            assign.restype = ctypes.c_int
            delete = ctypes.windll.gdi32.DeleteObject
            delete.argtypes = [wintypes.HANDLE]
            delete.restype = wintypes.BOOL
            rgn = create(0, 0, w + 1, h + 1, radius, radius)
            # _fit queues repaint next; do not dispatch paint from this FFI
            # call either (also covers pre-Win11 fallback).
            if rgn and not assign(hwnd, rgn, False):
                delete(rgn)  # ownership transfers only on successful SetWindowRgn
        except Exception:
            pass

    def _apply_acrylic(self, on):
        """SetWindowCompositionAttribute: ACCENT_ENABLE_ACRYLICBLURBEHIND (4)
        when on, ACCENT_DISABLED (0) when off. Returns True on success."""
        try:
            hwnd = int(self.root.wm_frame(), 16)
            # ABGR tint for acrylic: alpha 0x99, color #1e1e2e (dark slate)
            tint = (0x99 << 24) | (0x2E << 16) | (0x1E << 8) | 0x1E

            class ACCENTPOLICY(ctypes.Structure):
                _fields_ = [("AccentState", ctypes.c_int),
                            ("AccentFlags", ctypes.c_int),
                            ("GradientColor", ctypes.c_uint),
                            ("AnimationId", ctypes.c_int)]

            class WCA(ctypes.Structure):
                _fields_ = [("Attribute", ctypes.c_int),
                            ("Data", ctypes.c_void_p),
                            ("SizeOfData", ctypes.c_size_t)]

            accent = ACCENTPOLICY(4 if on else 0, 0, tint if on else 0, 0)
            data = WCA(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p),
                       ctypes.sizeof(accent))
            from ctypes import wintypes
            apply = ctypes.windll.user32.SetWindowCompositionAttribute
            apply.argtypes = [wintypes.HWND, ctypes.POINTER(WCA)]
            apply.restype = wintypes.BOOL
            return bool(apply(hwnd, ctypes.byref(data)))
        except Exception:
            return False
