"""Public release gates: no user credentials, state or network required."""
from desktop_test_support import isolate_desktop
isolate_desktop()
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import quota_cli as cli
import quota_install as installer
import quota_state as state
import quota_monitor as monitor
from widget_viewport import clamp_rect
import test_monitor

ROOT = Path(monitor.__file__).parent

class StateTests(unittest.TestCase):
    def test_config_bad_types_are_reported_and_defaulted(self):
        cfg, errors=state.validate_config({'theme':[],'show_codex':'false','window_alpha':float('nan')},monitor.DEFAULT_CONFIG)
        self.assertEqual(cfg['theme'],'dark')
        self.assertIs(cfg['show_codex'],True)
        self.assertEqual(len(errors),3)
    def test_bad_config_top_level(self):
        _, errors=state.validate_config([],monitor.DEFAULT_CONFIG)
        self.assertTrue(errors)
    def test_false_and_zero_remain_valid(self):
        cfg,errors=state.validate_config({'show_codex':False,'deepseek_low_balance':0},monitor.DEFAULT_CONFIG)
        self.assertFalse(errors)
        self.assertIs(cfg['show_codex'],False)
    def test_cache_is_not_claimed_verified(self):
        self.assertEqual(state.source_status({'cw_pct':0},10,False,now=11)['state'],'unverified')
        self.assertFalse(state.source_status({'cw_pct':0},10,True,now=11)['stale'])
    def test_expired_and_bad_timestamp(self):
        self.assertTrue(state.window_expired({'cw_reset':10},'cw',11))
        self.assertFalse(state.window_expired({'cw_reset':True},'cw',11))
    def test_partial_voucher_expiry_is_not_all_expiry(self):
        self.assertEqual(state.credit_status({'cr_credit_count':2,'cr_credit_expiries':[10,30]},20),(1,30,''))
    def test_unknown_voucher_expiry_explicit(self):
        self.assertEqual(state.credit_status({'cr_credit_count':1})[2],'期限未提供')
    def test_all_vouchers_expired(self):
        self.assertEqual(state.credit_status({'cr_credit_count':1,'cr_credit_expiries':[10]},20),(0,None,'已到期'))
    def test_negative_monitor_coordinates(self):
        self.assertEqual(clamp_rect(-1000,50,260,300,(-1920,0,0,1080)),(260,300,-1000,50))
    def test_oversize_window_clamps(self):
        w,h,x,y=clamp_rect(0,0,500,600,(0,0,320,240))
        self.assertTrue(x>=0 and y>=0 and x+w<=320 and y+h<=240)
    def test_account_and_currency_isolation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(monitor,'DEEPSEEK_SPEND_FILE',str(Path(directory)/'spend.json')):
            self.assertEqual(monitor.deepseek_spend(100,scope='fake-account-A:CNY'),0)
            self.assertEqual(monitor.deepseek_spend(99.999,scope='fake-account-A:CNY'),.001)
            self.assertEqual(monitor.deepseek_spend(20,scope='fake-account-B:CNY'),0)
            self.assertEqual(monitor.deepseek_spend(2,scope='fake-account-B:USD'),0)
    def test_retry_after_is_bounded(self):
        from monitor_runtime import Scheduler
        s=Scheduler('unused',lambda *x:None,monotonic=lambda:100,wall=lambda:100)
        s.configure(['codex'])
        record=s.states['codex']; record['attempt']=1
        s._finish('codex',record,dict(ok=False,error='HTTP429',retry_after=5000),100)
        self.assertEqual(record['due'],400)
    def test_error_label_rejects_non_string(self):
        self.assertEqual(state.error_label({'secret':'FAKE'}),'查询失败')
    def test_corrupt_config_is_preserved_until_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'; path.write_text('broken',encoding='utf-8')
            with patch.object(monitor,'CONFIG_FILE',str(path)),patch.object(monitor,'SETTINGS_FILE',str(path.parent/'absent')),patch.object(monitor,'CONFIG_ISSUES',[]),patch.object(monitor,'CONFIG_SAVE_FAILED',False):
                cfg=monitor._load_config()
                self.assertTrue(monitor.CONFIG_ISSUES)
                self.assertEqual(path.read_text(),'broken')
                self.assertTrue(monitor._save_config(cfg))
                backup=list(path.parent.glob('config.json.invalid-*.bak'))
                self.assertEqual(len(backup),1)
                self.assertEqual(backup[0].read_text(),'broken')
                with patch.object(monitor,'atomic_json',side_effect=PermissionError()):
                    self.assertFalse(monitor._save_config(cfg))
                self.assertTrue(monitor.CONFIG_SAVE_FAILED)

class GuiReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_monitor.UITests(); self.fixture.setUp(); self.app=self.fixture.app
    def tearDown(self):
        self.fixture.tearDown()
    def test_voucher_expiry_survives_failed_query(self):
        a=self.app
        a._on_result('codex',{'ok':True,'data':{'cw_pct':50,'cr_credit_count':1,'cr_credit_expiry':time.time()+86400}},{})
        note=a.rows['cr_credit'][1].cget('text')
        a._on_result('codex',{'ok':False,'error':'Timeout'},{})
        self.assertEqual(a.rows['cr_credit'][1].cget('text'),note)
        self.assertIn('旧',a.rows['cr_credit'][0].cget('text'))
    def test_initial_failure_is_not_infinite_loading(self):
        self.app._on_result('kimi',{'ok':False,'error':'HTTP401'},{})
        self.assertIn('失败',self.app.status.cget('text'))
        self.assertEqual(self.app.rows['k5'][1].cget('text'),'需重新认证')
    def test_empty_visibility_is_explicit(self):
        a=self.app
        for name in ('kimi','codex','glm','deepseek','radar'): getattr(a,'show_'+name).set(False)
        a._apply_visibility(); a._render()
        self.assertIn('未显示账户',a.status.cget('text'))
    def test_tiny_and_large_amounts(self):
        a=self.app
        for value, expected in ((0,'¥0.00'),(.3,'¥0.30'),(.001,'<¥0.01'),(12345.67,'¥12,345.67'),(1000000,'¥100.00万')):
            a._set_amount('ds',value,'CNY',whole_width=0)
            self.assertEqual(a.rows['ds'][0].cget('text'),expected)
    def test_small_workarea_has_scroll_and_visible_footer(self):
        a=self.app
        with patch.object(monitor,'work_area',return_value=(0,0,320,240)):
            a._fit()
            # Native Configure events follow geometry(); exercise the real loop
            # before inspecting child positions, not the previous frame.
            a.root.update()
        self.assertLessEqual(a.root.winfo_height(),240)
        self.assertTrue(a.viewport.vertical.winfo_manager())
        self.assertLessEqual(a.close_btn.winfo_rooty()+a.close_btn.winfo_height(),a.root.winfo_rooty()+a.root.winfo_height())
    def test_cache_failure_recovers(self):
        a=self.app
        with patch.object(a,'_save_cache',side_effect=OSError()):
            a._on_result('codex',{'ok':True,'data':{'cw_pct':10}},{})
        self.assertEqual(a._ui_error,'CacheWriteFailed')
        a._on_result('codex',{'ok':True,'data':{'cw_pct':20}},{})
        self.assertIsNone(a._ui_error)
    def test_scrollbars_and_close_button_do_not_start_window_drag(self):
        from types import SimpleNamespace
        a=self.app
        for widget in (a.viewport.vertical,a.viewport.horizontal,a.close_btn):
            a._drag_start(SimpleNamespace(widget=widget,x=2,y=2))
            self.assertIsNone(a._drag)

class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.flags={k:False for k in state.ACCOUNT_SOURCES}
        self.patches=[patch.object(cli,'configured',return_value=self.flags),
            patch.object(monitor,'CACHE_FILE',str(Path(self.temp.name)/'cache.json')),
            patch.object(monitor,'DEBUG_FILE',str(Path(self.temp.name)/'debug.json')),
            patch.object(monitor,'CONFIG_ISSUES',[])]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
    def test_doctor_no_sources_and_no_leaked_values(self):
        with patch.object(installer,'running',return_value=False): report,code=cli.doctor(monitor)
        self.assertEqual(code,2)
        self.assertIn('未检测到',report)
        self.assertNotIn(str(Path.home()),report)
    def test_doctor_healthy(self):
        self.flags['deepseek']=True
        with patch.object(cli,'module_available',return_value=True): report,code=cli.doctor(monitor)
        self.assertEqual(code,0)
        self.assertIn('第三方',report)
    def test_doctor_missing_dependency(self):
        self.flags['codex']=True
        with patch.object(cli,'module_available',return_value=False): _,code=cli.doctor(monitor)
        self.assertEqual(code,1)
    def test_json_cache_zero_and_unverified(self):
        self.flags['codex']=True
        Path(monitor.CACHE_FILE).write_text(json.dumps({'sources':{'codex':{'success_at':time.time(),'data':{'cw_pct':0,'secret':'FAKE-SECRET'}}}}))
        output,code=cli.collect(monitor)
        self.assertEqual(code,1)
        self.assertEqual(output['source'],'cache')
        self.assertEqual(output['sources']['codex']['data']['cw_pct'],0)
        self.assertNotIn('FAKE-SECRET',json.dumps(output))
    def test_fresh_queries_configured_sources_once_no_scheduler(self):
        self.flags['deepseek']=True
        worker=Mock(); worker.poll.return_value=0
        worker.result.return_value={'ok':True,'data':{'ds_balance':0,'ds_spend':0,'ds_currency':'CNY','ds_spend_day':monitor.date.today().isoformat()}}
        factory=Mock(return_value=worker)
        with patch.object(monitor.os.path,'isdir',return_value=False),patch.object(monitor.Scheduler,'tick',side_effect=AssertionError()):
            output,code=cli.collect(monitor,True,factory)
        self.assertEqual(factory.call_count,1); worker.close.assert_called_once()
        self.assertEqual(code,0); self.assertEqual(output['schema'],1)
    def test_fresh_error_never_echoes_arbitrary_message(self):
        self.flags['deepseek']=True
        factory=Mock(side_effect=RuntimeError('FAKE-SECRET'))
        with patch.object(monitor.os.path,'isdir',return_value=False): output,code=cli.collect(monitor,True,factory)
        self.assertEqual(code,2); self.assertNotIn('FAKE-SECRET',json.dumps(output))
    def test_once_disclaimer(self):
        output,_=cli.collect(monitor)
        self.assertIn('均非官方账单',cli.summary(output))
    def test_headless_help_doctor_json_once_version(self):
        for args in (['--help'],['--version'],['--doctor'],['--json'],['--once']):
            code="import runpy,sys; sys.argv=['quota_monitor.py']+"+repr(args)+";\ntry: runpy.run_path('quota_monitor.py',run_name='__main__')\nexcept SystemExit: pass\nassert not any(n in sys.modules for n in ('tkinter','pystray','PIL','widget_themes'))"
            result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,timeout=15,**monitor._NO_WINDOW)
            self.assertEqual(result.returncode,0,result.stderr)

class InstallTests(unittest.TestCase):
    def test_child_output_supports_chinese_on_english_windows(self):
        with patch.dict(os.environ,{'PYTHONIOENCODING':'cp1252','PYTHONUTF8':'0'}):
            result=installer.run([sys.executable,'-c',"print('中文安装目录')"])
        self.assertEqual(result.stdout.decode('utf-8').strip(),'中文安装目录')
    def test_running_app_not_killed_or_overwritten(self):
        with patch.object(installer,'running',return_value=True),patch.object(installer,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'仍在运行'): installer.install('unused')
            run.assert_not_called()
    def test_copy_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(installer,'running',return_value=False),patch.object(installer,'run'):
            dest=Path(directory)/'install'; dest.mkdir()
            (dest/'app_version.py').write_text('original')
            (dest/'config.json').write_text('{"private":"FAKE-KEY"}')
            original=installer.os.replace
            def replace(source,target):
                if str(target).endswith('quota_cli.py'): raise PermissionError('injected')
                return original(source,target)
            with patch.object(installer.os,'replace',side_effect=replace):
                with self.assertRaises(PermissionError): installer.install(dest,skip_deps=True)
            self.assertEqual((dest/'app_version.py').read_text(),'original')
            self.assertEqual((dest/'config.json').read_text(),'{"private":"FAKE-KEY"}')
    def test_missing_source_stops_before_destination_write(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(installer,'running',return_value=False):
            root=Path(directory); (root/'runtime-files.txt').write_text('missing.py\n')
            with patch.object(installer,'source_paths',return_value=(root,root)):
                with self.assertRaises(RuntimeError): installer.install(root/'dest',True)
            self.assertFalse((root/'dest').exists())
