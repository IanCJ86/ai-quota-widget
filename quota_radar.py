"""Public reset signals only; cadence percentages are never actionable signals."""
from datetime import datetime
import hashlib
import math
import time

PHASES = ('announced', 'hint', 'expired', 'quiet', 'completed')


def _stamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if value.tzinfo is None:
                return None
            value = value.timestamp()
        return value if type(value) in (int, float) and math.isfinite(value) and 0 < value < 253402300800 else None
    except (ValueError, OverflowError, OSError):
        return None


def _score(value):
    return round(value) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _deadline(*items):
    limits = []
    for item in items:
        for key in ('expires_at', 'end_at', 'ends_at', 'end', 'deadline'):
            if item.get(key) is not None:
                stamp = _stamp(item[key])
                if stamp is None:
                    raise ValueError('invalid radar deadline')
                limits.append(stamp)
    return min(limits) if limits else None


def parse_forecast(payload, now=None):
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or payload.get('mode') not in ('model', 'announced', 'signal', 'quiet', 'confirmed', 'completed'):
        raise ValueError('invalid radar response')
    probabilities = _mapping(payload.get('probabilities'))
    official = _mapping(payload.get('official_signal'))
    alert = _mapping(payload.get('latest_alert'))
    tease = _mapping(payload.get('tease_signal'))
    reset_at = _stamp(payload.get('last_reset_at'))
    if reset_at is not None and reset_at > now + 300:
        raise ValueError('future radar reset')
    phase, signal_at, expires, review, identity = 'quiet', None, None, None, None
    scores = {24: None, 48: None}
    banked = official.get('kind') in ('banked', 'banked_reset', 'grant') or official.get('signal_type') in ('banked', 'banked_reset', 'grant')
    if payload.get('mode') == 'announced' and not banked and (official or alert.get('kind') == 'watch'):
        phase = 'announced'
        related = not official.get('tweet_id') or alert.get('id') == official.get('tweet_id')
        signal_at = _stamp(official.get('at') or (alert.get('source_at') if related else None))
        identity = official.get('tweet_id') or alert.get('id')
        score = next((s for s in (_score(probabilities.get('signal_percent')),
                                  _score(_mapping(payload.get('signal_score')).get('value')),
                                  _score(_mapping(official.get('score')).get('value')),
                                  _score(probabilities.get('commitment_floor_percent'))) if s is not None), None)
        scores = {24: score, 48: score}
        expires = _deadline(official, _mapping(official.get('window')),
                            alert if related else {}, _mapping(alert.get('window')) if related else {})
        # Cancellation only applies to this signal, not an older unrelated alert.
        if related and alert.get('state') in ('expired', 'cancelled', 'canceled', 'withdrawn', 'retracted'):
            phase = 'expired'
    elif tease:
        phase = 'hint'
        post = _mapping(tease.get('post'))
        signal_at, identity = _stamp(post.get('at')), post.get('id')
        expires = _deadline(tease, _mapping(tease.get('window')))
        scores = {hours: _score(tease.get(f'floor_{hours}h')) for hours in (24, 48)}
    elif alert.get('kind') == 'watch' and alert.get('state') in ('expired', 'cancelled', 'canceled', 'withdrawn', 'retracted'):
        phase = 'expired'
        signal_at = _stamp(alert.get('source_at'))
    if phase in ('announced', 'hint'):
        if signal_at is None or signal_at > now + 300:
            raise ValueError('invalid radar signal time')
        # An unspecified deadline is not permission to reuse a promise forever.
        review = signal_at + 48 * 3600 if expires is None else None
        if expires is not None and now >= expires:
            phase = 'expired'
    if reset_at and ((signal_at is not None and reset_at >= signal_at) or phase == 'quiet' and now-reset_at <= 86400):
        phase, scores = 'completed', {24: None, 48: None}
    if phase not in ('announced', 'hint'):
        scores = {24: None, 48: None}
    key = hashlib.sha256(f'{phase}:{identity}:{signal_at}'.encode()).hexdigest()
    return dict(cr_main_phase=phase, cr_main_signal_at=signal_at,
                cr_main_expires_at=expires, cr_main_review_at=review,
                cr_main_reset_at=reset_at, cr_main_signal_key=key,
                cr_main24=scores[24], cr_main48=scores[48],
                cr_main_updated=_stamp(payload.get('updated_at')), cr_main_at=now,
                cr_main24_at=now, cr_main48_at=now)


def radar_view(data, window=24, now=None):
    """Re-evaluate expiry on the clock, even if the network has stopped."""
    now = time.time() if now is None else now
    phase = data.get('cr_main_phase')
    if phase not in PHASES:
        return None  # Legacy data remains unverified; new adapters always tag it.
    if phase in ('announced', 'hint'):
        if _stamp(data.get('cr_main_expires_at')) and now >= data['cr_main_expires_at']:
            phase = 'expired'
        elif _stamp(data.get('cr_main_review_at')) and now >= data['cr_main_review_at']:
            phase = 'review'
    if phase == 'completed' and (not _stamp(data.get('cr_main_reset_at')) or now-data['cr_main_reset_at'] > 86400):
        phase = 'quiet'
    note = {'announced': '已预告', 'hint': '重置线索', 'expired': '待确认',
            'quiet': '暂无预告', 'completed': '已重置', 'review': '预告待核验'}[phase]
    score = data.get(f'cr_main{window}') if phase in ('announced', 'hint') else None
    return dict(phase=phase, score=score, note=note)
