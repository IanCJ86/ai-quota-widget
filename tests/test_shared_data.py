"""No real credentials: migration/lookup tests only use temporary profiles."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quota_paths as paths


class SharedDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name)
        self.target = self.profile / '.ai-quota-widget'
        self.old = self.profile / 'Local/AIQuotaWidget'
        self.old.mkdir(parents=True)
        self.config = {'renew_codex': '10-05', 'codex_plan_name': 'Pro 20x', 'theme': 'glass'}
        (self.old/'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        (self.old/'deepseek-key.dpapi').write_bytes(b'test-encrypted-not-a-key')
        (self.old/'deepseek-spend.json').write_text('{"test": 1}', encoding='utf-8')

    def test_agent_and_desktop_localappdata_variants_share_target(self):
        for local in (self.profile/'AppData/Local', self.profile/'Packages/Agent/LocalCache/Local'):
            target, _ = paths.data_locations('program', {'USERPROFILE': str(self.profile),
                                                       'LOCALAPPDATA': str(local)}, True)
            self.assertEqual(target, self.target)

    def test_override_and_source_install_are_not_migrated(self):
        self.assertEqual(paths.data_locations('source', {'AI_QUOTA_WIDGET_DATA_DIR': 'explicit'}, True),
                         (Path('explicit'), None))
        self.assertEqual(paths.data_locations('source', {}, False), (Path('source'), None))

    def test_copy_keeps_dates_credentials_history_and_originals(self):
        paths.migrate_data(self.target, self.old)
        for name in ('config.json', 'deepseek-key.dpapi', 'deepseek-spend.json'):
            self.assertEqual((self.target/name).read_bytes(), (self.old/name).read_bytes())
        self.assertEqual(json.loads((self.target/'config.json').read_text())['renew_codex'], '10-05')

    def test_existing_shared_config_always_wins_over_stale_agent_copy(self):
        paths.migrate_data(self.target, self.old)
        (self.old/'config.json').write_text('{"renew_codex":"MM-DD"}')
        paths.migrate_data(self.target, self.old)
        self.assertEqual(json.loads((self.target/'config.json').read_text())['renew_codex'], '10-05')

    def test_failure_leaves_no_partial_destination_and_can_retry(self):
        with patch.object(paths.shutil, 'copy2', side_effect=OSError('injected')):
            with self.assertRaises(OSError): paths.migrate_data(self.target, self.old)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.profile.glob('.aiquota-migrate-*')))
        paths.migrate_data(self.target, self.old)
        self.assertTrue((self.target/'config.json').is_file())

    def test_readonly_resolver_does_not_create_shared_directory(self):
        with patch.object(paths, 'data_locations', return_value=(self.target, self.old)):
            self.assertEqual(paths.resolve_data_dir('unused'), str(self.old))
            self.assertFalse(self.target.exists())
            paths.migrate_data(self.target, self.old)
            self.assertEqual(paths.resolve_data_dir('unused'), str(self.target))

    def test_non_directory_destination_is_not_silently_ignored(self):
        self.target.write_text('not a directory')
        with self.assertRaises(OSError): paths.migrate_data(self.target, self.old)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction protection')
    def test_junction_source_is_rejected(self):
        import subprocess
        link = self.profile/'junction'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.old)],
                       check=True, capture_output=True)
        try:
            with self.assertRaises(OSError): paths.migrate_data(self.target, link)
        finally:
            link.rmdir()

