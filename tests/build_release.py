"""Build release assets from a committed Git tree, never personal runtime files.

python tests/build_release.py REF OUTPUT_DIRECTORY
Requires uv for an isolated wheel build; performs no Git writes or publishing.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

root=Path(__file__).resolve().parents[1]
ref=sys.argv[1]
output=Path(sys.argv[2]).resolve()
commit=subprocess.check_output(['git','rev-parse',ref+'^{commit}'],cwd=root,text=True).strip()
output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='quota-release-build-') as temporary:
    source=Path(temporary)
    archive=source/'source.zip'
    subprocess.run(['git','archive','--format=zip','--output='+str(archive),commit],cwd=root,check=True)
    with zipfile.ZipFile(archive) as z:
        # Git tree only; forbid accidentally committed runtime/credential files.
        assert not any(n.endswith(('.dpapi','last-good.json','deepseek-spend.json','debug.txt')) for n in z.namelist())
        cfg=json.loads(z.read('config.json'))
        assert not cfg.get('deepseek_api_key') and not cfg.get('glm_api_key')
        z.extractall(source/'tree')
    tree=source/'tree'
    version=subprocess.check_output([sys.executable,str(tree/'quota_monitor.py'),'--version'],text=True).strip()
    assert 'dev' not in version, 'not a formal release version'
    finalzip=output/f'ai-quota-widget-v{version}-windows-source.zip'
    finalzip.write_bytes(archive.read_bytes())
    subprocess.run(['uv','build','--wheel','--out-dir',str(output),str(tree)],check=True)
    wheel=output/f'ai_quota_widget-{version}-py3-none-any.whl'
    assets = [finalzip, wheel]
    if '--windows' in sys.argv:
        subprocess.run([sys.executable,str(tree/'tests/build_windows.py'),str(output)],check=True,cwd=tree)
        assets.append(output/f'ai-quota-widget-v{version}-windows-x64.zip')
        quick=output/'quick-install.ps1'
        quick.write_text((tree/'quick-install.ps1').read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
        assets.append(quick)
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets)
    (output/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    print(json.dumps({'commit':commit,'version':version,'files':[p.name for p in assets]+['SHA256SUMS.txt']}))
