"""Small, source-aware HTTPS transport. No system edits or credential discovery."""
import copy
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

GROUPS = ('accounts', 'radar', 'updates')
MODES = ('system', 'direct', 'proxy')


class NetworkError(OSError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # never expose URLs, headers or raw exception text


def proxy_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('InvalidProxy')
    try:
        p = urllib.parse.urlsplit(value.strip())
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
                or p.path not in ('', '/') or p.query or p.fragment or not p.port
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError('InvalidProxy')
    except ValueError:
        raise ValueError('InvalidProxy') from None
    return value.strip().rstrip('/')


def settings(config):
    raw = config.get('network', {})
    if not isinstance(raw, dict):
        raise ValueError('InvalidNetworkSettings')
    result = {}
    for group in GROUPS:
        item = raw.get(group, {})
        if not isinstance(item, dict) or item.get('mode', 'system') not in MODES:
            raise ValueError('InvalidNetworkSettings')
        mode = item.get('mode', 'system')
        url = proxy_url(item.get('proxy', '')) if mode == 'proxy' else ''
        fallback = item.get('direct_fallback', False)
        if not isinstance(fallback, bool) or (fallback and group == 'accounts'):
            raise ValueError('InvalidNetworkSettings')
        result[group] = dict(mode=mode, proxy=url, direct_fallback=fallback)
    return result


def _pac_configured():
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            return bool(winreg.QueryValueEx(key, 'AutoConfigURL')[0])
    except OSError:
        return False


def proxies_for(item):
    if item['mode'] == 'direct':
        return {}
    if item['mode'] == 'proxy':
        return {'https': item['proxy'], 'http': item['proxy']}
    detected = urllib.request.getproxies()
    if _pac_configured() and not detected.get('https'):
        raise NetworkError('PACUnsupported')
    for scheme in ('http', 'https'):
        value = detected.get(scheme)
        if value:
            # urllib cannot speak SOCKS. Never silently try it as HTTP.
            parsed = urllib.parse.urlsplit(value if '://' in value else 'http://' + value)
            if parsed.scheme not in ('http', 'https'):
                raise NetworkError('ProxyUnsupported')
    if detected.get('all') and not detected.get('https'):
        raise NetworkError('ProxyUnsupported')
    return detected


def _origin(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise NetworkError('UnsafeRedirect')
    return (p.hostname.lower(), p.port or 443)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(req.full_url) != _origin(newurl):
            raise NetworkError('UnsafeRedirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def error_code(exc):
    if isinstance(exc, NetworkError):
        return exc.code
    if isinstance(exc, urllib.error.HTTPError):
        return f'HTTP{exc.code}'
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLError):
        return 'TLSError'
    if isinstance(reason, socket.gaierror):
        return 'DNSError'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'Timeout'
    if isinstance(reason, (ConnectionError, OSError)):
        return 'ConnectionError'
    return type(exc).__name__


def retry_after(headers, now=None):
    value = headers.get('Retry-After', '') if headers else ''
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
        except (ValueError, TypeError, OverflowError):
            return 0
    import math
    return min(86400, max(0, delay)) if math.isfinite(delay) else 0


def open_request(req, config, group, timeout=10, redirect=None, direct=False):
    _origin(req.full_url)
    item = settings(config)[group]
    proxies = {} if direct else proxies_for(item)
    # Custom ProxyHandler must not inherit no_proxy bypass for an explicit proxy.
    handler = urllib.request.ProxyHandler(proxies)
    if item['mode'] == 'proxy' and not direct:
        class ForcedProxy(urllib.request.ProxyHandler):
            def proxy_open(self, request, proxy, scheme):
                p = urllib.parse.urlsplit(proxy)
                request.set_proxy(p.netloc, p.scheme)
                return None
        handler = ForcedProxy(proxies)
    opener = urllib.request.build_opener(handler, redirect or SameOriginRedirect())
    return opener.open(req, timeout=timeout)


def stream(req, config, group, *, limit, budget, consume=None, output=None,
           cancel=None, progress=None, redirect=None):
    """read1 prevents an endless trickle filling read(n); caller owns hard process deadline."""
    deadline = time.monotonic() + budget
    item = settings(config)[group]
    attempts = (False, True) if group != 'accounts' and item['direct_fallback'] and item['mode'] == 'system' else (False,)
    for direct in attempts:
        if cancel and cancel.is_set():
            raise NetworkError('Cancelled')
        if time.monotonic() >= deadline:
            raise NetworkError('Timeout')
        size = 0
        result = bytearray()
        try:
            with open_request(copy.copy(req), config, group,
                    timeout=min(8, max(.1, deadline-time.monotonic())), redirect=redirect, direct=direct) as response:
                while True:
                    if cancel and cancel.is_set():
                        raise NetworkError('Cancelled')
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise NetworkError('Timeout')
                    # Bounded blocking reads, including TLS sockets.
                    sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if sock:
                        sock.settimeout(min(3, remaining))
                    block = response.read1(16384) if hasattr(response, 'read1') else response.read(16384)
                    if time.monotonic() >= deadline:
                        raise NetworkError('Timeout')
                    if not block:
                        return bytes(result)
                    size += len(block)
                    if size > limit:
                        raise NetworkError('ResponseTooLarge')
                    if output:
                        output.write(block)
                    else:
                        result.extend(block)
                    if progress:
                        progress(size)
                    if consume and consume(block):
                        return bytes(result)
        except (urllib.error.URLError, OSError) as exc:
            code = error_code(exc)
            # No policy bypass, HTTP retry, TLS downgrade, or mixing partial downloads.
            if direct or len(attempts) == 1 or size or code not in ('Timeout', 'ConnectionError', 'DNSError') or deadline-time.monotonic() < 1:
                raise
    raise NetworkError('ConnectionError')
