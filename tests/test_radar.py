"""Signal lifecycle fixtures; no credentials, network, GUI or real cache."""
import unittest
from datetime import datetime, timezone

from quota_radar import parse_forecast, radar_view
from quota_state import radar_status, merge_radar
from monitor_runtime import validate_result

NOW = datetime(2026, 10, 22, 9, tzinfo=timezone.utc).timestamp()


def announced():
    return dict(mode='announced', updated_at=NOW,
                last_reset_at=NOW-2*86400,
                probabilities=dict(rounded_24h=22, rounded_48h=39, signal_percent=93),
                official_signal=dict(tweet_id='signal-a', at=NOW-7200, kind='signal',
                                     signal_type='promise'),
                latest_alert=dict(id='signal-a', kind='watch', state='active',
                                  source_at=NOW-7200))


class RadarLifecycleTests(unittest.TestCase):
    def parse(self, payload):
        return validate_result('main', parse_forecast(payload, NOW))

    def test_announcement_uses_signal_score_not_cadence(self):
        data = self.parse(announced())
        self.assertEqual((data['cr_main24'], data['cr_main48']), (93, 93))
        self.assertEqual(radar_view(data, now=NOW)['note'], '已预告')
        self.assertFalse(radar_status(data, verified=True, now=NOW)['stale'])

    def test_cadence_only_is_successful_quiet_not_probability_or_failure(self):
        payload=announced()
        payload.update(mode='model', official_signal=None, latest_alert=None)
        data = self.parse(payload)
        self.assertIsNone(data['cr_main24'])
        self.assertIsNone(data['cr_main48'])
        self.assertEqual(radar_view(data, now=NOW)['note'], '暂无预告')
        self.assertFalse(radar_status(data, verified=True, now=NOW)['stale'])

    def test_no_score_does_not_fall_back_to_historical_probability(self):
        for score in (None, True, '93', -1, 101, float('nan')):
            payload=announced();payload['probabilities']['signal_percent']=score
            with self.subTest(score=score):
                view=radar_view(self.parse(payload), now=NOW)
                self.assertEqual(view['phase'], 'announced')
                self.assertIsNone(view['score'])

    def test_score_zero_and_full_are_not_missing(self):
        for score in (0,100):
            payload=announced();payload['probabilities']['signal_percent']=score
            self.assertEqual(radar_view(self.parse(payload),now=NOW)['score'],score)

    def test_explicit_deadline_expires_on_clock_without_another_query(self):
        payload=announced();payload['latest_alert']['window']={'end':NOW+60}
        data=self.parse(payload)
        self.assertEqual(radar_view(data,now=NOW+59)['score'],93)
        self.assertEqual(radar_view(data,now=NOW+60)['note'],'预告失效')
        self.assertIsNone(radar_view(data,now=NOW+60)['score'])

    def test_unspecified_deadline_is_not_reused_forever(self):
        data=self.parse(announced());edge=data['cr_main_review_at']
        self.assertEqual(radar_view(data,now=edge)['note'],'预告待核验')
        self.assertIsNone(radar_view(data,now=edge)['score'])

    def test_response_arriving_after_deadline_does_not_cache_high_score(self):
        payload=announced();payload['latest_alert']['expires_at']=NOW-1
        data=self.parse(payload)
        self.assertEqual(data['cr_main_phase'],'expired')
        self.assertIsNone(data['cr_main24'])
        self.assertIsNone(data['cr_main48'])

    def test_withdrawn_expired_and_cancelled_signals_clear_score(self):
        for state in ('expired','cancelled','canceled','withdrawn','retracted'):
            payload=announced();payload['latest_alert']['state']=state
            with self.subTest(state=state):
                view=radar_view(self.parse(payload),now=NOW)
                self.assertEqual(view['note'],'预告失效')
                self.assertIsNone(view['score'])

    def test_withdrawal_of_old_event_does_not_cancel_new_announcement(self):
        payload=announced();payload['latest_alert'].update(id='older-event',state='expired',expires_at=NOW-100)
        self.assertEqual(radar_view(self.parse(payload),now=NOW)['score'],93)

    def test_model_response_can_explicitly_expire_previous_announcement(self):
        payload=announced();payload.update(mode='model',official_signal=None)
        payload['latest_alert']['state']='expired'
        self.assertEqual(self.parse(payload)['cr_main_phase'],'expired')

    def test_completion_after_announcement_clears_pending_score(self):
        payload=announced();payload['last_reset_at']=NOW-60
        view=radar_view(self.parse(payload),now=NOW)
        self.assertEqual(view['note'],'已重置')
        self.assertIsNone(view['score'])

    def test_completed_event_without_watch_and_next_announcement(self):
        payload=announced();payload.update(mode='model',official_signal=None,
                last_reset_at=NOW-60,latest_alert={'kind':'reset','state':'confirmed'})
        completed=self.parse(payload)
        self.assertEqual(radar_view(completed,now=NOW)['phase'],'completed')
        self.assertEqual(radar_view(completed,now=NOW+86400)['phase'],'quiet')
        payload=announced();payload['last_reset_at']=NOW-7201
        self.assertEqual(radar_view(self.parse(payload),now=NOW)['phase'],'announced')

    def test_banked_reset_is_not_a_completed_global_reset(self):
        payload=announced();payload.update(mode='model',official_signal=None,
                latest_alert={'kind':'banked','state':'confirmed','source_at':NOW})
        self.assertEqual(radar_view(self.parse(payload),now=NOW)['phase'],'quiet')
        payload=announced();payload['official_signal']['kind']='banked'
        self.assertEqual(radar_view(self.parse(payload),now=NOW)['phase'],'quiet')

    def test_tease_has_own_expiry_and_does_not_use_model_probabilities(self):
        payload=announced();payload.update(mode='model',official_signal=None,latest_alert=None,
                tease_signal={'post':{'id':'hint-a','at':NOW-60},'floor_24h':50,
                              'floor_48h':75,'expires_at':NOW+60})
        data=self.parse(payload)
        self.assertEqual(radar_view(data,48,NOW)['score'],75)
        self.assertEqual(radar_view(data,now=NOW)['note'],'重置线索')
        self.assertIsNone(radar_view(data,48,NOW+60)['score'])

    def test_merge_quiet_expired_and_completed_cannot_resurrect_old_high_score(self):
        old=self.parse(announced())
        for phase in ('quiet','expired','completed'):
            current=dict(old,cr_main_phase=phase,cr_main24=None,cr_main48=None)
            data=merge_radar(dict(old,cw_pct=79),current,NOW)
            self.assertIsNone(data['cr_main24'])
            self.assertIsNone(data['cr_main48'])
            self.assertEqual(data['cw_pct'],79)

    def test_transport_error_and_stale_source_remain_visible(self):
        data=self.parse(announced())
        self.assertTrue(radar_status(data,verified=True,error='Timeout',now=NOW)['stale'])
        self.assertTrue(radar_status(data,verified=False,now=NOW)['stale'])
        data['cr_main_updated']=NOW-10801
        self.assertEqual(radar_status(data,verified=True,now=NOW)['reason'],'信源预测过旧')

    def test_bad_schema_future_time_or_deadline_is_not_quiet_success(self):
        for payload in (None,[],{}, {'mode':'bad'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.parse(payload)
        for value in (None,True,'bad','2026-10-22T08:00:00',NOW+301):
            payload=announced();payload['official_signal']['at']=value
            payload['latest_alert']['source_at']=value
            with self.subTest(value=value),self.assertRaises(ValueError):self.parse(payload)
        payload=announced();payload['latest_alert']['expires_at']='private malformed data'
        with self.assertRaises(ValueError):self.parse(payload)

    def test_missing_update_time_is_not_replaced_with_query_time(self):
        payload=announced();payload['updated_at']=None
        data=self.parse(payload)
        self.assertIsNone(data['cr_main_updated'])
        self.assertEqual(radar_status(data,verified=True,now=NOW)['reason'],'信源时间未提供')

    def test_cache_fields_contain_no_raw_posts_or_url(self):
        payload=announced();payload['official_signal'].update(summary='PUBLIC_POST',url='https://x.com/example')
        data=self.parse(payload)
        self.assertNotIn('PUBLIC_POST',str(data))
        self.assertNotIn('https://',str(data))
        self.assertEqual(len(data['cr_main_signal_key']),64)
