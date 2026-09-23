"""Offline process-tree fixture. Never contacts services or reads credentials."""
import os
import subprocess
import sys
import time

if sys.stdin.buffer.readline(16) == b"go\n":
    if sys.argv[2] == "tree":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        print(child.pid, flush=True)
        time.sleep(300)
    elif sys.argv[2] == "hang":
        time.sleep(300)
    else:
        print('{"ok":true,"data":{"cw_pct":75}}', flush=True)
