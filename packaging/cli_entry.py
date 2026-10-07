"""Separate headless import graph: no GUI, Pillow or tray in worker PYZ."""
import sys
from pathlib import Path
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.argv[1:2] == ['--network-download']:
    from quota_update import download_worker
    download_worker()
elif sys.argv[1:2] == ['--apply-update']:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply-update', required=True)
    parser.add_argument('--parent-pid', required=True, type=int)
    args = parser.parse_args()
    from quota_update import apply_update
    raise SystemExit(apply_update(args.apply_update, args.parent_pid))
elif sys.argv[1:2] == ['--query'] and len(sys.argv) == 3:
    import quota_monitor
    quota_monitor.query_worker(sys.argv[2])
else:
    from quota_cli import main
    raise SystemExit(main())
