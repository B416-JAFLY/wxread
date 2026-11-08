import unittest
from unittest.mock import Mock, patch
import main


class ReadingRecoveryTests(unittest.TestCase):
    def run_reading(self, replies, renewal_side_effect=None):
        with patch.object(main, 'READ_NUM', 1), patch.object(main, 'renew_session', side_effect=renewal_side_effect) as renew, patch.object(main.session, 'post', side_effect=replies), patch.object(main.time, 'sleep'), patch.object(main, 'notify_result') as notify:
            main.run()
            return renew, notify

    def test_startup_renewal_failure_can_use_existing_cookie(self):
        reply = Mock()
        reply.json.return_value = {'succ': 1, 'synckey': 'test'}
        renew, notify = self.run_reading([reply], main.SessionExpiredError('expired'))
        self.assertEqual(renew.call_count, 1)
        self.assertIn('完成次数：1/1', notify.call_args.args[0])
        self.assertTrue(notify.call_args.kwargs['is_success'])

    def test_missing_synckey_recovery_is_bounded(self):
        reply = Mock()
        reply.json.return_value = {'succ': 1}
        with patch.object(main, 'READ_NUM', 1), patch.object(main, 'renew_session'), patch.object(main, 'fix_no_synckey') as repair, patch.object(main.session, 'post', return_value=reply) as post, patch.object(main.time, 'sleep'), patch.object(main, 'notify_result') as notify:
            with self.assertRaises(main.SessionExpiredError):
                main.run()
            self.assertEqual(post.call_count, 3)
            self.assertEqual(repair.call_count, 2)
            self.assertFalse(notify.call_args.kwargs['is_success'])

    def test_renewal_preserves_all_returned_cookies(self):
        reply = Mock()
        reply.json.return_value = {'succ': 1}
        reply.cookies.get_dict.return_value = {'wr_skey': 'new', 'wr_rt': 'refresh'}
        with patch.object(main.session, 'post', return_value=reply), patch.dict(main.cookies, {}, clear=True):
            main.renew_session()
            self.assertEqual(main.session.cookies.get('wr_rt'), 'refresh')
            self.assertEqual(main.session.cookies.get('wr_skey'), 'new')


if __name__ == '__main__':
    unittest.main()
