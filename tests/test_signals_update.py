"""Synthetic adversarial tests; never touch accounts or real installations."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quota_signals as signals
import quota_update as updates
import quota_monitor as monitor


class TariffTests(unittest.TestCase):
    def at(self, value):
        return signals.tariff_status(datetime.fromisoformat(value).replace(tzinfo=signals.BEIJING), monitor.DEEPSEEK_HOLIDAYS)

    def test_edges_and_seconds_ceil(self):
        for value, expected in (
                ('2026-10-08T08:59:59', ('梁文谷 剩00:01', False)),
                ('2026-10-08T09:00:00', ('梁文锋 剩03:00', True)),
                ('2026-10-08T11:59:59', ('梁文锋 剩00:01', True)),
                ('2026-10-08T12:00:00', ('梁文谷 剩02:00', False)),
                ('2026-10-08T14:00:00', ('梁文锋 剩04:00', True)),
                ('2026-10-08T18:00:00', ('梁文谷 剩15:00', False))):
            self.assertEqual(self.at(value), expected)

    def test_weekends_and_holidays_are_continuous(self):
        self.assertEqual(self.at('2026-09-30T18:00:00'), ('梁文谷 剩183:00', False))
        self.assertEqual(self.at('2026-10-09T18:00:00'), ('梁文谷 剩63:00', False))

    def test_unknown_year_is_not_invented(self):
        self.assertEqual(self.at('2027-01-04T09:00:00'), ('', None))
        self.assertEqual(self.at('2027-01-04T18:00:00'), ('梁文谷 ·待日历', False))


class VoucherTests(unittest.TestCase):
    def data(self, ids, scope='a'):
        return dict(cr_credit_count=len(ids), cr_credit_tokens=ids, cr_credit_scope=scope)

    def test_first_baseline_restart_and_fixed_24hours(self):
        state = signals.observe_vouchers({}, self.data(['first']), 100)
        self.assertEqual(state['new_until'], 0)
        state = signals.observe_vouchers(state, self.data(['first', 'second']), 200)
        self.assertEqual(state['new_until'], 86600)
        state = json.loads(json.dumps(state))
        state = signals.observe_vouchers(state, self.data(['first', 'second']), 300)
        self.assertEqual(state['new_until'], 86600)
        self.assertEqual(signals.voucher_colors(state, 400, 900), (True, True))
        self.assertEqual(signals.voucher_colors(state, 86600, 900), (False, False))

    def test_same_count_replacement_and_account_switch(self):
        state = signals.observe_vouchers({}, self.data(['old']), 100)
        state = signals.observe_vouchers(state, self.data(['new']), 200)
        self.assertEqual(state['new_until'], 86600)
        self.assertEqual(signals.observe_vouchers(state, self.data(['other'], 'b'), 300)['new_until'], 0)

    def test_unknown_count_does_not_erase_history_or_create_alert(self):
        state = signals.observe_vouchers({}, self.data([]), 100)
        self.assertEqual(signals.observe_vouchers(state, {}, 200), state)
        self.assertEqual(signals.voucher_colors({}, 100, 86500), (False, True))
        self.assertEqual(signals.voucher_colors({}, 100, 86501), (False, False))

    def test_raw_identifiers_never_persist(self):
        result = signals.voucher_fingerprints([dict(id='private-voucher', expiresAt=999),
                    dict(id='used', status='used'), dict(expiresAt=999)])
        self.assertEqual(len(result), 2)
        self.assertNotIn('private', str(result))


class UpdateTests(unittest.TestCase):
    def release(self, tag='v9.0.0'):
        return dict(tag_name=tag, draft=False, prerelease=False, assets=[
            dict(name=name, browser_download_url=updates.ASSETS + tag + '/' + name)
            for name in (f'ai-quota-widget-{tag}-windows-x64.zip', 'SHA256SUMS.txt')])

    def test_only_stable_exact_repository_assets(self):
        self.assertTrue(updates.release_info(self.release(), current='1.0.0'))
        self.assertIsNone(updates.release_info(self.release('v1.0.0'), current='1.0.0'))
        for field in ('draft', 'prerelease'):
            data = self.release(); data[field] = True
            with self.assertRaises(ValueError): updates.release_info(data)
        for tag in ('v9.0.0rc1', 'v9.0.0+build', '../../evil'):
            with self.assertRaises(ValueError): updates.release_info(self.release(tag))
        data = self.release(); data['assets'][0]['browser_download_url'] = 'https://evil.example/app.zip'
        with self.assertRaises(ValueError): updates.release_info(data)

    def test_zip_traversal_and_checksum_stop_before_execution(self):
        for name in ('../escape', '/absolute', 'C:/escape', 'dir\\escape'):
            with tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / 'app.zip'
                with zipfile.ZipFile(archive, 'w') as zipped:
                    entry = zipfile.ZipInfo('placeholder')
                    entry.filename = name  # keep Windows backslash, not ZipInfo's normalization
                    zipped.writestr(entry, 'bad')
                sums = updates.file_hash(archive) + '  app.zip\n'
                with self.assertRaisesRegex(ValueError, 'UnsafeArchivePath'):
                    updates.unpack_verified(archive, sums, 'app.zip', Path(temp) / 'dest')
                self.assertFalse((Path(temp) / 'escape').exists())
                with self.assertRaisesRegex(ValueError, 'Checksum'):
                    updates.unpack_verified(archive, '0'*64 + '  app.zip', 'app.zip', Path(temp) / 'other')

    def test_trim_only_receipted_owned_versions_and_keep_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('v1.0.0', 'v2.0.0', 'v3.0.0', 'v0.0.0', 'personal'):
                folder = root / name; folder.mkdir()
                if name not in ('v0.0.0', 'personal'):
                    (folder / '.install-receipt.json').write_text(json.dumps(dict(product='AIQuotaWidget', version=name[1:])))
            updates.trim_versions(root, {'v2.0.0', 'v3.0.0'})
            self.assertEqual({p.name for p in root.iterdir()}, {'v2.0.0', 'v3.0.0', 'v0.0.0', 'personal'})

    def test_controller_source_never_phones_home(self):
        from unittest.mock import Mock
        app = Mock()
        controller = updates.UpdateController(app)
        with patch.object(updates, 'check_latest', side_effect=AssertionError('network')):
            controller.next_check = 0
            controller.tick()
            controller.request()
        self.assertFalse(controller.busy)

    def test_failed_start_restores_shortcuts_and_restarts_exact_old_app(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory(prefix='aiquota-update-') as temp:
            stage = Path(temp)
            root = stage / 'install'
            old = root / ('v' + updates.APP_VERSION) / 'quota-widget.exe'
            old.parent.mkdir(parents=True)
            old.write_bytes(b'old')
            package = stage / 'package'; package.mkdir()
            for name in ('quota-widget.exe','quota-cli.exe','setup.ps1'):
                (package/name).write_bytes(b'fixture')
            (package/'bundle-manifest.json').write_text(json.dumps(dict(version='9.0.0',
                files={p.name:updates.file_hash(p) for p in package.iterdir()})))
            plan = stage / 'pending.json'
            plan.write_text(json.dumps(dict(old=str(old), data=str(stage/'data'))))
            shortcut = stage / 'example.lnk'; shortcut.write_bytes(b'old-link')
            new = Mock(); new.pid = 999; new.poll.return_value = 1
            restarted = Mock()
            def installed(*args, **kwargs):
                shortcut.write_bytes(b'new-link')
                return Mock(returncode=0)
            with patch.object(updates.sys, 'executable', str(old.with_name('quota-cli.exe'))), \
                    patch.object(updates, 'wait_parent'), patch.object(updates, 'shortcut_paths', return_value=[shortcut]), \
                    patch.object(updates.subprocess, 'run', side_effect=installed), \
                    patch.object(updates.subprocess, 'Popen', side_effect=[new, restarted]) as launch, \
                    patch.object(updates.ctypes.windll.user32, 'MessageBoxW'), \
                    patch.object(updates.shutil, 'rmtree'):
                self.assertEqual(updates.apply_update(plan, 123), 1)
                self.assertEqual(shortcut.read_bytes(), b'old-link')
                self.assertEqual(Path(launch.call_args.args[0][0]).resolve(), old.resolve())
