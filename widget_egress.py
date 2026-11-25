"""Optional public IP lookup using the configured account network route."""
import ipaddress
import json
import re
from urllib.request import Request

from quota_network import stream


LOOKUP_URL = 'https://ipwho.is/?lang=zh-CN&fields=success,ip,country_code,region'


def parse_egress(data):
    if not isinstance(data, dict) or data.get('success') is not True:
        raise ValueError('invalid IP lookup result')
    ip, country, region = (data.get(key) for key in ('ip', 'country_code', 'region'))
    if not isinstance(ip, str) or '%' in ip:
        raise ValueError('invalid IP address')
    address = ipaddress.ip_address(ip)
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise ValueError('expected a public IP address')
    if not isinstance(country, str) or not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('invalid country code')
    if not isinstance(region, str) or not region.isprintable():
        region = ''
    return {'ip': str(address), 'country_code': country,
            'region': ' '.join(region.split())[:48], 'success': True}


def fetch_egress(config):
    request = Request(LOOKUP_URL, headers={'Accept': 'application/json'})
    return parse_egress(json.loads(stream(request, config, 'accounts', limit=4096, budget=6)))
