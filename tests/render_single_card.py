"""Visual evidence for a single card, header width and Chinese quick setup."""
from pathlib import Path
import sys
from unittest.mock import patch
from render_themes import capture, UITests, monitor

out = Path(sys.argv[1]); out.mkdir(parents=True,exist_ok=True)
fixture = UITests()
with patch.object(monitor.ctypes.windll.user32,'GetDpiForSystem',return_value=192):
    fixture.setUp()
try:
    app=fixture.app
    with patch.object(monitor.ctypes.windll.user32,'GetDpiForWindow',return_value=192):
        app.root.attributes('-alpha',1)
        for name in app.CARD_ORDER:
            getattr(app,'show_'+name).set(name=='deepseek')
        app._apply_visibility(persist=False)
        app._on_result('deepseek',{'ok':True,'data':{'ds_balance':105.32,'ds_spend':.11,'ds_currency':'CNY','ds_spend_day':monitor.date.today().isoformat()}},{})
        app._on_result('tokens',{'ok':True,'data':{'ds_tokens_total':5200000,'ds_tokens_day':monitor.date.today().isoformat()}},{})
        app.root.update(); app._fit(); app.root.update()
        capture(app.root,out/'single-card-200.png')
        with patch('quota_cli.configured',return_value={n:False for n in app.CARD_ORDER}):
            app._setup_sources(); app.root.update()
            capture(app._setup_window,out/'quick-setup-200.png',decorated=True)
finally:
    fixture.tearDown()
