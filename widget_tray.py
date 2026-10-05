"""Thread-owned Windows tray. Tk is only reached through a command queue."""
import threading
import queue
from decimal import Decimal, ROUND_HALF_UP
from quota_state import finite


class CommandInbox(queue.SimpleQueue):
    """Post to a private, withdrawn Tk message window; no worker calls Tcl.

    Its WM_CLOSE protocol is a command signal, NOT the visible widget's close
    operation. Tk dispatches the Python callback on its owner thread, including
    unthreaded Windows Tcl builds. A slow timer still covers a failed message.
    """
    def __init__(self):
        super().__init__()
        self.closed = threading.Event()
        self.window = None
        self.hwnd = None
        self.post = None

    def put(self, value, block=True, timeout=None):
        if self.closed.is_set():
            return
        super().put(value)
        hwnd, post = self.hwnd, self.post
        if hwnd and post:
            try:
                post(hwnd, 0x10, 0, 0)  # asynchronous, never SendMessage
            except Exception:
                pass  # command remains queued for the low-frequency fallback

    def attach(self, root, callback):
        """Main thread only; the internal window never maps onto the desktop."""
        try:
            import tkinter as tk
            import ctypes
            from ctypes import wintypes
            channel = tk.Toplevel(root)
            channel.withdraw()
            channel.title('AIQuotaWidgetCommandChannel')
            channel.protocol('WM_DELETE_WINDOW', callback)
            channel.update_idletasks()
            self.window = channel
            self.hwnd = int(channel.wm_frame(), 16)
            post = ctypes.windll.user32.PostMessageW
            post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            post.restype = wintypes.BOOL
            self.post = post
        except Exception:
            self.hwnd = self.post = None

    def close(self):
        self.closed.set()
        self.hwnd = self.post = None


def rounded_amount(value):
    """Money uses ordinary half-up rounding, not Python's ties-to-even round."""
    if not finite(value) or value < 0:
        return None
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    pystray = None


class TrayIcon:
    def __init__(self, commands):
        self.commands = commands
        self.icon = None
        self.thread = None
        self.failed = False
        self.last_value = object()

    @property
    def available(self):
        return bool(self.icon and self.icon.visible and self.thread and self.thread.is_alive())

    @property
    def state(self):
        if self.failed:
            return 'failed'
        if self.available:
            return 'ready'
        if self.thread and self.thread.is_alive():
            return 'starting'
        return 'not_started'

    def start(self):
        if pystray is None:
            self.failed = True
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示额度监控", lambda *args: self.commands.put("show"), default=True),
            pystray.MenuItem("立即刷新", lambda *args: self.commands.put("refresh")),
            pystray.MenuItem("退出", lambda *args: self.commands.put("quit")),
        )
        try:
            self.icon = pystray.Icon("quota-monitor", self.image(None), "AI 额度监控", menu)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        except Exception:
            self.icon = None
            self.failed = True

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            self.commands.put("tray_failed")

    def stop(self):
        if self.icon is not None:
            self.icon.stop()

    @staticmethod
    def image(value, stale=False, amount=False):
        """Transparent number; spending is not a remaining-percent warning."""
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        pct = rounded_amount(value) if amount else int(value) if finite(value) else None
        color = (131, 212, 171, 255) if pct is None or pct > 30 else (
            (208, 128, 32, 255) if pct > 15 else (208, 64, 64, 255))
        if amount:
            color = (77, 107, 254, 255)  # DeepSeek blue, readable on light and dark taskbars
        if stale:
            color = (155, 155, 165, 255)
        text = "--" if pct is None else str(pct)
        if amount and pct is not None and pct > 999:
            text = '999+'  # exact amount remains available in the tooltip
        try:
            size = 46 if pct is not None and len(text) <= 2 else 34 if len(text) <= 3 else 26
            font = ImageFont.truetype(r"C:\Windows\Fonts\calibrib.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        x = (64 - (box[2] - box[0])) / 2
        y = (64 - (box[3] - box[1])) / 2 - 9
        draw.text((x, y), text, fill=color, font=font)
        return image
