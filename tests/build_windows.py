"""Build a standalone x64 app in an isolated build venv, without local config.

Call with a committed-tree export as cwd, using the pinned build interpreter.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app_version import APP_VERSION


def build(output):
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
                    '--distpath',str(output/'frozen'),'--workpath',str(output/'work'),
                    str(root/'packaging/windows.spec')],check=True,cwd=root)
    app = output/'frozen/AIQuotaWidget'
    shutil.copy2(root/'LICENSE', app/'LICENSE')
    # Windows PowerShell 5 needs a BOM for Chinese script literals.
    for name in ('setup.ps1','install.cmd'):
        text = (root/'packaging'/name).read_text(encoding='utf-8-sig')
        (app/name).write_text(text,encoding='utf-8-sig' if name.endswith('.ps1') else 'utf-8')
    entries = {p.relative_to(app).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(app.rglob('*')) if p.is_file()}
    (app/'bundle-manifest.json').write_text(json.dumps(dict(version=APP_VERSION,files=entries),indent=2),encoding='utf-8')
    archive = output/f'ai-quota-widget-v{APP_VERSION}-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(app.rglob('*')):
            if p.is_file(): z.write(p, p.relative_to(app).as_posix())
    print(json.dumps({'file':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size}))


if __name__ == '__main__':
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    build(output)
