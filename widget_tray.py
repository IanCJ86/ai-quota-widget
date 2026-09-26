"""Thread-owned Windows tray. Tk is only reached through a command queue."""
import threading

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
    def image(value, stale=False):
        """Create a transparent tray icon showing the selected percentage."""
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        pct = int(value) if value is not None else None
        color = (131, 212, 171, 255) if pct is None or pct > 30 else (
            (208, 128, 32, 255) if pct > 15 else (208, 64, 64, 255))
        if stale:
            color = (155, 155, 165, 255)
        text = "--" if pct is None else str(pct)
        try:
            size = 46 if pct is not None and len(text) <= 2 else 34
            font = ImageFont.truetype(r"C:\Windows\Fonts\calibrib.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        x = (64 - (box[2] - box[0])) / 2
        y = (64 - (box[3] - box[1])) / 2 - 9
        draw.text((x, y), text, fill=color, font=font)
        return image
