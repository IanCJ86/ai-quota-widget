"""Opt-in public-source smoke, no accounts, GUI or installed data touched.

Run: python tests/frozen_network_smoke.py BUNDLE HTTP_PROXY_URL
The URL is used only in an isolated temporary profile, never printed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quota_network import proxy_url
from quota_state import radar_status
from quota_update import API


def smoke(bundle, proxy):
    proxy = proxy_url(proxy)
    cli = str(bundle / 'quota-cli.exe')
    with tempfile.TemporaryDirectory(prefix='quota-frozen-network-') as tmp:
        root = Path(tmp)
        env = {k:v for k,v in os.environ.items() if k.lower() not in
               ('http_proxy','https_proxy','all_proxy','no_proxy','pythonpath','pythonhome','glm_api_key','deepseek_api_key','zai_api_key')
               and not k.startswith('AI_QUOTA_WIDGET_')}
        env.update(USERPROFILE=tmp, CODEX_HOME=str(root/'codex'), LOCALAPPDATA=str(root/'local'),
                   AI_QUOTA_WIDGET_DATA_DIR=tmp, PATH=os.path.join(os.environ['SystemRoot'],'System32'))
        def run(args, payload, timeout=28):
            before=time.monotonic()
            result=subprocess.run([cli,*args], input=payload,env=env,capture_output=True,
                                  timeout=timeout,creationflags=0x08000000)
            assert result.returncode==0,(result.returncode,result.stderr.decode('utf-8','replace'))
            return json.loads(result.stdout.splitlines()[-1]),round(time.monotonic()-before,2)
        cfg={'network':{'radar':{'mode':'proxy','proxy':proxy}}}
        (root/'config.json').write_text(json.dumps(cfg),encoding='utf-8')
        result, elapsed=run(['--query','main'],b'go\n')
        assert result.get('ok'), result
        assert not radar_status(result['data'],24,True)['stale'],result
        print(json.dumps(dict(explicit_proxy_without_agent_environment=True,radar_seconds=elapsed,
              probabilities=[result['data']['cr_main24'],result['data']['cr_main48']],source_timestamp_preserved=True)))
        cfg['network']['radar']['proxy']='http://127.0.0.1:1'
        (root/'config.json').write_text(json.dumps(cfg),encoding='utf-8')
        result,elapsed=run(['--query','main'],b'go\n')
        assert result.get('ok') is False and 'data' not in result,result
        print(json.dumps(dict(unavailable_proxy_failure=result['error'],seconds=elapsed,no_fake_zero=True)))
        request=dict(url=API,limit=2*1024*1024,budget=20,
                     config={'network':{'updates':{'mode':'proxy','proxy':proxy}}})
        result,elapsed=run(['--network-download'],json.dumps(request).encode()+b'\n')
        assert result.get('ok'),result
        print(json.dumps(dict(frozen_update_helper=True,metadata_seconds=elapsed)))
        assert not (root/'last-good.json').exists()
        assert not (root/'debug.txt').exists()


if __name__=='__main__':
    smoke(Path(sys.argv[1]).resolve(),sys.argv[2])
