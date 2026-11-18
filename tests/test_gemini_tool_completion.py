"""Visual review selection and AFC exhaustion with real SDK, no external calls."""
import unittest
import json
from unittest.mock import AsyncMock, patch
import test_conversation_images as helpers
from test_gemini_latency import body


class ToolCompletionTests(unittest.IsolatedAsyncioTestCase):
    setUp = helpers.GeminiFullPipelineTests.setUp
    asyncTearDown = helpers.GeminiFullPipelineTests.asyncTearDown
    response = helpers.GeminiFullPipelineTests.response

    async def test_visualization_sdk_call_survives_both_final_response_modes(self):
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe.valves.AUTO_GOOGLE_SEARCH = False
        self.pipe._get_client = lambda: self.client
        args = {'title': '세계 도시', 'html': '<svg><text>도시 인구</text></svg>', 'libraries': ['chartjs']}
        render = AsyncMock(return_value={'status': 'accepted'})
        tools = {'render_visualization': {'type': 'builtin', 'tool_id': 'builtin:render_visualization',
            'callable': render, 'spec': {'name': 'render_visualization', 'description': 'Render a visualization',
            'parameters': {'type': 'object', 'properties': {
                'title': {'type': 'string'}, 'html': {'type': 'string'},
                'libraries': {'type': 'array', 'items': {'type': 'string', 'enum': ['chartjs']}}},
                'required': ['title', 'html']}}}}
        t = self.types
        response = t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model', parts=[
            t.Part(function_call=t.FunctionCall(name='render_visualization', args=args),
                   thought_signature=b'visualization-signature')]))])
        for stream in (True, False):
            with self.subTest(stream=stream):
                render.reset_mock()
                http = AsyncMock(side_effect=[response, self.response('도시 인구 그래프입니다.')])
                emitter = AsyncMock()
                with patch.object(self.client.aio.models, '_generate_content', http), patch.dict(
                        helpers.Gemini.pipe.__globals__, {'_terminal_helper': lambda *a: None}):
                    result = await self.pipe.pipe(
                        {'model': 'gemini-4-hydrogen', 'stream': stream,
                         'messages': [{'role': 'user', 'content': '세계 10대 도시를 시각화해줘'}]},
                        __tools__=tools, __event_emitter__=emitter)
                render.assert_awaited_once_with(**args)
                self.assertEqual(http.await_count, 2)
                payload = result['response'] if stream else result
                output = payload['output']
                self.assertEqual(json.loads(output[0]['arguments']), args)
                self.assertEqual(output[0]['name'], 'render_visualization')
                self.assertEqual(output[0]['call_id'], output[1]['call_id'])
                self.assertEqual(output[1]['status'], 'completed')
                self.assertEqual(json.loads(output[1]['output'][0]['text']), {'status': 'accepted'})
                self.assertIn('도시 인구 그래프입니다.', output[-1]['content'][0]['text'])
                self.assertTrue(any(c.args[0].get('data', {}).get('output') for c in emitter.call_args_list))
                contents = http.call_args.kwargs['contents']
                responses = [p.function_response.response for c in contents for p in c.parts
                             if p.function_response]
                self.assertEqual(json.loads(responses[-1]['result']), {'status': 'accepted'})
                self.assertNotIn('_terminal_bridge', tools['render_visualization'])

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
        for text in ('문제 검토 후 PDF 파일로 만들어줘', '문제 검토 후 한글파일 만들어줘', '문제 오류를 Python으로 검토해줘', '코드를 실행해서 검토해줘'):
            config = self.pipe._configure_generation(body(text), None, {}, tools, model_id='gemini-3.8-flash')
            self.assertTrue(any(callable(t) for t in config.tools or []), text)
        _, workspace = self.terminal('workspace')
        config = self.pipe._configure_generation(body('문제 오류 및 타당성 검토 부탁'), None, {}, workspace, model_id='gemini-3.8-flash')
        self.assertTrue(any(callable(t) for t in config.tools or []))
        self.pipe.valves.SMART_TERMINAL_SELECTION = False
        config = self.pipe._configure_generation(body('문제 오류 및 타당성 검토 부탁'), None, {}, tools, model_id='gemini-3.8-flash')
        self.assertTrue(any(callable(t) for t in config.tools or []))

    async def test_search_then_direct_terminal_returns_hwpx_card(self):
        b = body('최신 자료를 검토하고 한글 파일 만들어줘')
        tools = {'display_file': {'direct': True, 'type': 'terminal', 'tool_id': 'terminal:one',
            'spec': {'name': 'display_file', 'description': 'Display a generated file',
                     'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}},
                                    'required': ['path']}}}}
        event_call = AsyncMock(return_value={'path': '보고서.hwpx', 'exists': True})
        t = self.types
        display = t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model', parts=[
            t.Part(function_call=t.FunctionCall(name='display_file', args={'path': '보고서.hwpx'}))]))])
        http = AsyncMock(side_effect=[self.response('검색 자료'), display, self.response('완료')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe(b, __tools__=tools, __event_call__=event_call)
        event_call.assert_awaited_once()
        self.assertEqual(event_call.call_args.args[0]['data']['params'], {'path': '보고서.hwpx'})
        self.assertIn('보고서.hwpx', result['response']['output'][1]['output'][0]['text'])
        self.assertIn('kordoc', http.call_args.kwargs['config'].system_instruction)
        self.assertEqual(http.await_count, 3)

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
