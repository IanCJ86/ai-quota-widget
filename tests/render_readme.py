"""Render public README assets from synthetic data, never personal accounts.

Run: python tests/render_readme.py
Uses the real GUI on a private desktop; screenshots are native 200% DPI,
not enlarged 100% images. No desktop switching or real tray/network queries.
"""
from render_themes import capture, UITests, monitor, patch
from pathlib import Path
import time
from PIL import Image


def save_theme_gif(frames, path):
    # GIF logical canvas must fit the largest theme; otherwise taller skins
    # lose their bottom controls when the first frame happens to be shorter.
    size = (max(f.width for f in frames), max(f.height for f in frames))
    padded = []
    try:
        for frame in frames:
            canvas = Image.new('RGB', size, frame.getpixel((0, 0)))
            canvas.paste(frame, (0, 0))
            padded.append(canvas)
        padded[0].save(path, save_all=True, append_images=padded[1:],
                       duration=1400, loop=0, disposal=2)
    finally:
        for canvas in padded:
            canvas.close()


def main():
    output = Path(__file__).resolve().parents[1] / 'docs' / 'images'
    output.mkdir(parents=True, exist_ok=True)
    fixture = UITests()
    with patch.object(monitor.ctypes.windll.user32, 'GetDpiForSystem', return_value=192):
        fixture.setUp()
    frames = []
    try:
        with patch.object(monitor.ctypes.windll.user32, 'GetDpiForWindow', return_value=192):
            app = fixture.app
            monitor.CFG.update(kimi_plan_name='Andante', codex_plan_name='Pro 20x',
                               renew_kimi='10-15', renew_codex='10-20')
            app.root.attributes('-alpha', 1.0)
            now = time.time()
            fixtures = {
                'kimi': dict(k_plan='Andante', k5_pct=62, k5_reset=now+7200,
                             kw_pct=85, kw_reset=now+86400*4),
                'codex': dict(c_plan='Pro', cw_pct=72, cw_reset=now+86400*5,
                              cr_credit_count=1, cr_credit_expiry=now+86400*20),
                'deepseek': dict(ds_balance=128.50, ds_spend=2.35, ds_currency='CNY',
                                 ds_spend_day=monitor.date.today().isoformat()),
                'main': dict(cr_main24=48),
                'tokens': dict(ds_tokens_day=monitor.date.today().isoformat(),
                               ds_tokens_total=12500000),
            }
            for source, data in fixtures.items():
                app._on_result(source, {'ok': True, 'data': data}, {})
            for theme in ('glass', 'dark', 'light', 'steam', 'fuel', 'ink'):
                app._set_theme(theme)
                app.root.update()
                app._fit()
                app.root.update()
                # PNGs are reusable public previews, not temporary captures.
                path = output / ('hero.png' if theme == 'glass' else theme+'.png')
                capture(app.root, path)
                if theme != 'glass':
                    with Image.open(path) as image:
                        frames.append(image.convert('RGB'))
            save_theme_gif(frames, output/'themes.gif')
            print('Rendered glass hero + five-theme GIF with synthetic data')
    finally:
        fixture.tearDown()
        for frame in frames:
            frame.close()


if __name__ == '__main__':
    main()
