"""Visual review selection and AFC exhaustion with real SDK, no external calls."""
import unittest
from unittest.mock import AsyncMock, patch
import test_conversation_images as helpers
from test_gemini_latency import body


class ToolCompletionTests(unittest.IsolatedAsyncioTestCase):
    setUp = helpers.GeminiFullPipelineTests.setUp
    asyncTearDown = helpers.GeminiFullPipelineTests.asyncTearDown
    response = helpers.GeminiFullPipelineTests.response

    def terminal(self, kind='terminal'):
        call = AsyncMock(return_value={'stdout': 'verified'})
        return call, {'run_command': {'type': kind, 'callable': call,
            'spec': {'name': 'run_command', 'description': 'Run a command', 'parameters': {
                'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}}

    async def test_screenshot_review_omits_terminal_and_streams(self):
        call, tools = self.terminal()
        streaming = AsyncMock(return_value=object())
        self.pipe._handle_streaming_response = lambda iterator, *a, **kw: iterator
        with patch.object(self.client.aio.models, 'generate_content_stream', streaming), patch.object(
                self.client.aio.models, 'generate_content', AsyncMock()) as nonstream:
            await self.pipe.pipe(body('문제 오류 및 타당성 검토 부탁'), __tools__=tools)
        nonstream.assert_not_awaited()
        self.assertFalse(any(callable(t) for t in streaming.call_args.kwargs['config'].tools or []))
        call.assert_not_awaited()
        self.assertNotIn('_terminal_bridge', tools['run_command'])

    def test_explicit_operations_workspace_and_opt_out_remain_available(self):
        _, tools = self.terminal()
        for text in ('문제 검토 후 PDF 파일로 만들어줘', '문제 오류를 Python으로 검토해줘', '코드를 실행해서 검토해줘'):
            config = self.pipe._configure_generation(body(text), None, {}, tools, model_id='gemini-3.8-flash')
            self.assertTrue(any(callable(t) for t in config.tools or []), text)
        _, workspace = self.terminal('workspace')
        config = self.pipe._configure_generation(body('문제 오류 및 타당성 검토 부탁'), None, {}, workspace, model_id='gemini-3.8-flash')
        self.assertTrue(any(callable(t) for t in config.tools or []))
        self.pipe.valves.SMART_TERMINAL_SELECTION = False
        config = self.pipe._configure_generation(body('문제 오류 및 타당성 검토 부탁'), None, {}, tools, model_id='gemini-3.8-flash')
        self.assertTrue(any(callable(t) for t in config.tools or []))

    def pending(self, name='run_command'):
        t = self.types
        return t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model', parts=[
            t.Part(text='Unrelated Python cURL plan', thought=True),
            t.Part(function_call=t.FunctionCall(name=name, args={'command': 'echo test'}, id='pending-id'),
                   thought_signature=b'preserved-signature')]))])

    async def test_afc_round_limit_finalizes_once_without_replaying_tool(self):
        call, tools = self.terminal('workspace')
        original = self.pipe._configure_generation
        def limited(*args, **kwargs):
            result = original(*args, **kwargs)
            result.automatic_function_calling = self.types.AutomaticFunctionCallingConfig(maximum_remote_calls=2)
            return result
        self.pipe._configure_generation = limited
        http = AsyncMock(side_effect=[self.pending(), self.pending(), self.response('검토 결과입니다.')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe(body('Python으로 검토해줘'), __tools__=tools)
        self.assertEqual(result, '검토 결과입니다.')
        self.assertEqual(http.await_count, 3)
        call.assert_awaited_once_with(command='echo test')
        final = http.call_args.kwargs
        self.assertIsNone(final['config'].tools)
        self.assertTrue(final['config'].automatic_function_calling.disable)
        self.assertEqual(final['config'].http_options.retry_options.attempts, 1)
        contents = final['contents']
        self.assertEqual(contents[-2].parts[-1].thought_signature, b'preserved-signature')
        self.assertFalse(contents[-1].parts[0].function_response.response['executed'])
        self.assertEqual(contents[-1].parts[0].function_response.id, 'pending-id')
        self.assertTrue(any(getattr(p, 'function_response', None) and 'stdout' in str(p.function_response.response)
            for c in contents[:-2] for p in getattr(c, 'parts', [])))

    async def test_finalization_failure_does_not_retry_or_show_unfinished_thoughts(self):
        _, tools = self.terminal('workspace')
        pending = self.pending('unknown_tool')
        generate = AsyncMock(side_effect=[pending, RuntimeError('network unavailable')])
        with patch.object(self.client.aio.models, 'generate_content', generate):
            result = await self.pipe.pipe(body('Python으로 검토해줘'), __tools__=tools)
        self.assertEqual(generate.await_count, 2)
        self.assertIn('최종 답변을 만들지 못했습니다', result)
        self.assertNotIn('Unrelated Python', result)
        self.assertNotIn('thought summary', result)

    async def test_repeated_pending_response_stops_after_one_finalization(self):
        _, tools = self.terminal('workspace')
        generate = AsyncMock(return_value=self.pending())
        with patch.object(self.client.aio.models, 'generate_content', generate):
            result = await self.pipe.pipe(body('Python으로 검토해줘'), __tools__=tools)
        self.assertEqual(generate.await_count, 2)
        self.assertIn('최종 답변을 만들지 못했습니다', result)

    async def test_normal_response_needs_no_extra_call(self):
        generate = AsyncMock(return_value=self.response('정상 답변'))
        b = body('문제 오류 검토')
        b['stream'] = False
        with patch.object(self.client.aio.models, 'generate_content', generate):
            result = await self.pipe.pipe(b)
        self.assertEqual(result, '정상 답변')
        generate.assert_awaited_once()
