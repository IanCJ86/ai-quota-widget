"""Bounded local usage aggregation; never persist transcript text or credentials."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import os
import time

from monitor_runtime import atomic_json


@contextmanager
def open_log(path):
    """Both codecs stream across concatenated frames (Harness appends frames)."""
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    # Standard-library/backport both detect truncated frames, unlike a permissive
    # stream_reader that can mistake an incomplete trailing frame for empty usage.
    with zstd.open(path, "rb", options={zstd.DecompressionParameter.window_log_max: 27}) as stream:
        yield stream


def totals(root, day=None, cache_path=None, budget=12):
    """Cache complete per-file/day totals; reread only changed files.

    An incomplete scan returns None, never a plausible but partial total. Limits
    bound memory and CPU; the scheduler independently kills a stuck worker.
    Cache keys are hashes of paths and contain only counts/size/timestamps.
    """
    day = day or date.today()
    if not os.path.isdir(root):
        return None
    start = datetime.combine(day, datetime.min.time()).timestamp() * 1000
    end = datetime.combine(day + timedelta(days=1), datetime.min.time()).timestamp() * 1000
    deadline = time.monotonic() + budget
    cached, completed = {}, {}
    try:
        if cache_path:
            with open(cache_path, encoding="utf-8") as stream:
                cache = json.load(stream)
            if cache.get("version") == 1 and cache.get("day") == day.isoformat():
                cached = cache.get("files", {})
                if not isinstance(cached, dict):
                    cached = {}
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    total = fresh = 0
    files_seen = 0
    try:
        def walk_error(error):
            raise error
        for base, dirs, files in os.walk(root, onerror=walk_error):
            # Do not follow junctions/symlinks out of the selected log directory.
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
            for name in files:
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                if not name.endswith(".jsonl.zstd"):
                    continue
                files_seen += 1
                if files_seen > 10000:
                    raise ValueError("too many logs")
                path = os.path.join(base, name)
                if os.path.islink(path):
                    continue
                stat = os.stat(path)
                if stat.st_mtime * 1000 < start:
                    continue
                identity = hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()
                signature = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
                record = cached.get(identity, {})
                valid = (isinstance(record, dict) and record.get("signature") == signature
                         and all(type(record.get(k)) is int and record[k] >= 0
                                 for k in ("total", "fresh")))
                if not valid:
                    count = new = decoded = 0
                    with open_log(path) as stream:
                        while True:
                            if time.monotonic() >= deadline:
                                raise TimeoutError()
                            line = stream.readline((16 << 20) + 1)
                            if not line:
                                break
                            decoded += len(line)
                            if len(line) > 16 << 20 or decoded > 256 << 20:
                                raise ValueError("log scan limit")
                            if b'"usage"' not in line:
                                continue
                            item = json.loads(line)
                            if not isinstance(item, dict):
                                continue
                            stamp, data = item.get("time"), item.get("data")
                            usage = data.get("usage") if isinstance(data, dict) else None
                            if (not isinstance(stamp, (int, float)) or isinstance(stamp, bool)
                                    or not start <= stamp < end or not isinstance(usage, dict)):
                                continue
                            values = [usage.get(k, 0) for k in
                                      ("totalTokens", "inputTokens", "outputTokens")]
                            if any(type(v) is not int or v < 0 for v in values):
                                raise ValueError("invalid usage")
                            count += values[0]
                            new += values[1] + values[2]
                    after = os.stat(path)
                    if signature != [after.st_size, after.st_mtime_ns, after.st_ctime_ns]:
                        raise ValueError("log changed during scan")
                    record = {"signature": signature, "total": count, "fresh": new}
                completed[identity] = record
                total += record["total"]
                fresh += record["fresh"]
        return {"total": total, "fresh": fresh}
    except (OSError, ValueError, ImportError, EOFError, TypeError):
        return None
    except Exception:
        # Codec-specific truncation/errors must not turn into partial totals.
        return None
    finally:
        if cache_path:
            try:
                atomic_json(cache_path, {"version": 1, "day": day.isoformat(),
                                         "files": completed})
            except OSError:
                pass
