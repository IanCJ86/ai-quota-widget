"""DSH-only visual QA using an isolated desktop and synthetic data."""
from render_themes import capture, UITests, monitor, patch
from widget_tray import TrayIcon
from pathlib import Path
import sys


def render(output):
    output.mkdir(parents=True,exist_ok=True)
    for dpi in (96,144):
        fixture=UITests()
        with patch.object(monitor.ctypes.windll.user32,'GetDpiForSystem',return_value=dpi):
            fixture.setUp()
        try:
            with patch.object(monitor.ctypes.windll.user32,'GetDpiForWindow',return_value=dpi):
                a=fixture.app
                for name in ('kimi','codex','glm'):getattr(a,'show_'+name).set(False)
                a.show_deepseek.set(True);a._apply_visibility(persist=False)
                a._set_theme('glass')
                a._on_result('deepseek',dict(ok=True,data=dict(ds_balance=102.23,ds_spend=.01,
                    ds_currency='CNY',ds_spend_day=monitor.date.today().isoformat())),{})
                a._on_result('tokens',dict(ok=True,data=dict(ds_tokens_total=31700000,
                    ds_tokens_day=monitor.date.today().isoformat())),{})
                a.root.update();a._fit();a.root.update()
                path=output/f'deepseek-glass-{dpi*100//96}.png'
                capture(a.root,path);print(path)
        finally:fixture.tearDown()
    for value in (0,.5,2.5,100.5,1000):
        image=TrayIcon.image(value,amount=True)
        image.save(output/f'tray-{value}.png');image.close()


if __name__=='__main__':render(Path(sys.argv[1]))
