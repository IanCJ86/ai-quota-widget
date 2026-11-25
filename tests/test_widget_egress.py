import unittest
from unittest.mock import patch

from widget_egress import fetch_egress, parse_egress


class EgressTests(unittest.TestCase):
    def test_uses_account_route_without_authentication(self):
        config = {'network': {'accounts': {'mode': 'direct'}}}
        with patch('widget_egress.stream', return_value=(
                b'{"success":true,"ip":"2001:4860::1","country_code":"US","region":"California"}'
        )) as stream:
            result = fetch_egress(config)
        request, used_config, group = stream.call_args.args
        self.assertEqual(request.host, 'ipwho.is')
        self.assertIs(used_config, config)
        self.assertEqual(group, 'accounts')
        self.assertEqual(request.header_items(), [('Accept', 'application/json')])
        self.assertEqual((result['ip'], result['region']), ('2001:4860::1', 'California'))

    def test_rejects_unusable_addresses_and_country_codes(self):
        base = {'success': True, 'ip': '8.8.8.8', 'country_code': 'US'}
        for invalid in ({'ip': 1}, {'ip': '127.0.0.1'}, {'ip': '224.0.0.1'},
                        {'ip': '2001:4860::1%3'}, {'success': False}, {'country_code': '42'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_egress({**base, **invalid})
        self.assertEqual(parse_egress({**base, 'region': {'name': 'California'}})['region'], '')
