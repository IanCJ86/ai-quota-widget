"""Bounded local usage aggregation; never persist transcript text or credentials."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import os
import time

from monitor_runtime import atomic_json

class UsageSchemaError(ValueError):
    pass

class UsageReadError(ValueError):
    pass

class UsageBudgetError(ValueError):
    pass


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


def _codec():
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    return zstd


def _hash_to(stream, begin, end, deadline, digest=None):
    """Validate skipped compressed bytes, not just sampled head/tail blocks."""
    digest = digest or hashlib.sha256()
    stream.seek(begin)
    remaining = end - begin
    while remaining:
        if time.monotonic() >= deadline:
            raise UsageBudgetError()
        block = stream.read(min(131072, remaining))
        if not block:
            raise UsageReadError('log shortened during scan')
        digest.update(block)
        remaining -= len(block)
    return digest


def _scan_frames(stream, start, end, deadline, offset=0, count=0, fresh=0):
    """Checkpoint only complete frames AND JSONL boundaries; no text in cache."""
    codec = _codec()
    stream.seek(offset)
    checkpoint = dict(offset=offset, base_total=count, base_fresh=fresh)
    pending = bytearray()
    decoded = 0
    decoder = None
    data = b''

    def consume(block, final=False):
        nonlocal count, fresh, decoded
        decoded += len(block)
        if decoded > 256 << 20:
            raise UsageBudgetError()
        pending.extend(block)
        while True:
            boundary = pending.find(b'\n')
            if boundary < 0:
                if len(pending) > 16 << 20:
                    raise UsageBudgetError()
                if not final or not pending:
                    break
                boundary = len(pending)
            if boundary > 16 << 20:
                raise UsageBudgetError()
            line = bytes(pending[:boundary])
            del pending[:boundary + 1]
            if b'"usage"' not in line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            stamp, body = item.get('time'), item.get('data')
            usage = body.get('usage') if isinstance(body, dict) else None
            if (not isinstance(stamp, (int, float)) or isinstance(stamp, bool)
                    or not start <= stamp < end or not isinstance(usage, dict)):
                continue
            values = [usage.get(k) for k in ('totalTokens', 'inputTokens', 'outputTokens')]
            if any(type(v) is not int or v < 0 for v in values):
                raise UsageSchemaError('unrecognized usage fields')
            count += values[0]
            fresh += values[1] + values[2]

    while True:
        if time.monotonic() >= deadline:
            raise UsageBudgetError()
        if decoder is None or decoder.needs_input:
            if not data:
                data = stream.read(65536)
            if not data:
                if decoder is not None:
                    raise UsageReadError('incomplete compressed frame')
                break
        if decoder is None:
            decoder = codec.ZstdDecompressor(options={codec.DecompressionParameter.window_log_max: 27})
        block = decoder.decompress(data, max_length=65536)
        data = b''
        consume(block)
        if decoder.eof:
            data = decoder.unused_data
            boundary = stream.tell() - len(data)
            if not pending:
                checkpoint = dict(offset=boundary, base_total=count, base_fresh=fresh)
            decoder = None
    consume(b'', final=True)
    return dict(total=count, fresh=fresh, **checkpoint)


def _record_ok(record):
    return (isinstance(record, dict)
            and all(type(record.get(k)) is int and record[k] >= 0
                    for k in ('total', 'fresh', 'offset', 'base_total', 'base_fresh'))
            and isinstance(record.get('signature'), list) and len(record['signature']) == 3
            and all(type(v) is int and v >= 0 for v in record['signature'])
            and record['offset'] <= record['signature'][0]
            and record['base_total'] <= record['total'] and record['base_fresh'] <= record['fresh']
            and isinstance(record.get('prefix'), str) and len(record['prefix']) == 64)


def totals(root, day=None, cache_path=None, budget=12, strict=False):
    """Cache complete per-file/day totals; reread only changed files.

    An incomplete scan returns None, never a plausible but partial total. Limits
    bound memory and CPU; the scheduler independently kills a stuck worker.
    Cache keys are hashes of paths and contain only counts/size/timestamps.
    """
    day = day or date.today()
    if not os.path.isdir(root):
        if strict:
            raise FileNotFoundError('usage directory missing')
        return None
    start = datetime.combine(day, datetime.min.time()).timestamp() * 1000
    end = datetime.combine(day + timedelta(days=1), datetime.min.time()).timestamp() * 1000
    deadline = time.monotonic() + budget
    cached, completed = {}, {}
    try:
        if cache_path:
            with open(cache_path, encoding="utf-8") as stream:
                cache = json.load(stream)
            if cache.get("version") == 3 and cache.get("day") == day.isoformat():
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
                    raise UsageBudgetError()
                if not name.endswith(".jsonl.zstd"):
                    continue
                files_seen += 1
                if files_seen > 10000:
                    raise UsageBudgetError()
                path = os.path.join(base, name)
                if os.path.islink(path):
                    continue
                stat = os.stat(path)
                if stat.st_mtime * 1000 < start:
                    continue
                identity = hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()
                signature = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
                record = cached.get(identity, {})
                valid = _record_ok(record) and record.get("signature") == signature
                if not valid:
                    inode = [stat.st_dev, stat.st_ino]
                    with open(path, 'rb') as stream:
                        offset = count = new = 0
                        digest = hashlib.sha256()
                        if (_record_ok(record) and record.get('inode') == inode
                                and stat.st_size >= record['signature'][0]):
                            candidate = _hash_to(stream, 0, record['offset'], deadline)
                            if candidate.hexdigest() == record['prefix']:
                                offset, count, new = record['offset'], record['base_total'], record['base_fresh']
                                digest = candidate
                        result = _scan_frames(stream, start, end, deadline, offset, count, new)
                        digest = _hash_to(stream, offset, result['offset'], deadline, digest)
                    after = os.stat(path)
                    if signature != [after.st_size, after.st_mtime_ns, after.st_ctime_ns] or inode != [after.st_dev, after.st_ino]:
                        raise ValueError("log changed during scan")
                    record = dict(signature=signature, inode=inode, prefix=digest.hexdigest(), **result)
                completed[identity] = record
                total += record["total"]
                fresh += record["fresh"]
        return {"total": total, "fresh": fresh}
    except Exception as exc:
        # Codec-specific truncation/errors must not turn into partial totals.
        if strict:
            if isinstance(exc, (UsageSchemaError, UsageBudgetError, PermissionError, ImportError)):
                raise
            raise UsageReadError('incomplete usage scan') from None
        return None
    finally:
        if cache_path:
            try:
                atomic_json(cache_path, {"version": 3, "day": day.isoformat(),
                                         "files": completed})
            except OSError:
                pass
