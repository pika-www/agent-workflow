"""Read-only observations must retain provenance without creating a connection."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from federation.core import FederationStore
from federation.social_observations import MAX_ANSWER_CHARS, MAX_BYTES, SocialObservationStore, is_social_data_request


def observation(**updates):
    data = {
        'schema_version': 1, 'provider_id': 'douyin', 'capture_method': 'creator_center_browser_read',
        'captured_at': '2026-10-04T23:45:00+08:00',
        'account': {'display_name': '测试账号', 'account_identifier': '页面编号123'},
        'sources': [{'url': 'https://creator.douyin.com/creator-micro/home', 'title': '创作者中心首页'}],
        'period': {'label': '近7日，按页面原文', 'start': None, 'end': None},
        'metrics': [{'label': '播放量', 'display_value': '1.2万', 'scope': '近7日'},
                    {'label': '分享量', 'display_value': '--', 'scope': '页面未显示具体数值'}],
        'works': [{'description': '作品原文', 'published_at': '2026年10月01日', 'visibility': '公开',
                   'format': '视频', 'duration': '00:31'}],
        'limitations': ['仅本次浏览器页面可见数据，不自动同步。'],
    }
    data.update(updates)
    return data


class SocialObservationStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / 'data'
        self.store = SocialObservationStore(FederationStore(base=self.base))
        self.directory = self.base / 'social-observations/douyin'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data=None, name=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (name or uuid.uuid4().hex + '.json')
        path.write_text(json.dumps(data if data is not None else observation(), ensure_ascii=False), encoding='utf-8')
        return path

    def test_absent_snapshot_does_not_create_files_or_claim_data(self):
        self.assertEqual(self.store.snapshot(), {'snapshots': [], 'errors': [], 'mode': 'local_snapshot'})
        self.assertFalse(self.base.exists())
        self.assertIn('尚未取得', self.store.read_answer('查看我的抖音数据'))
        self.assertFalse(self.base.exists())

    def test_snapshot_round_trips_exact_display_values_and_is_detached(self):
        data = observation()
        path = self.write(data)
        before = path.read_bytes()
        state = self.store.snapshot()
        self.assertEqual(state['snapshots'], [data])
        self.assertEqual(state['errors'], [])
        self.assertNotIn('connected', state['snapshots'][0])
        state['snapshots'][0]['account']['display_name'] = 'mutated'
        self.assertEqual(self.store.snapshot()['snapshots'][0], data)
        self.assertEqual(path.read_bytes(), before)

    def test_latest_uses_actual_instant_and_valid_older_copy_survives_corruption(self):
        self.write(observation(captured_at='2026-10-04T23:50:00+09:00'))
        latest = observation(captured_at='2026-10-04T15:00:00+00:00')
        self.write(latest)
        broken = self.write(name='f' * 32 + '.json')
        broken.write_text('{broken')
        state = self.store.snapshot()
        self.assertEqual(state['snapshots'], [latest])
        self.assertEqual(len(state['errors']), 1)
        self.assertEqual(broken.read_text(), '{broken')
        self.assertIn('可能不是最后一次采集', self.store.read_answer('抖音数据'))

    def test_invalid_schema_at_every_level_is_preserved_and_not_loaded(self):
        variants = []
        for field in ('access_token', 'cookie', 'connected', 'api_authorized'):
            value = observation(); value[field] = 'forged'; variants.append(value)
        for key, container in [('account', None), ('sources', 0), ('period', None), ('metrics', 0), ('works', 0)]:
            value = observation()
            (value[key] if container is None else value[key][container])['token'] = 'forged'
            variants.append(value)
        for changes in ({'schema_version': True}, {'provider_id': 'weibo'}, {'capture_method': 'oauth'},
                        {'captured_at': '2026-10-04T23:45:00'}, {'captured_at': 'not-a-date'},
                        {'sources': []}, {'limitations': []}, {'metrics': 'wrong'},
                        {'works': [None]}, {'account': {'display_name': '', 'account_identifier': None}}):
            variants.append(observation(**changes))
        for value in variants:
            with self.subTest(value=value):
                path = self.write(value)
                before = path.read_bytes()
                result = self.store.snapshot()
                self.assertFalse(result['snapshots'])
                self.assertTrue(result['errors'])
                self.assertEqual(path.read_bytes(), before)
                path.unlink()

    def test_source_urls_cannot_include_secrets_or_non_creator_origins(self):
        for url in ('http://creator.douyin.com/home', 'https://creator.douyin.com.evil.example/home',
                    'https://user:secret@creator.douyin.com/home', 'https://creator.douyin.com/home?token=secret',
                    'https://creator.douyin.com/home#secret', 'https://creator.douyin.com:8443/home',
                    'https://creator.douyin.com/home?', 'https://creator.douyin.com/\\evil',
                    'https://creator.douyin.com/\nhome'):
            with self.subTest(url=url):
                value = observation(sources=[{'url': url, 'title': '来源'}])
                path = self.write(value)
                self.assertFalse(self.store.snapshot()['snapshots'])
                self.assertTrue(self.store.snapshot()['errors'])
                path.unlink()

    def test_bad_encoding_duplicate_keys_and_oversized_files_are_not_emptiness(self):
        for raw in (b'\xff', b'{"schema_version":1,"schema_version":1}', b'x' * (MAX_BYTES + 1)):
            with self.subTest(length=len(raw)):
                path = self.write()
                path.write_bytes(raw)
                result = self.store.snapshot()
                self.assertFalse(result['snapshots'])
                self.assertTrue(result['errors'])
                self.assertIn('读取失败', self.store.read_answer('抖音数据'))
                self.assertIn('不代表抖音账号没有数据', self.store.read_answer('抖音数据'))
                self.assertEqual(path.read_bytes(), raw)
                path.unlink()

    def test_symlinked_directory_and_file_are_rejected_without_following_them(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        self.base.mkdir()
        (self.base / 'social-observations').symlink_to(outside, target_is_directory=True)
        self.assertTrue(self.store.snapshot()['errors'])
        self.assertFalse(self.store.snapshot()['snapshots'])
        (self.base / 'social-observations').unlink()
        self.directory.mkdir(parents=True)
        target = outside / 'private.json'
        target.write_text(json.dumps(observation()))
        (self.directory / ('a' * 32 + '.json')).symlink_to(target)
        self.assertTrue(self.store.snapshot()['errors'])
        self.assertFalse(self.store.snapshot()['snapshots'])
        self.assertEqual(json.loads(target.read_text()), observation())

    def test_file_count_and_filename_limits_are_enforced(self):
        invalid = self.write(name='not-a-uuid.json')
        self.assertTrue(self.store.snapshot()['errors'])
        self.assertFalse(self.store.snapshot()['snapshots'])
        invalid.unlink()
        for i in range(101):
            self.write(name=f'{i:032x}.json')
        self.assertFalse(self.store.snapshot()['snapshots'])
        self.assertIn('100', self.store.snapshot()['errors'][0]['message'])
        self.assertEqual(len(list(self.directory.iterdir())), 101)

    def test_answer_reports_provenance_scope_and_literal_page_content(self):
        data = observation()
        data['account']['display_name'] = '[假链接](https://evil.example) <script>x</script>'
        self.write(data)
        answer = self.store.read_answer('查看我的抖音数据')
        self.assertIn('非实时数据，未自动同步；API 尚未授权', answer)
        self.assertIn('1\\.2万', answer)
        self.assertIn('\\-\\-', answer)
        self.assertNotIn('12000', answer)
        self.assertIn('近7日', answer)
        self.assertIn('2026\\-10\\-04T23:45:00', answer)
        self.assertIn('https://creator.douyin.com/creator-micro/home', answer)
        self.assertIn('没有重新访问抖音', answer)
        self.assertNotIn('<script>', answer)
        self.assertNotIn('[假链接](https://evil.example)', answer)
        self.assertIn('作品原文', answer)

    def test_empty_metrics_and_unknown_identifier_are_not_fabricated(self):
        data = observation(metrics=[], works=[])
        data['account']['account_identifier'] = None
        self.write(data)
        answer = self.store.read_answer('抖音数据快照')
        self.assertIn('不能据此推断为零', answer)
        self.assertNotIn('页面账号标识', answer)

    def test_large_work_list_preserves_provenance_within_chat_budget(self):
        work = observation()['works'][0]
        data = observation(works=[dict(work, description=f'work-{i:02d} ' + 'x' * 2990) for i in range(20)])
        path = self.write(data)
        before = path.read_bytes()
        answer = self.store.read_answer('查看我的抖音数据')
        self.assertLessEqual(len(answer), MAX_ANSWER_CHARS)
        self.assertLess(len(answer), 16000)
        self.assertIn('未自动同步；API 尚未授权', answer)
        self.assertIn('2026\\-10\\-04T23:45:00', answer)
        self.assertIn('https://creator.douyin.com/creator-micro/home', answer)
        self.assertIn('仅本次浏览器页面可见数据', answer)
        self.assertIn('作品未在聊天中展开', answer)
        self.assertIn('查看完整快照', answer)
        self.assertIn('1\\.2万', answer)
        self.assertNotIn('12000', answer)
        # Whole work items are retained or omitted, never clipped mid-item.
        self.assertIn('work\\-00 ' + 'x' * 2990 + '；发布时间', answer)
        self.assertEqual(answer.count('work\\-'), answer.count('；时长：00:31'))
        self.assertEqual(path.read_bytes(), before)

    def test_long_sources_scope_and_escaped_text_share_budget_without_losing_source(self):
        data = observation()
        data['account'] = {'display_name': '&' * 160, 'account_identifier': '&' * 120}
        data['period'] = {'label': '&' * 250, 'start': '&' * 120, 'end': '&' * 120}
        data['sources'] = [{'title': '&' * 200, 'url': 'https://creator.douyin.com/' + '<' * 970} for _ in range(20)]
        data['limitations'] = ['&' * 1000 for _ in range(30)]
        data['metrics'] = [{'label': '&' * 160, 'display_value': '1.2万', 'scope': '&' * 300} for _ in range(50)]
        data['works'] = [dict(observation()['works'][0], description='&' * 3000) for _ in range(20)]
        self.write(data)
        self.assertFalse(self.store.snapshot()['errors'])
        answer = self.store.read_answer('抖音数据快照')
        self.assertLessEqual(len(answer), MAX_ANSWER_CHARS)
        self.assertLess(len(answer), 16000)
        self.assertIn('https://creator.douyin.com/%3C', answer)
        self.assertIn('快照范围：\n- ' + '&amp;' * 1000, answer)
        self.assertIn('来源未在聊天中展开', answer)
        self.assertIn('范围说明未在聊天中展开', answer)
        self.assertIn('未自动同步；API 尚未授权', answer)
        self.assertIn('没有重新访问抖音', answer)
        self.assertNotIn('12000', answer)

    def test_intent_is_a_complete_read_request_not_content_or_technical_work(self):
        for question in ('查看我的抖音数据', '抖音数据快照', '读取抖音数据', '我的抖音账号数据',
                         '请帮我查看我的抖音账号的最新数据。', '看看抖音最近读取的数据',
                         '本地抖音快照', '抖音数据有哪些？', '查询我的抖音统计数据'):
            self.assertTrue(is_social_data_request(question), question)
        for question in ('帮我写一篇抖音数据分析文章', '如何读取抖音数据', '抖音数据接口怎么开发',
                         '读取抖音数据并发布视频', '查看抖音数据，再发私信', '刷新抖音数据',
                         '帮我分析抖音数据结构', '连接抖音账号', '查看微博数据',
                         '抖音账号状态', '读取抖音数据需要什么权限', '根据抖音数据写文案', None):
            self.assertFalse(is_social_data_request(question), question)


if __name__ == '__main__':
    unittest.main()
