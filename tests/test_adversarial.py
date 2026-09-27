"""Public-release adversarial regressions; fake profiles, no network or keys."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
import test_monitor as fixtures
monitor = fixtures.monitor
from monitor_runtime import validate_result, Scheduler
import quota_cli as cli
import harness_stats


class Contracts(unittest.TestCase):
    def test_cache_rejects_all_invalid_amount_variants(self):
        for value in ('bad', True, float('nan'), float('inf'), 10**1000, -1):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                validate_result('deepseek', {'ds_balance':10,'ds_spend':value})

    def test_cross_source_fields_are_removed(self):
        self.assertEqual(validate_result('codex', {'cw_pct':0,'ds_balance':999}), {'cw_pct':0})

    def test_invalid_metadata_is_rejected(self):
        for data in ({'ds_balance':1,'ds_currency':{}}, {'ds_balance':1,'ds_spend_day':'yesterday'},
                     {'cw_pct':80,'cr_credit_expiries':[{}]}, {'cw_pct':80,'cw_reset':'later'}):
            with self.assertRaises(ValueError):
                validate_result('codex' if 'cw_pct' in data else 'deepseek', data)

    def test_iso_reset_survives_cli_and_expires(self):
        stamp = datetime.fromtimestamp(time.time()-30, timezone.utc).isoformat()
        data = cli.safe_data('kimi', {'kw_pct':50,'kw_reset':stamp})
        self.assertTrue(cli.window_expired(data, 'kw'))

    def test_all_three_providers_reschedule_at_reset(self):
        for name, prefix in (('kimi','k'),('glm','g'),('codex','c')):
            results=[]
            scheduler=Scheduler('', lambda *args:results.append(args), monotonic=lambda:100, wall=lambda:1000)
            scheduler.configure([name])
            state=scheduler.states[name]
            scheduler._finish(name,state,{'ok':True,'data':{prefix+'w_pct':30,prefix+'w_reset':1020}},100)
            self.assertEqual(state['due'],121)
            scheduler.close()

    def test_spend_disk_failure_is_not_zero(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(monitor,'DEEPSEEK_SPEND_FILE',str(Path(folder)/'spend.json')):
            monitor.deepseek_spend(100)
            with patch.object(monitor,'atomic_json',side_effect=PermissionError()):
                with self.assertRaises(PermissionError): monitor.deepseek_spend(200)

    def test_balance_survives_spend_failure(self):
        response = io.StringIO(json.dumps({'is_available':True,'balance_infos':[{'currency':'CNY','total_balance':'12'}]}))
        with patch.object(monitor,'deepseek_api_key',return_value='fake'), \
             patch.object(monitor.urllib.request,'urlopen',return_value=response), \
             patch.object(monitor,'deepseek_spend',side_effect=PermissionError()):
            result=monitor.fetch_deepseek()
        self.assertEqual(result['ds_balance'],12)
        self.assertIsNone(result['ds_spend'])
        self.assertEqual(result['ds_spend_error'],'SpendWriteFailed')

    def test_unknown_usage_is_not_zero(self):
        line=json.dumps({'time':time.time()*1000,'data':{'usage':{'renamedTotal':123}}}).encode()+b'\n'
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'fake.jsonl.zstd').write_bytes(b'fake')
            with patch.object(harness_stats,'open_log',return_value=io.BytesIO(line)):
                with self.assertRaises(harness_stats.UsageSchemaError):
                    harness_stats.totals(folder,strict=True)

    def test_empty_logs_are_real_zero_and_budget_error_is_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(harness_stats.totals(folder,strict=True),{'total':0,'fresh':0})
            (Path(folder)/'fake.jsonl.zstd').write_bytes(b'fake')
            with self.assertRaises(harness_stats.UsageBudgetError):
                harness_stats.totals(folder,budget=-1,strict=True)

    def test_defaults_include_log_settings(self):
        self.assertEqual(monitor.DEFAULT_CONFIG['deepseek_token_metric'],'total')
        self.assertEqual(monitor.DEFAULT_CONFIG['harness_sessions_dir'],'')


class UIAdversarial(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.UITests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.app=self.fixture.app

    def test_malformed_cache_does_not_break_real_startup(self):
        stamp=time.time()
        Path(monitor.CACHE_FILE).write_text(json.dumps({'sources':{
            'deepseek':{'identity':monitor.source_identity('deepseek'),'success_at':stamp,'data':{'ds_balance':10,'ds_spend':'broken'}},
            'codex':{'success_at':stamp,'data':{'cw_pct':72,'ds_balance':'foreign'}},
            'kimi':42}}),encoding='utf-8')
        second=monitor.App()
        try:
            self.assertNotIn('ds_balance',second.data)
            self.assertEqual(second.data['cw_pct'],72)
            second._render()
        finally: second._quit()

    def test_key_change_closes_old_worker_and_invalidates_cache(self):
        app=self.app
        app._on_result('deepseek',{'ok':True,'data':{'ds_balance':10,'ds_currency':'CNY'}},{})
        worker=Mock()
        app.scheduler.states['deepseek']['worker']=worker
        with patch.object(monitor,'deepseek_api_key',return_value='new-fake-key'):
            app._sync_credentials()
            worker.close.assert_called_once()
            self.assertNotIn('ds_balance',app.data)
            self.assertNotIn('deepseek',app._verified)
            self.assertEqual(app.scheduler.states['deepseek']['due'],0)
            app._load_cache()
            self.assertNotIn('ds_balance',app.data)

    def test_harness_without_api_key_is_visible(self):
        folder=Path(self.fixture.tmp.name)/'sessions'
        folder.mkdir()
        with patch.object(monitor,'deepseek_api_key',return_value=''):
            self.assertIn('tokens',self.app._enabled_sources())
            self.assertNotIn('deepseek',self.app._enabled_sources())
            self.app._on_result('tokens',{'ok':True,'data':{'ds_tokens_total':1234,'ds_tokens_fresh':1234,'ds_tokens_day':date.today().isoformat()}},{})
            self.assertIn('tok',self.app.rows['ds_spend'][1].cget('text'))
            self.assertEqual(self.app.rows['ds_spend'][0].cget('text'),'--')

    def test_late_result_after_external_key_change_is_discarded(self):
        with patch.object(monitor,'deepseek_api_key',return_value='different-fake'):
            self.app._on_result('deepseek',{'ok':True,'data':{'ds_balance':999}}, {})
            self.assertNotIn('ds_balance',self.app.data)
            self.assertNotIn('deepseek',self.app._verified)

    def test_cache_keeps_queried_identity_not_external_new_key(self):
        original=self.app._source_identities['deepseek']
        self.app._on_result('deepseek',{'ok':True,'data':{'ds_balance':10}}, {})
        with patch.object(monitor,'deepseek_api_key',return_value='different-fake'):
            self.app._save_cache()
        cached=json.loads(Path(monitor.CACHE_FILE).read_text(encoding='utf-8'))
        self.assertEqual(cached['sources']['deepseek']['identity'],original)

    def test_kimi_glm_only_expired_window_is_grey(self):
        self.app.show_glm.set(True)
        with patch.object(monitor,'glm_api_key',return_value='fake'):
            self.app._apply_visibility()
            for source,prefix in (('kimi','k'),('glm','g')):
                self.app._on_result(source,{'ok':True,'data':{prefix+'5_pct':10,prefix+'5_reset':time.time()-10,
                    prefix+'w_pct':80,prefix+'w_reset':time.time()+1000}},{})
                self.assertEqual(self.app.rows[prefix+'5'][1].cget('text'),'窗口已过期')
                self.assertNotEqual(self.app.rows[prefix+'w'][1].cget('text'),'窗口已过期')

    def test_secret_empty_keeps_dialog_then_cancel(self):
        dialog=self.app.settings.dialogs
        def submit():
            win,value,ok=dialog._secret_prompt
            value.set('  ')
            ok()
            self.assertTrue(win.winfo_exists())
            win.destroy()
        self.app.root.after(30,submit)
        self.assertIsNone(dialog._ask_secret('测试','测试'))

    def test_log_directory_change_invalidates_tokens(self):
        app=self.app
        app._on_result('tokens',{'ok':True,'data':{'ds_tokens_total':99,'ds_tokens_day':date.today().isoformat()}},{})
        monitor.CFG['harness_sessions_dir']=str(Path(self.fixture.tmp.name)/'新 日志')
        app._sync_credentials()
        self.assertNotIn('ds_tokens_total',app.data)

    def test_no_login_no_account_worker(self):
        with patch.object(monitor.os.path,'isfile',return_value=False):
            names=self.app._enabled_sources()
            self.assertNotIn('kimi',names)
            self.assertNotIn('codex',names)


if __name__=='__main__': unittest.main()
