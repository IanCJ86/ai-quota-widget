"""Synthetic long-session append benchmark; no real chat or user data read."""
from datetime import datetime
import base64
import json
from pathlib import Path
import random
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import harness_stats as stats

with tempfile.TemporaryDirectory(prefix='quota-incremental-bench-') as temp:
    root=Path(temp);log=root/'long.jsonl.zstd';cache=root/'cache.json'
    randomizer=random.Random(5)
    def frame(n,payload=''):
        row=dict(time=datetime.now().timestamp()*1000,data=dict(text=payload,
            usage=dict(totalTokens=n,inputTokens=n,outputTokens=0)))
        return stats._codec().compress((json.dumps(row)+'\n').encode())
    with log.open('wb') as stream:
        for i in range(256):
            stream.write(frame(1,base64.b64encode(randomizer.randbytes(96*1024)).decode()))
    stats.totals(root,cache_path=cache,strict=True)
    with log.open('ab') as stream:stream.write(frame(7))
    start=time.perf_counter();incremental=stats.totals(root,cache_path=cache,strict=True);inc=time.perf_counter()-start
    start=time.perf_counter();full=stats.totals(root,strict=True);cold=time.perf_counter()-start
    assert incremental==full==dict(total=263,fresh=263)
    print(json.dumps(dict(compressed_mib=round(log.stat().st_size/1048576,2),
        incremental_seconds=round(inc,4),full_scan_seconds=round(cold,4),
        speedup=round(cold/inc,2),exactly_equal=True)))
