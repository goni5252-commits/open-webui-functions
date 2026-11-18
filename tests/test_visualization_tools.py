"""OpenWebUI 0.13.4 renders visualizations from completed call/result pairs."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from test_responses import m, completed, decision


class VisualizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_visualization_survives_streaming_and_nonstream_finalization(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                pipe = m.Pipe()
                pipe.valves.PERSIST_TOOL_RESULTS = False
                pipe.send_openai_responses_nonstreaming_request = AsyncMock(
                    return_value=completed(json.dumps(decision())))
                args = {'title': '도시 인구', 'html': '<svg><text>도시</text></svg>', 'libraries': []}
                call = {'type': 'function_call', 'id': 'fc1', 'call_id': 'c1',
                        'name': 'render_visualization', 'arguments': json.dumps(args)}
                render = AsyncMock(return_value={'status': 'accepted'})
                tools = {'render_visualization': {
                    'type': 'builtin', 'tool_id': 'builtin:render_visualization',
                    'callable': render, 'spec': {'name': 'render_visualization',
                    'parameters': {'type': 'object', 'properties': {}}}}}
                requests = []

                async def api(body, *unused, **kwargs):
                    requests.append(json.loads(json.dumps(body)))
                    if len(requests) == 1:
                        yield {'type': 'response.output_item.done', 'item': call}
                        response = {'status': 'completed', 'output': [call]}
                    else:
                        response = completed('그래프 설명')
                    yield {'type': 'response.completed', 'response': response}

                pipe.send_openai_responses_streaming_request = api
                emitter = AsyncMock()
                with patch.object(m, '_terminal_helper', return_value=None):
                    result = await pipe.pipe(
                        {'model': 'openai_responses.gpt-6-auto', 'stream': stream,
                         'messages': [{'role': 'user', 'content': '세계 10대 도시 시각화'}]},
                        {'id': 'u'}, None, emitter, None, {}, tools)
                render.assert_awaited_once_with(**args)
                payload = result['response'] if stream else result
                output = payload['output']
                self.assertEqual(json.loads(output[0]['arguments']), args)
                self.assertEqual(output[0]['call_id'], output[1]['call_id'])
                self.assertEqual(output[1]['status'], 'completed')
                self.assertEqual(json.loads(output[1]['output'][0]['text']), {'status': 'accepted'})
                self.assertEqual(output[-1]['content'][0]['text'], '그래프 설명')
                self.assertTrue(any(c.args[0].get('data', {}).get('output') for c in emitter.call_args_list))
                wire = requests[1]['input'][-1]
                self.assertEqual(wire['type'], 'function_call_output')
                self.assertEqual(json.loads(wire['output']), {'status': 'accepted'})
                self.assertNotIn('embeds', wire)

    async def test_processor_signatures_preserve_embeds_and_context(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                seen = []
                async def current(request, name, result, tool_type, metadata=None, user=None):
                    seen.append((metadata, user))
                    return 'visible', [], ['<svg/>']
                async def old(request, name, result, tool_type, direct_tool=False, metadata=None, user=None):
                    self.assertTrue(direct_tool)
                    return await current(request, name, result, tool_type, metadata, user)
                bridge = m._TerminalBridge(AsyncMock(), {
                    '__metadata__': {'chat_id': 'c'}, '__user__': {'id': 'u'},
                    '__event_call__': AsyncMock(return_value='html')})
                processor = old if legacy else current
                with patch.object(m, '_terminal_helper', side_effect=lambda mod, name:
                                  processor if name == 'process_tool_result' else None):
                    result = await bridge.execute(
                        {'name': 'chart', 'arguments': '{}', 'call_id': 'c1'},
                        {'type': 'external', 'direct': True})
                self.assertEqual(result, 'visible')
                self.assertEqual(seen, [({'chat_id': 'c'}, {'id': 'u'})])
                self.assertEqual(bridge.output[1]['embeds'], ['<svg/>'])

    async def test_rejected_visualization_is_not_reported_as_accepted(self):
        bridge = m._TerminalBridge(AsyncMock(), {})
        with patch.object(m, '_terminal_helper', return_value=None):
            result = await bridge.execute(
                {'name': 'render_visualization', 'arguments': '{}', 'call_id': 'c1'},
                {'type': 'builtin', 'callable': AsyncMock(return_value={'error': 'invalid html'})})
        self.assertEqual(json.loads(result), {'error': 'invalid html'})
        self.assertNotIn('accepted', bridge.output[1]['output'][0]['text'])

    async def test_workspace_display_file_keeps_its_own_arguments(self):
        emit = AsyncMock()
        bridge = m._TerminalBridge(emit, {})
        fn = AsyncMock(return_value='ok')
        with patch.object(m, '_terminal_helper', return_value=None):
            await bridge.execute({'name': 'display_file', 'call_id': 'c',
                                  'arguments': '{"inline":true,"page":2}'},
                                 {'type': 'workspace', 'callable': fn})
        fn.assert_awaited_once_with(inline=True, page=2)
        emit.assert_not_awaited()

    def test_persistence_marker_has_its_own_markdown_paragraph(self):
        marker = m.create_marker('function_call')
        text = '설명' + m.wrap_marker(marker) + '다음 설명'
        self.assertIn('\n\n[' + marker + ']: #\n\n', text)
        self.assertEqual(m.extract_markers(text), [marker])
