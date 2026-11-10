"""Offline tests with real httpx transport and Pydantic; no provider requests."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx

spec = importlib.util.spec_from_file_location('exaone_auto', Path(__file__).resolve().parents[1] / 'functions/exaone_auto.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REAL_CLIENT = httpx.AsyncClient


def completion(text, reason='stop'):
    return {'choices': [{'message': {'content': text, 'reasoning_content': 'private reasoning'}, 'finish_reason': reason}]}


class ExaoneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = module.Pipe()
        self.pipe.valves.EXAONE_API_KEY = 'test-secret'
        self.body = {'model': 'renamed.k-exaone-auto', 'stream': True, 'messages': [{'role': 'user', 'content': '설명해줘'}]}
        self.calls = []
        self.events = []

    async def invoke(self, responses, **kwargs):
        async def handler(request):
            self.calls.append(json.loads(request.content))
            self.assertEqual(str(request.url), module.ENDPOINT)
            self.assertEqual(request.headers['Authorization'], 'Bearer test-secret')
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if isinstance(response, int):
                return httpx.Response(response, text='test-secret private upstream error')
            return httpx.Response(200, json=response)
        async def emit(event):
            self.events.append(event)
        with patch.object(module.httpx, 'AsyncClient', side_effect=lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw)):
            return await self.pipe.pipe(self.body, __event_emitter__=emit, **kwargs)

    async def test_auto_levels_and_payload(self):
        for level in ('low', 'high', 'max'):
            self.calls.clear()
            before = copy.deepcopy(self.body)
            answer = await self.invoke([completion(level), completion('\n\n답변')])
            self.assertEqual(answer, '답변')
            self.assertEqual(self.body, before)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(self.calls[0]['reasoning_effort'], 'low')
            payload = self.calls[1]
            self.assertEqual(payload['reasoning_effort'], level)
            self.assertEqual(payload['model'], 'k-exaone_v2.5')
            self.assertFalse(payload['stream'])
            self.assertNotIn('tools', payload)
            self.assertEqual(payload['messages'], self.body['messages'])
            self.assertTrue(self.events[-1]['data']['done'])

    async def test_invalid_and_truncated_classifier_fallback(self):
        for response in (completion('medium'), completion('max', 'length'), {}, completion('HIGH'), completion('')):
            self.calls.clear()
            await self.invoke([response, completion('ok')])
            self.assertEqual(self.calls[1]['reasoning_effort'], 'high')

    async def test_router_timeout_fallback(self):
        await self.invoke([httpx.ReadTimeout('secret'), completion('ok')])
        self.assertEqual(self.calls[1]['reasoning_effort'], 'high')

    async def test_fixed_and_user_overrides(self):
        for user in ({'valves': {'REASONING_EFFORT': 'max'}}, {'valves': module.Pipe.UserValves(REASONING_EFFORT='max')}):
            self.calls.clear()
            await self.invoke([completion('ok')], __user__=user)
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.calls[0]['reasoning_effort'], 'max')
        self.pipe.valves.REASONING_EFFORT = 'low'
        await self.invoke([completion('ok')])
        self.assertEqual(self.calls[-1]['reasoning_effort'], 'low')

    async def test_background_task_skips_router_and_status(self):
        await self.invoke([completion('title')], __task__='title_generation')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['reasoning_effort'], 'low')
        self.assertFalse(self.events)

    async def test_unsupported_input_prevents_http(self):
        cases = [
            {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'secret'}}]}]},
            {'messages': [{'role': 'tool', 'content': 'result'}]},
            {'messages': [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': '1'}]}]},
            {'messages': []},
            {**self.body, 'files': [{'id': '1'}]},
        ]
        for body in cases:
            self.body = body
            with self.assertRaises(ValueError):
                await self.invoke([])
        self.assertEqual(self.calls, [])

    async def test_text_parts_and_full_answer_history(self):
        self.body['messages'] = [{'role': 'system', 'content': 'system instructions'}, {'role': 'user', 'content': 'a' * 9000}, {'role': 'assistant', 'content': 'prior'}, {'role': 'user', 'content': [{'type': 'text', 'text': 'follow-up'}]}]
        await self.invoke([completion('high'), completion('ok')])
        context = json.loads(self.calls[0]['messages'][1]['content'])
        self.assertEqual(len(context[0]['content']), 4000)
        self.assertEqual(len(self.calls[1]['messages'][1]['content']), 9000)
        self.assertEqual(self.calls[1]['messages'][-1]['content'], 'follow-up')

    async def test_http_errors_no_retry_or_secret(self):
        for code in (400, 401, 403, 429, 500):
            self.calls.clear()
            with self.assertRaises(ValueError) as error:
                await self.invoke([code])
            self.assertIn(str(code), str(error.exception))
            self.assertNotIn('test-secret', str(error.exception))
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(self.events[-1]['data']['done'])

    async def test_final_timeout_and_incomplete_output(self):
        self.pipe.valves.REASONING_EFFORT = 'high'
        for response in (completion('partial', 'length'), completion(''), {}, completion('refusal', 'content_filter'), httpx.ReadTimeout('test-secret')):
            with self.assertRaises(ValueError) as error:
                await self.invoke([response])
            self.assertNotIn('test-secret', str(error.exception))

    async def test_missing_key_and_env_key(self):
        self.pipe.valves.EXAONE_API_KEY = ''
        with patch.dict(module.os.environ, {'EXAONE_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'API 키'):
                await self.invoke([])
        with patch.dict(module.os.environ, {'EXAONE_API_KEY': 'test-secret'}):
            await self.invoke([completion('low'), completion('ok')])

    async def test_event_failure_does_not_discard_answer(self):
        async def broken(event):
            raise RuntimeError('closed UI')
        with patch.object(self.pipe, '_post', return_value=completion('ok')):
            self.pipe.valves.REASONING_EFFORT = 'high'
            self.assertEqual(await self.pipe.pipe(self.body, __event_emitter__=broken), 'ok')

    async def test_cancellation_propagates(self):
        with patch.object(self.pipe, '_post', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.pipe.pipe(self.body)


if __name__ == '__main__':
    unittest.main()
