"""Hydrogen model discovery and real SDK configuration; no paid API calls."""
import logging
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
try:
    from google.genai import types
except ImportError:
    types = None
from test_conversation_images import Gemini


@unittest.skipIf(types is None, "google-genai is required for SDK configuration checks")
class HydrogenTests(unittest.TestCase):
    def setUp(self):
        self.pipe = object.__new__(Gemini)
        self.pipe.valves = Gemini.Valves()
        self.pipe.log = logging.getLogger('hydrogen-test')
        self.pipe._model_cache = None
        self.pipe._model_cache_time = 0

    def config(self, body=None, model='gemini-4-hydrogen'):
        return self.pipe._configure_generation(body or {}, None, {}, model_id=model)

    def test_supported_levels_and_legacy_budget_omitted(self):
        for level in ('low', 'medium', 'high', 'xhigh'):
            with self.subTest(level=level):
                cfg = self.config({'reasoning_effort': level, 'thinking_budget': 0,
                                   'temperature': .2, 'top_p': .3, 'top_k': 5})
                self.assertEqual(cfg.thinking_config.thinking_level.value.lower(), 'high' if level == 'xhigh' else level)
                self.assertIsNone(cfg.thinking_config.thinking_budget)
                self.assertTrue(all(getattr(cfg, key) is None for key in ('temperature', 'top_p', 'top_k')))

    def test_minimal_normalized_and_manual_override(self):
        self.assertEqual(self.config({'reasoning_effort': 'minimal'}).thinking_config.thinking_level.value.lower(), 'low')
        self.pipe.valves.THINKING_LEVEL = 'xhigh'
        self.assertEqual(self.config().thinking_config.thinking_level.value.lower(), 'high')
        self.assertEqual(self.config({'reasoning_effort': 'medium'}).thinking_config.thinking_level.value.lower(), 'medium')

    def test_default_preserves_provider_thinking_and_no_image_generation(self):
        cfg = self.config()
        self.assertIsNone(cfg.thinking_config.thinking_level)
        self.assertIsNone(cfg.thinking_config.thinking_budget)
        self.assertFalse(self.pipe._check_image_generation_support('gemini-4-hydrogen'))
        self.assertTrue(self.pipe._is_auto_thinking_candidate_model('gemini-4-hydrogen'))

    def test_discovery_with_saved_valves_and_whitelist(self):
        self.pipe.valves.MODEL_ADDITIONAL = 'gemini-3.7-flash'
        client = Mock()
        client.models.list.return_value = []
        self.pipe._get_client = lambda: client
        models = self.pipe.get_google_models(force_refresh=True)
        self.assertEqual(sum(m['id'] == 'gemini-4-hydrogen' for m in models), 1)
        self.pipe.valves.MODEL_WHITELIST = 'gemini-3.7-flash'
        self.assertNotIn('gemini-4-hydrogen', [m['id'] for m in self.pipe.get_google_models(force_refresh=True)])
        self.pipe.valves.MODEL_WHITELIST = 'gemini-4-hydrogen'
        client.models.list.return_value = [types.Model(name='models/gemini-4-hydrogen', supported_actions=['generateContent'])]
        self.assertEqual(len(self.pipe.get_google_models(force_refresh=True)), 1)

    def test_prefix_and_older_model_compatibility(self):
        self.assertEqual(self.pipe._prepare_model_id('google_gemini.gemini-4-hydrogen'), 'gemini-4-hydrogen')
        self.assertEqual(self.config({'reasoning_effort': 'xhigh'}, 'gemini-3.8-flash').thinking_config.thinking_level.value.lower(), 'high')
        self.assertEqual(self.config({'thinking_budget': 1024}, 'gemini-2.5-flash').thinking_config.thinking_budget, 1024)

    def test_auto_levels_followup_and_stale_history(self):
        for text, expected in [('안녕', 'low'), ('장단점을 비교해줘', 'medium'), ('정리를 엄밀하게 증명해줘', 'high')]:
            body = {'messages': [{'role': 'user', 'content': text}]}
            self.assertEqual(self.pipe._select_auto_thinking_level(body, 'gemini-4-hydrogen')[0], expected)
        body = {'messages': [{'role': 'user', 'content': '정리를 엄밀하게 증명해줘'},
                             {'role': 'assistant', 'content': '증명'},
                             {'role': 'user', 'content': '더 자세히 설명해줘'}]}
        self.assertEqual(self.pipe._select_auto_thinking_level(body, 'gemini-4-hydrogen')[0], 'high')
        body['messages'][-1]['content'] = '고마워'
        self.assertEqual(self.pipe._select_auto_thinking_level(body, 'gemini-4-hydrogen')[0], 'low')
        self.pipe.valves.AUTO_THINKING_DEFAULT_LEVEL = 'xhigh'
        self.assertEqual(self.pipe._select_auto_thinking_level(body, 'gemini-4-hydrogen')[0], 'high')
        self.pipe.valves.AUTO_THINKING = False
        self.assertIsNone(self.pipe._select_auto_thinking_level(body, 'gemini-4-hydrogen')[0])

    def test_image_intent_and_visual_followup_selection(self):
        session = SimpleNamespace(entries={'image': {'role': 'user'}})
        for text, expected in [('이 사진 설명해줘', False), ('이 문제 풀어줘', False),
                               ('이미지 생성 프롬프트를 만들어줘', False), ('그리지 마', False),
                               ('고양이를 그려줘', True), ('이번에는 수채화로', True)]:
            body = {'messages': [{'role': 'user', 'content': text}]}
            self.assertEqual(self.pipe._needs_conversation_images(body, session), expected, text)



@unittest.skipIf(types is None, "google-genai is required for SDK integration checks")
class HydrogenPipelineTests(unittest.IsolatedAsyncioTestCase):
    from test_conversation_images import GeminiFullPipelineTests as _Base
    setUp = _Base.setUp
    asyncTearDown = _Base.asyncTearDown
    response = _Base.response
    tool_response = _Base.tool_response

    async def test_text_requests_stream_once_without_router_or_image_calls(self):
        from unittest.mock import AsyncMock, patch
        self.pipe.valves.AUTO_THINKING = True
        self.pipe._get_client = lambda: self.client
        self.pipe._handle_streaming_response = lambda iterator, *a, **kw: iterator
        for text, level in [('안녕', 'low'), ('장단점을 비교해줘', 'medium'),
                            ('정리를 엄밀하게 증명해줘', 'high'),
                            ('이미지 생성 프롬프트를 만들어줘', 'low')]:
            stream = AsyncMock(return_value=object())
            with patch.object(self.client.aio.models, 'generate_content_stream', stream), patch.object(
                    self.client.aio.models, 'generate_content', AsyncMock()) as nonstream:
                result = await self.pipe.pipe({'model': 'gemini-4-hydrogen', 'stream': True,
                    'messages': [{'role': 'user', 'content': text}]})
            self.assertIs(result, stream.return_value)
            stream.assert_awaited_once()
            nonstream.assert_not_awaited()
            cfg = stream.call_args.kwargs['config']
            self.assertEqual(cfg.thinking_config.thinking_level.value.lower(), level)
            self.assertFalse(any(callable(t) for t in cfg.tools or []))
            self.image_api.assert_not_awaited()

    async def test_image_generation_keeps_hydrogen_and_calls_image_model_once(self):
        from unittest.mock import AsyncMock, patch
        self.pipe.valves.AUTO_THINKING = True
        http = AsyncMock(side_effect=[self.tool_response(), self.response('완료')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model': 'gemini-4-hydrogen', 'stream': True,
                'messages': [{'role': 'user', 'content': '고양이를 그려줘'}]}, __event_emitter__=AsyncMock())
        self.assertIn('![Generated Image', result)
        self.image_api.assert_awaited_once()
        self.assertEqual(self.image_api.call_args.kwargs['model'], 'gemini-3.1-flash-image')
        self.assertEqual(http.await_count, 2)
        self.assertTrue(all(c.kwargs['model'] == 'gemini-4-hydrogen' for c in http.call_args_list))

    async def test_manual_override_and_background_exclusion(self):
        from unittest.mock import AsyncMock, patch
        self.pipe.valves.AUTO_THINKING = True
        self.pipe._get_client = lambda: self.client
        self.pipe._handle_streaming_response = lambda iterator, *a, **kw: iterator
        for effort, metadata, expected in [('medium', {}, 'medium'), ('xhigh', {}, 'high'),
                                            (None, {'task': 'title_generation'}, None)]:
            stream = AsyncMock(return_value=object())
            with patch.object(self.client.aio.models, 'generate_content_stream', stream):
                await self.pipe.pipe({'model': 'gemini-4-hydrogen', 'stream': True,
                    'reasoning_effort': effort, 'messages': [{'role': 'user', 'content': '안녕'}]},
                    __metadata__=metadata)
            thinking = stream.call_args.kwargs['config'].thinking_config
            actual = thinking.thinking_level
            self.assertEqual(actual.value.lower() if actual else None, expected)
