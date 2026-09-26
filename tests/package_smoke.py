"""Test the real distributable in isolated directories, without account queries."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_version import APP_VERSION

wheel = Path(sys.argv[1]).resolve()
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    manifest = archive.read('quota_assets/runtime-files.txt').decode().splitlines()
    assert all(name in names for name in manifest)
    assert not any(name.endswith(('.dpapi','debug.txt','last-good.json','deepseek-spend.json')) for name in names)

with tempfile.TemporaryDirectory(prefix='quota-package-test-') as temp:
    root = Path(temp)
    env = dict(os.environ, AI_QUOTA_WIDGET_DATA_DIR=str(root/'state'))
    env.pop('PYTHONPATH',None)
    def run(args, expected=(0,)):
        p = subprocess.run([str(x) for x in args],cwd=root,env=env,capture_output=True,timeout=300,
                           creationflags=0x08000000 if os.name == 'nt' else 0)
        assert p.returncode in expected, (args[1:3],p.returncode,p.stderr.decode('utf-8','replace')[-600:])
        return p.stdout.decode('utf-8','replace')
    with tempfile.TemporaryDirectory(prefix='quota-entry-test-') as entry:
        run([sys.executable,'-m','venv',entry])
        py = Path(entry)/'Scripts/python.exe'
        exe = Path(entry)/'Scripts/quota_monitor.exe'
        run([py,'-m','pip','install','--disable-pip-version-check','--no-deps',wheel])
        assert APP_VERSION in run([exe,'--version'])
        assert '--doctor' in run([exe,'--help'])
        run([exe,'--doctor'],(0,1,2))
        run([exe,'--json'],(1,2))
        dest = root/'中文 install with spaces'
        try:
            run([exe,'--install','--dest',dest,'--no-autostart'])
        except AssertionError:
            # CI-only fixture diagnostics, no credentials or network requests.
            installed_python=dest/('.venv-'+APP_VERSION)/'Scripts/python.exe'
            if installed_python.exists():
                for module in ('tkinter','PIL','pystray','compression.zstd' if sys.version_info >= (3,14) else 'backports.zstd'):
                    p=subprocess.run([str(installed_python),'-c',f'import {module}'],capture_output=True,env=env)
                    print('fixture import',module,'exit',p.returncode,flush=True)
            raise
        assert json.loads((dest/'config.json').read_text(encoding='utf-8'))['theme'] == 'glass'
        sentinel = '{"kimi_plan_name":"TEST_ONLY","theme":"steam","show_kimi":false,"show_codex":false}'
        (dest/'config.json').write_text(sentinel,encoding='utf-8')
        run([exe,'--install','--dest',dest,'--no-autostart'])
        assert (dest/'config.json').read_text(encoding='utf-8') == sentinel
        launch = (dest/'start.bat').read_text(encoding='utf-8')
        assert entry not in launch, 'launcher binds temporary tool environment'
    # The ephemeral entry is now gone: only permanent installed files may run.
    installed = dest/('.venv-'+APP_VERSION)/'Scripts/python.exe'
    assert APP_VERSION in run([installed,dest/'quota_monitor.py','--version'])
    run([installed,dest/'quota_monitor.py','--launch-check'])
    print('PASS: wheel assets; isolated no-dependency CLI; persistent GUI dependency install; Chinese/spaced path; upgrade keeps config; entry removal does not break launch environment')
