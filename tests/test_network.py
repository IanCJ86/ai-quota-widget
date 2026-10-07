"""Offline adversarial network contracts; only synthetic credentials and responses."""
import io
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
from desktop_test_support import isolate_desktop
isolate_desktop()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quota_network as net
import quota_monitor as monitor
import quota_state as state
import quota_update as updates
from monitor_runtime import Scheduler, validate_result


RINGS = (b'<div data-testid="probability-ring-24h" data-target-value="30"></div>'
         b'<div data-testid="probability-ring-48h" data-target-value="52"></div>')


class RoutingTests(unittest.TestCase):
    def test_defaults_do_not_write_environment_or_scan_ports(self):
        before = dict(os.environ)
        cfg = net.settings({})
        self.assertEqual({v['mode'] for v in cfg.values()}, {'system'})
        self.assertEqual(os.environ, before)

    def test_custom_proxy_validation_and_group_independence(self):
        cfg = {'network': {'radar': {'mode': 'proxy', 'proxy': 'http://127.0.0.1:12345'}}}
        actual = net.settings(cfg)
        self.assertEqual(actual['accounts']['mode'], 'system')
        self.assertEqual(net.proxies_for(actual['radar'])['https'], 'http://127.0.0.1:12345')
        for bad in ('socks5://host:1', 'https://host:1', 'http://user:secret@host:1', 'http://host',
                    'http://host:99999', 'http://host:1/path', 'http://host:1?secret',
                    'http://host:1\n', 'file:///tmp', 'http://host:1#private'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                net.proxy_url(bad)

    def test_invalid_configuration_is_reported_not_silently_selected(self):
        for raw in (None, [], {'radar': {'mode':'socks'}}, {'accounts': {'direct_fallback':True}}):
            cfg, issues = state.validate_config({'network':raw}, monitor.DEFAULT_CONFIG)
            self.assertTrue(issues)
            with self.assertRaises(ValueError):net.settings(cfg)
            with patch.object(net.urllib.request,'build_opener',side_effect=AssertionError('network')):
                with self.assertRaisesRegex(net.NetworkError,'InvalidNetworkSettings'):
                    net.open_request(urllib.request.Request('https://x.invalid'),cfg,'accounts')

    def test_pac_and_socks_are_explicit_not_silent_direct(self):
        with patch.object(net, '_pac_configured', return_value=True), patch.object(net.urllib.request, 'getproxies', return_value={}):
            with self.assertRaisesRegex(net.NetworkError, 'PACUnsupported'):
                net.proxies_for(net.settings({})['radar'])
        with patch.object(net, '_pac_configured', return_value=False), patch.object(net.urllib.request, 'getproxies', return_value={'https':'socks5://host:1'}):
            with self.assertRaisesRegex(net.NetworkError, 'ProxyUnsupported'):
                net.proxies_for(net.settings({})['radar'])
        with patch.object(net, '_pac_configured', return_value=False), patch.object(net.urllib.request, 'getproxies', return_value={'https':'https://user:FAKE@host:1'}):
            with self.assertRaisesRegex(net.NetworkError, 'ProxyUnsupported'):
                net.proxies_for(net.settings({})['radar'])

    def test_direct_ignores_proxy_and_custom_ignores_no_proxy(self):
        req = urllib.request.Request('https://account.example.invalid/data')
        with patch.object(net.urllib.request, 'build_opener') as build, patch.dict(os.environ, {'no_proxy':'*'}):
            net.open_request(req, {'network':{'accounts':{'mode':'proxy','proxy':'http://127.0.0.1:12345'}}}, 'accounts')
            handler = build.call_args.args[0]
            handler.proxy_open(req, 'http://127.0.0.1:12345', 'https')
            self.assertEqual(req.host, '127.0.0.1:12345')
            self.assertEqual(req._tunnel_host, 'account.example.invalid')
        with patch.object(net.urllib.request, 'getproxies', side_effect=AssertionError('env read')):
            self.assertEqual(net.proxies_for({'mode':'direct'}), {})

    def test_cross_origin_port_downgrade_and_userinfo_never_receive_auth(self):
        req = urllib.request.Request('https://api.example.invalid/balance', headers={'Authorization':'Bearer FAKE_ONLY'})
        handler = net.SameOriginRedirect()
        for url in ('https://other.invalid/balance', 'http://api.example.invalid/balance',
                    'https://api.example.invalid:444/balance', 'https://u:p@api.example.invalid/balance'):
            with self.subTest(url=url), self.assertRaises(net.NetworkError):
                handler.redirect_request(req, None, 302, '', {}, url)
        moved = handler.redirect_request(req, None, 302, '', {}, 'https://api.example.invalid/new')
        self.assertEqual(moved.get_header('Authorization'), 'Bearer FAKE_ONLY')
        for code in (301,302,303,307,308):
            with self.assertRaises(net.NetworkError):
                handler.redirect_request(req,None,code,'',{},'https://other.invalid/new')

    def test_errors_are_categories_without_private_text(self):
        for cause, expected in ((socket.gaierror('PRIVATE'), 'DNSError'),
                                (ssl.SSLError('PRIVATE'), 'TLSError'),
                                (TimeoutError('PRIVATE'), 'Timeout')):
            code = net.error_code(urllib.error.URLError(cause))
            self.assertEqual(code, expected)
            self.assertNotIn('PRIVATE', str(state.safe_error(code)))
        self.assertEqual(state.error_label('HTTP403','main'), '站点拒绝访问')
        self.assertIn('Tibo雷达', state.refresh_notice([], {'main':'HTTP403'}, retry_in={'main':300}))


class StreamTests(unittest.TestCase):
    def test_early_stop_does_not_read_huge_tail(self):
        body = RINGS+b'<p>Data last updated: Oct 7, 2026 11:00 AM UTC</p>'+b'x'*1000000
        response = io.BytesIO(body)
        with patch.object(net, 'open_request', return_value=response):
            text = monitor._fetch_public_text(monitor.CODEX_RADAR_URL, 'text/html')
        self.assertLess(len(text), 32768)

    def test_unknown_metadata_stops_bounded_and_remains_unknown(self):
        body = RINGS+b'<div>'+b'x'*1000000
        with patch.object(net, 'open_request', return_value=io.BytesIO(body)):
            text = monitor._fetch_public_text(monitor.CODEX_RADAR_URL,'text/html')
        self.assertLessEqual(len(text),512*1024)
        parser=monitor._RadarParser();parser.feed(text.decode())
        self.assertIsNone(parser.updated)

    def test_trickle_and_total_deadline(self):
        class Trickle(io.BytesIO):
            def read1(self, n):
                clock[0] += 1
                return b'x'
        clock = [0]
        with patch.object(net.time, 'monotonic', side_effect=lambda:clock[0]), patch.object(net, 'open_request', return_value=Trickle()):
            with self.assertRaisesRegex(net.NetworkError, 'Timeout'):
                net.stream(urllib.request.Request('https://x.invalid'), {}, 'radar', limit=1000, budget=3)
        self.assertEqual(clock[0], 3)

    def test_cancellation_and_byte_budget(self):
        cancel = threading.Event(); cancel.set()
        with patch.object(net, 'open_request', return_value=io.BytesIO(b'ok')):
            with self.assertRaisesRegex(net.NetworkError, 'Cancelled'):
                net.stream(urllib.request.Request('https://x.invalid'), {}, 'radar', limit=10, budget=2, cancel=cancel)
        with patch.object(net, 'open_request', return_value=io.BytesIO(b'xxxx')):
            with self.assertRaisesRegex(net.NetworkError, 'ResponseTooLarge'):
                net.stream(urllib.request.Request('https://x.invalid'), {}, 'radar', limit=3, budget=2)

    def test_fallback_only_explicit_public_and_no_partial_mixing(self):
        cfg = {'network':{'radar':{'direct_fallback':True}}}
        req = urllib.request.Request('https://x.invalid')
        with patch.object(net, 'open_request', side_effect=[TimeoutError(), io.BytesIO(b'ok')]) as open_:
            self.assertEqual(net.stream(req, cfg, 'radar', limit=10, budget=20), b'ok')
            self.assertEqual([c.kwargs['direct'] for c in open_.call_args_list], [False, True])
        for error in (ssl.SSLError(), urllib.error.HTTPError(req.full_url,403,'',{},None)):
            if hasattr(error, 'close'):
                self.addCleanup(error.close)
            with patch.object(net, 'open_request', side_effect=error) as open_:
                with self.assertRaises(OSError): net.stream(req, cfg, 'radar', limit=10,budget=20)
                self.assertEqual(open_.call_count,1)
        forced = {'network':{'radar':{'mode':'proxy','proxy':'http://localhost:1','direct_fallback':True}}}
        with patch.object(net, 'open_request', side_effect=TimeoutError()) as open_:
            with self.assertRaises(TimeoutError): net.stream(req, forced, 'radar', limit=10,budget=20)
            self.assertEqual(open_.call_count,1)
        class Partial(io.BytesIO):
            def read1(self, n):
                if self.tell():
                    raise TimeoutError()
                return super().read1(1)
        with patch.object(net,'open_request',return_value=Partial(b'x')) as open_:
            with self.assertRaises(TimeoutError):net.stream(req,cfg,'radar',limit=10,budget=20)
            self.assertEqual(open_.call_count,1)

    def test_network_settings_are_resolved_each_request(self):
        proxy = {'https':'http://first.invalid:1'}
        with patch.object(net, '_pac_configured',return_value=False), patch.object(net.urllib.request,'getproxies',side_effect=lambda:dict(proxy)), patch.object(net.urllib.request,'build_opener') as build:
            net.open_request(urllib.request.Request('https://x.invalid'),{},'radar')
            self.assertEqual(build.call_args.args[0].proxies['https'],'http://first.invalid:1')
            proxy['https']='http://second.invalid:2'
            net.open_request(urllib.request.Request('https://x.invalid'),{},'radar')
            self.assertEqual(build.call_args.args[0].proxies['https'],'http://second.invalid:2')

    def test_proxy_credentials_never_reach_direct_fallback_or_original_request(self):
        cfg={'network':{'radar':{'direct_fallback':True}}}
        req=urllib.request.Request('https://example.invalid/')
        seen=[]
        def fake(request,*args,**kwargs):
            seen.append(request.get_header('Proxy-authorization'))
            if len(seen)==1:
                request.add_header('Proxy-authorization','FAKE_ONLY')
                raise TimeoutError()
            return io.BytesIO(b'ok')
        with patch.object(net,'open_request',side_effect=fake):
            self.assertEqual(net.stream(req,cfg,'radar',limit=10,budget=10),b'ok')
        self.assertEqual(seen,[None,None])
        self.assertIsNone(req.get_header('Proxy-authorization'))

    def test_redirect_drops_proxy_auth_for_the_new_route(self):
        req=urllib.request.Request('https://api.example.invalid/old',headers={
            'Authorization':'Bearer FAKE_ACCOUNT','Proxy-Authorization':'FAKE_PROXY'})
        moved=net.SameOriginRedirect().redirect_request(req,None,302,'',{},'https://api.example.invalid/new')
        self.assertIsNone(moved.get_header('Proxy-authorization'))
        self.assertEqual(moved.get_header('Authorization'),'Bearer FAKE_ACCOUNT')
        req=urllib.request.Request(updates.API,headers={'Proxy-Authorization':'FAKE_PROXY'})
        moved=updates.SafeRedirect().redirect_request(req,None,302,'',{},'https://github.com/next')
        self.assertIsNone(moved.get_header('Proxy-authorization'))
        with self.assertRaises(ValueError):
            updates.SafeRedirect().redirect_request(req,None,302,'',{},'https://github.com:444/next')


class FreshnessTests(unittest.TestCase):
    def test_unknown_stale_and_future_source_are_not_fresh(self):
        for updated, expected in ((None,'信源时间未提供'), (100000-10801,'信源预测过旧'), (100301,'信源时间异常')):
            data = dict(cr_main24=30, cr_main24_at=100000, cr_main_updated=updated)
            result = state.radar_status(data, verified=True, now=100000)
            self.assertTrue(result['stale'])
            self.assertEqual(result['reason'],expected)

    def test_partial_preserves_window_and_its_old_time_without_copying(self):
        old = dict(cr_main24=30, cr_main24_at=90000, cr_main24_updated=90000)
        current = dict(cr_main24=None, cr_main48=52, cr_main_updated=100000,cr_main48_at=100000)
        data = state.merge_radar(old,current,now=100000)
        self.assertEqual(data['cr_main24'],30)
        self.assertEqual(data['cr_main24_at'],90000)
        self.assertTrue(state.radar_status(data,24,True,now=100000)['stale'])
        self.assertFalse(state.radar_status(data,48,True,now=100000)['stale'])
        self.assertEqual(validate_result('main',data),data)

    def test_timestamp_split_comments_script_noise_and_utf8(self):
        parser = monitor._RadarParser()
        body = '<script>Data last updated: Jan 1, 2020 1:00 AM UTC</script>'+RINGS.decode()+'<p>Data last updated:<!-- --> Oct 7, 2026 11:00 AM UTC</p>'
        for c in body: parser.feed(c)
        self.assertEqual(parser.updated, 1791370800)
        self.assertEqual(len(parser.values),2)

    def test_metadata_validation_rejects_private_text(self):
        for bad in ('PRIVATE', False, -1, float('nan')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_result('main', dict(cr_main24=30, cr_main_updated=bad))


class BackoffTests(unittest.TestCase):
    def test_manual_refresh_and_exhausted_attempts_obey_429(self):
        clock = [1000]
        s = Scheduler('',Mock(),monotonic=lambda:clock[0],wall=lambda:clock[0])
        s.configure(['main','codex']); record=s.states['main'];record['attempt']=3
        s._finish('main',record,dict(ok=False,error='HTTP429',retry_after=7200),clock[0])
        s.refresh()
        self.assertEqual(record['due'],8200)
        self.assertEqual(s.states['codex']['due'],0)
        clock[0]=8300;s.refresh();self.assertEqual(record['due'],0)

    def test_http_date_and_nonfinite_retry_after(self):
        self.assertEqual(net.retry_after({'Retry-After':'Thu, 01 Jan 1970 00:02:00 GMT'},now=100),20)
        for val in ('NaN','inf','bad','-3'):
            self.assertEqual(net.retry_after({'Retry-After':val}),0)

    def test_update_failure_backoff_and_success_reset(self):
        controller = updates.UpdateController(Mock())
        controller.enabled=True;controller.next_check=999999
        with patch.object(updates.time,'monotonic',return_value=100):
            for delay in (60,300,900,86400):
                controller.events.put(('failed',dict(phase='check',error='Timeout',retry_after=0)))
                controller.tick()
                self.assertEqual(controller.next_check,100+delay)
                self.assertFalse(controller.busy)
            controller.events.put(('checked',None));controller.tick()
            self.assertEqual(controller.failures,0)
            self.assertEqual(controller.next_check,86500)

    def test_cancel_keeps_old_application_and_does_not_auto_restart(self):
        controller = updates.UpdateController(Mock());controller.enabled=True;controller.busy=True
        controller.request();self.assertTrue(controller.cancel.is_set())
        controller.next_check=999999
        controller.events.put(('failed',dict(phase='download',error='Cancelled',retry_after=0)))
        with patch.object(updates.time,'monotonic',return_value=100):controller.tick()
        self.assertEqual(controller.next_check,86500)
        self.assertIn('已取消',controller.app.menu.entryconfigure.call_args.kwargs['label'])

    def test_changed_network_rechecks_after_cancel_not_tomorrow(self):
        controller = updates.UpdateController(Mock());controller.enabled=True;controller.busy=True
        with patch.object(updates.time,'monotonic',return_value=100):
            controller.network_changed()
            controller.events.put(('failed',dict(phase='check',error='Cancelled',retry_after=0)))
            controller.tick()
            self.assertEqual(controller.next_check,101)

    def test_cancelled_download_reaps_only_owned_process(self):
        process=Mock();process.poll.return_value=None
        event=threading.Event();event.set()
        with patch.object(updates.subprocess,'Popen',return_value=process), patch('monitor_runtime.KillJob') as job:
            with self.assertRaisesRegex(net.NetworkError,'Cancelled'):
                updates.download(updates.API,cancel=event)
        job.return_value.close.assert_called_once()
        process.kill.assert_called_once()
        process.communicate.assert_called_once()

    def test_invalid_update_route_reports_network_error_before_spawning(self):
        with patch.object(updates.subprocess,'Popen',side_effect=AssertionError('spawn')):
            with self.assertRaisesRegex(net.NetworkError,'InvalidNetworkSettings'):
                updates.download(updates.API,config={'network':{'__invalid__':True}})

    def test_real_hung_helper_cancel_is_prompt_and_reaped(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
            children.append(child)
            return child
        event=threading.Event()
        timer=threading.Timer(.3,event.set);timer.start()
        started=time.monotonic()
        try:
            with patch.object(updates.subprocess,'Popen',side_effect=launch):
                with self.assertRaisesRegex(net.NetworkError,'Cancelled'):
                    updates.download(updates.API,cancel=event)
            self.assertLess(time.monotonic()-started,3)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdout.closed)
        finally:
            timer.cancel();timer.join()
            for child in children:
                if child.poll() is None:child.kill();child.wait(timeout=2)

    def test_real_hung_helper_hard_deadline(self):
        real_popen = subprocess.Popen
        children=[]
        def launch(*args,**kwargs):
            child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
            children.append(child);return child
        try:
            with patch.object(updates.subprocess,'Popen',side_effect=launch), patch.object(updates.time,'monotonic',side_effect=[0,24]):
                with self.assertRaisesRegex(net.NetworkError,'Timeout'):
                    updates.download(updates.API)
            self.assertIsNotNone(children[0].poll())
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait(timeout=2)

    def test_update_cleanup_on_checksum_failure_and_phase_is_not_check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            controller=updates.UpdateController(Mock(),tmp)
            release={'zip':updates.ASSETS+'v9.0.0/app.zip','sums':updates.ASSETS+'v9.0.0/SHA256SUMS.txt'}
            with patch.object(updates,'download',side_effect=[None,b'fake sums']), patch.object(updates,'unpack_verified',side_effect=ValueError('DownloadChecksumMismatch')):
                controller._work(release)
            event,payload=controller.events.get_nowait()
            self.assertEqual((event,payload['phase']),('failed','verify'))
            self.assertFalse((Path(tmp)/'update-stage.json').exists())


class NetworkDialogTests(unittest.TestCase):
    def test_save_or_cancel_uses_only_local_config(self):
        import tkinter as tk
        from widget_network import show_network
        root=tk.Tk();root.withdraw()
        try:
            cfg=dict(monitor.DEFAULT_CONFIG)
            save=Mock(return_value=True)
            def click_save():
                win=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                button=next(w for panel in win.winfo_children() for w in panel.winfo_children() if isinstance(w,tk.Button) and w.cget('text')=='保存')
                button.invoke()
            root.after(20,click_save)
            with patch.object(net,'open_request',side_effect=AssertionError('unexpected network')):
                self.assertTrue(show_network(Mock(root=root),cfg,save))
            self.assertEqual(set(cfg['network']),set(net.GROUPS))
            original=json.dumps(cfg,sort_keys=True)
            def close():
                win=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel));win.destroy()
            root.after(20,close)
            self.assertFalse(show_network(Mock(root=root),cfg,save))
            self.assertEqual(json.dumps(cfg,sort_keys=True),original)
        finally:root.destroy()

    def test_small_screen_high_scaling_keeps_controls_accessible(self):
        import tkinter as tk
        import widget_network
        root=tk.Tk();root.withdraw()
        original=root.tk.call('tk','scaling')
        failures=[]
        def verify():
            try:
                win=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                win.update_idletasks()
                self.assertLessEqual(win.winfo_width(),312)
                self.assertLessEqual(win.winfo_height(),212)
                bars=[w for w in win.winfo_children() if isinstance(w,tk.Scrollbar)]
                self.assertTrue(any(w.winfo_manager() for w in bars))
            except Exception as exc:failures.append(exc)
            finally:win.destroy()
        try:
            root.tk.call('tk','scaling',4)
            root.after(30,verify)
            with patch.object(widget_network,'work_area',return_value=(0,0,320,220)):
                widget_network.show_network(Mock(root=root),dict(monitor.DEFAULT_CONFIG),Mock())
            if failures:raise failures[0]
        finally:
            root.tk.call('tk','scaling',original);root.destroy()


if __name__ == '__main__':
    unittest.main()
