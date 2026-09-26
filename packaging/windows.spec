# Two entrypoints share one runtime: GUI has no console; CLI workers have pipes.
from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root/'quota_monitor.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root/'runtime-files.txt'),'.')],
    hiddenimports=['pystray._win32','PIL.ImageTk','compression.zstd'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['unittest'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz,a.scripts,[],exclude_binaries=True,name='quota-widget',console=False,
          debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
          manifest=str(root/'packaging/app.manifest'))
cli = EXE(pyz,a.scripts,[],exclude_binaries=True,name='quota-cli',console=True,
          debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
          manifest=str(root/'packaging/app.manifest'))
coll = COLLECT(gui,cli,a.binaries,a.datas,strip=False,upx=False,name='AIQuotaWidget')
