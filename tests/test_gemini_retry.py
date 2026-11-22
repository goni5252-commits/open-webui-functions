"""Capacity retry regressions with real SDK errors and no network or real sleeps."""
import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, patch
from google.genai.errors import ClientError, ServerError
from test_conversation_images import Gemini
import test_conversation_images as helpers


def error(code):
    cls = ClientError if code < 500 else ServerError
    return cls(code, {'error': {'code': code, 'message': 'Resource exhausted'}})


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = object.__new__(Gemini)
        self.pipe.valves = Gemini.Valves(RETRY_COUNT=2)
        self.pipe.log = logging.getLogger('retry-test')
        self.sleep = AsyncMock()
        self.patch = patch.object(asyncio, 'sleep', self.sleep)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_capacity_then_success_and_bounded_backoff(self):
        call = AsyncMock(side_effect=[error(429), error(429), 'ok'])
        self.assertEqual(await self.pipe._retry_with_backoff(call), 'ok')
        self.assertEqual(call.await_count, 3)
        waits = [c.args[0] for c in self.sleep.call_args_list]
        self.assertTrue(4 <= waits[0] <= 5)
        self.assertTrue(8 <= waits[1] <= 9)

    async def test_exhaustion_and_zero_retries(self):
        for retries in (0, 2):
            self.pipe.valves.RETRY_COUNT = retries
            failure = error(429)
            call = AsyncMock(side_effect=failure)
            with self.assertRaises(ClientError) as raised:
                await self.pipe._retry_with_backoff(call)
            self.assertIs(raised.exception, failure)
            self.assertEqual(call.await_count, retries + 1)

    async def test_only_transient_errors_retry(self):
        for failure in (error(400), error(401), error(403), ValueError('bad'), asyncio.CancelledError()):
            call = AsyncMock(side_effect=failure)
            with self.assertRaises(type(failure)):
                await self.pipe._retry_with_backoff(call)
            call.assert_awaited_once()
        call = AsyncMock(side_effect=[error(503), 'ok'])
        self.assertEqual(await self.pipe._retry_with_backoff(call), 'ok')
        self.assertEqual(call.await_count, 2)

    async def test_lazy_429_retries_before_first_chunk_only(self):
        closed = []
        async def failed():
            try:
                raise error(429)
                yield
            finally:
                closed.append(True)
        async def success():
            yield 'first'
            yield 'last'
        factory = AsyncMock(return_value=success())
        result = [x async for x in self.pipe._retry_stream_start(failed(), factory)]
        self.assertEqual(result, ['first', 'last'])
        self.assertEqual(closed, [True])
        factory.assert_awaited_once()

    async def test_partial_stream_never_replayed(self):
        async def partial():
            yield 'visible'
            raise error(429)
        factory = AsyncMock()
        result = []
        with self.assertRaises(ClientError):
            async for item in self.pipe._retry_stream_start(partial(), factory):
                result.append(item)
        self.assertEqual(result, ['visible'])
        factory.assert_not_awaited()
        self.sleep.assert_not_awaited()

    async def test_factory_and_lazy_failures_share_retry_budget(self):
        async def failed():
            raise error(429)
            yield
        factory = AsyncMock(side_effect=[error(429), failed(), failed()])
        state = {'count': 0}
        iterator = await self.pipe._retry_with_backoff(factory, _retry_state=state)
        with self.assertRaises(ClientError):
            _ = [x async for x in self.pipe._retry_stream_start(iterator, factory, state)]
        self.assertEqual(factory.await_count, 3)
        self.assertEqual(self.sleep.await_count, 2)


class RetryPipelineTests(unittest.IsolatedAsyncioTestCase):
    setUp = helpers.GeminiFullPipelineTests.setUp
    asyncTearDown = helpers.GeminiFullPipelineTests.asyncTearDown
    response = helpers.GeminiFullPipelineTests.response
    tool_response = helpers.GeminiFullPipelineTests.tool_response

    async def test_text_429_recovers_for_both_models(self):
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe._get_client = lambda: self.client
        for model in ('gemini-4-neon', 'gemini-4-hydrogen'):
            call = AsyncMock(side_effect=[error(429), self.response('완료')])
            with patch.object(self.client.aio.models, 'generate_content', call), patch.object(asyncio, 'sleep', AsyncMock()):
                result = await self.pipe.pipe({'model': model, 'stream': False,
                    'messages': [{'role': 'user', 'content': '안녕'}]})
            self.assertIn('완료', str(result))
            self.assertEqual(call.await_count, 2)

    async def test_image_tool_is_not_replayed_after_later_429(self):
        http = AsyncMock(side_effect=[self.tool_response(), error(429)])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model': 'gemini-4-neon', 'stream': True,
                'messages': [{'role': 'user', 'content': '고양이를 그려줘'}]}, __event_emitter__=AsyncMock())
        self.image_api.assert_awaited_once()
        self.assertEqual(http.await_count, 2)
        self.assertIn('429', str(result))

    async def test_stream_pipeline_recovers_lazy_429_without_duplicate_text(self):
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe._get_client = lambda: self.client
        async def failed():
            raise error(429)
            yield
        async def success():
            yield self.response('완료')
        call = AsyncMock(side_effect=[failed(), success()])
        with patch.object(self.client.aio.models, 'generate_content_stream', call), patch.object(asyncio, 'sleep', AsyncMock()):
            result = await self.pipe.pipe({'model': 'gemini-4-neon', 'stream': True,
                'messages': [{'role': 'user', 'content': '안녕'}]})
            chunks = [part async for part in result]
        self.assertEqual([part for part in chunks if isinstance(part, str)], ['완료'])
        self.assertEqual(call.await_count, 2)
