# Two entrypoints share one runtime: GUI has no console; CLI workers have pipes.
from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root/'quota_monitor.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root/'runtime-files.txt'),'.')],
    hiddenimports=['pystray._win32','compression.zstd'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['unittest','numpy','scipy','PIL.ImageTk','PIL.AvifImagePlugin','PIL._avif'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz,a.scripts,[],exclude_binaries=True,name='quota-widget',console=False,
          debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
          manifest=str(root/'packaging/app.manifest'))
headless = Analysis([str(root/'packaging/cli_entry.py')], pathex=[str(root)],
    binaries=[], datas=[], hiddenimports=['compression.zstd'], hookspath=[],
    excludes=['unittest','tkinter','_tkinter','PIL','pystray','numpy','scipy',
              'widget_dialogs','widget_settings','widget_windows','widget_tray',
              'widget_viewport','widget_onboarding','widget_themes'], noarchive=False)
cli = EXE(PYZ(headless.pure),headless.scripts,[],exclude_binaries=True,name='quota-cli',console=True,
          debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
          manifest=str(root/'packaging/app.manifest'))
coll = COLLECT(gui,cli,a.binaries,a.datas,headless.binaries,headless.datas,
               strip=False,upx=False,name='AIQuotaWidget')
