"""Clock-only tariff display and persisted, account-scoped voucher observations."""
from collections import Counter
from datetime import timedelta, timezone
import hashlib
import math
from quota_state import finite

BEIJING = timezone(timedelta(hours=8))


def tariff_status(when, holidays):
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(BEIJING)

    def peak(at):
        minutes = at.hour * 60 + at.minute
        if at.weekday() >= 5 or not (540 <= minutes < 720 or 840 <= minutes < 1080):
            return False
        calendar = holidays.get(at.year)
        return None if calendar is None else at.date() not in calendar

    current = peak(local)
    if current is None:
        return '', None
    name = '梁文锋' if current else '梁文谷'
    # Never guess next year's unpublished holiday policy. Bound all lookahead.
    for day in range(32):
        base = (local + timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        for hour in (9, 12, 14, 18):
            edge = base.replace(hour=hour)
            if edge <= local:
                continue
            state = peak(edge)
            if state is None:
                return name + ' ·待日历', current
            if state != current:
                minutes = max(1, math.ceil((edge - local).total_seconds() / 60))
                return f'{name} 剩{minutes // 60:02d}:{minutes % 60:02d}', current
    return name + ' ·待日历', current


def voucher_fingerprints(credits):
    """Never store raw voucher identifiers. Expiry multiset is the fallback."""
    output = []
    for item in credits or []:
        if not isinstance(item, dict) or item.get('status', 'available') != 'available':
            continue
        identifier = item.get('id') or item.get('creditId')
        expiry = item.get('expiresAt')
        if identifier is not None:
            output.append(hashlib.sha256(('id:' + str(identifier)).encode()).hexdigest())
        elif finite(expiry):
            output.append(hashlib.sha256(('expiry:' + str(float(expiry))).encode()).hexdigest())
    return output


def observe_vouchers(previous, data, now):
    """First observation/account change is baseline; refresh never extends red."""
    count = data.get('cr_credit_count')
    if type(count) is not int or count < 0 or not finite(now):
        return previous if isinstance(previous, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    old_tokens = previous.get('tokens') or []
    if not isinstance(old_tokens, list) or len(old_tokens) > 10000 or any(not isinstance(v, str) for v in old_tokens):
        previous, old_tokens = {}, []
    scope = data.get('cr_credit_scope')
    baseline = previous.get('scope') != scope or type(previous.get('count')) is not int
    tokens = data.get('cr_credit_tokens') or []
    complete = len(tokens) == count
    new = not baseline and (count > previous['count'] or
        (complete and previous.get('complete') and bool(Counter(tokens) - Counter(old_tokens))))
    until = previous.get('new_until', 0) if not baseline else 0
    if not finite(until) or until > now + 86400:
        until = 0
    if new:
        until = now + 86400
    return dict(scope=scope, count=count, tokens=tokens, complete=complete, new_until=until)


def voucher_colors(observation, now, expiry):
    until = observation.get('new_until', 0) if isinstance(observation, dict) else 0
    new = finite(until) and now < until <= now + 86400
    expiring = finite(expiry) and 0 < expiry - now <= 86400
    return new, expiring
