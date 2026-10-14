"""Gemini SDK callable -> terminal result -> Pipe final output, offline."""
import inspect
import json
from types import MappingProxyType
import unittest
from unittest.mock import AsyncMock, patch
from test_conversation_images import Gemini


class GeminiTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipe(self, stream=False, exists=True, terminal=True, fail_final=False):
        pipe = object.__new__(Gemini)
        events = []
        calls = []
        async def emit(event):
            events.append(event)
        async def display_file(**kwargs):
            calls.append(kwargs)
            return ({'path': kwargs['path'], 'exists': exists}, MappingProxyType({'Content-Type': 'application/json'}))
        tool = {'callable': display_file, 'type': 'terminal' if terminal else 'workspace',
                'spec': {'name': 'display_file', 'description': 'Display a generated file',
                         'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}
        if terminal:
            tool['tool_id'] = 'terminal:test'
        async def impl(body, metadata, emitter, registry, request, user, holder):
            selected = registry['display_file']
            wrapped = pipe._named_native_tool('display_file', selected['callable'], set(), selected['spec'], selected)
            self.assertEqual(list(inspect.signature(wrapped).parameters), ['path'])
            await wrapped(path='/tmp/report.pptx')
            return 'Error generating content: unavailable' if fail_final else 'PPTX를 생성했습니다.'
        pipe._conversation_pipe_impl = impl
        ns = Gemini.pipe.__globals__
        with patch.dict(ns, {'_terminal_helper': lambda *a: None}):
            result = await pipe.pipe({'stream': stream, 'model': 'gemini-test'},
                                     {'chat_id': 'chat-1'}, emit, {'display_file': tool})
        self.assertNotIn('_terminal_bridge', tool)
        self.assertEqual(calls, [{'path': '/tmp/report.pptx'}])
        return result, events

    async def test_file_card_survives_both_final_response_modes(self):
        for stream in (False, True):
            result, events = await self.run_pipe(stream)
            final = result['response'] if stream else result
            output = final['output']
            card = json.loads(output[1]['output'][0]['text'])
            self.assertEqual(card['source'], 'open_terminal')
            self.assertEqual(card['terminal_selector'], 'test')
            self.assertEqual(card['session_id'], 'chat-1')
            self.assertEqual(card['name'], 'report.pptx')
            self.assertEqual(output[0]['call_id'], output[1]['call_id'])
            self.assertEqual(output[-1]['content'][0]['text'], 'PPTX를 생성했습니다.')
            self.assertTrue(any(e['type'] == 'terminal:display_file' for e in events))

    async def test_failed_file_and_workspace_names_do_not_create_terminal_cards(self):
        for args in ({'exists': False}, {'terminal': False}):
            result, events = await self.run_pipe(**args)
            self.assertIsInstance(result, str)
            self.assertEqual(events, [])

    async def test_successful_file_survives_final_model_failure(self):
        result, _ = await self.run_pipe(fail_final=True)
        self.assertEqual(len(result['output']), 3)
        self.assertIn('Error generating', result['output'][-1]['content'][0]['text'])

    async def test_spec_required_arguments_and_optional_omission(self):
        call = AsyncMock(return_value={'ok': True})
        spec = {'parameters': {'properties': {'path': {'type': 'string'}, 'page': {'type': 'integer'}}, 'required': ['path']}}
        wrapper = Gemini._named_native_tool('display_file', call, set(), spec)
        result = await wrapper()
        self.assertFalse(result['ok'])
        call.assert_not_awaited()
        await wrapper(path='file.pptx')
        call.assert_awaited_once_with(path='file.pptx')

    async def test_requests_have_distinct_call_ids(self):
        first, _ = await self.run_pipe()
        second, _ = await self.run_pipe()
        self.assertNotEqual(first['output'][0]['call_id'], second['output'][0]['call_id'])

    async def test_server_helpers_process_files_and_embeds(self):
        ns = Gemini.pipe.__globals__
        bridge = ns['_TerminalBridge'](AsyncMock(), {'__metadata__': {'chat_id': 'chat'}})
        process = AsyncMock(return_value=('download', [{'name': 'report.pptx'}], ['preview']))
        builder = lambda *a: {'type': 'file', 'source': 'open_terminal'}
        handler = AsyncMock()
        def helper(module, name):
            return {'build_terminal_file_tool_result': builder, 'process_tool_result': process,
                    'terminal_event_handler': handler}.get(name)
        with patch.dict(ns, {'_terminal_helper': helper}):
            await bridge.execute({'name': 'display_file', 'arguments': '{"path":"/tmp/report.pptx"}', 'call_id': 'a'},
                                 {'type': 'terminal', 'callable': AsyncMock(return_value={'exists': True})})
        self.assertEqual(bridge.output[1]['files'], [{'name': 'report.pptx'}])
        self.assertEqual(bridge.output[1]['embeds'], ['preview'])
        handler.assert_awaited_once()
