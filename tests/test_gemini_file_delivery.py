"""Offline Gemini SDK delivery, deduplication and failure evidence regressions."""
import ast
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_conversation_images as helpers


class GeminiFileDeliveryTests(unittest.IsolatedAsyncioTestCase):
    setUp = helpers.GeminiFullPipelineTests.setUp
    asyncTearDown = helpers.GeminiFullPipelineTests.asyncTearDown
    response = helpers.GeminiFullPipelineTests.response

    def test_bridges_keep_same_delivery_contract(self):
        root = Path(__file__).resolve().parents[1]
        trees = []
        for name in ('google_gemini', 'openai_responses'):
            tree = ast.parse((root / 'functions' / (name + '.py')).read_text())
            trees.append([ast.dump(n) for n in tree.body
                          if getattr(n, 'name', '') in ('_TerminalBridge', '_is_terminal_tool')])
        self.assertEqual(*trees)

    async def test_missing_delivery_recovers_without_replaying_creation(self):
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe.valves.AUTO_GOOGLE_SEARCH = False
        self.pipe.valves.NATIVE_TOOL_STREAMING_SAFE_MODE = False
        self.pipe._get_client = lambda: self.client
        t = self.types
        def call(name, args):
            return t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model', parts=[
                t.Part(function_call=t.FunctionCall(name=name, args=args), thought_signature=b'signed')]))])
        for stream in (False, True):
            create = AsyncMock(return_value={'stdout': 'Verified final output /tmp/final.hwpx'})
            display = AsyncMock(return_value={'path': '/tmp/final.hwpx', 'exists': True})
            tools = {}
            for name, fn, param in [('run_command', create, 'command'), ('display_file', display, 'path')]:
                tools[name] = {'type': 'terminal', 'tool_id': 'machine:one', 'callable': fn,
                    'spec': {'name': name, 'description': name, 'parameters': {'type': 'object',
                    'properties': {param: {'type': 'string'}}, 'required': [param]}}}
            http = AsyncMock(side_effect=[call('run_command', {'command': 'generate once'}),
                self.response('Created'), call('deliver_terminal_files', {'paths': ['/tmp/final.hwpx']}),
                self.response('Delivered')])
            with patch.object(self.client.aio.models, '_generate_content', http), patch.dict(
                    helpers.Gemini.pipe.__globals__, {'_terminal_helper': lambda *a: None}):
                result = await self.pipe.pipe({'model': 'gemini-4-hydrogen', 'stream': stream,
                    'messages': [{'role': 'user', 'content': 'Create a document file'}]}, __tools__=tools,
                    __event_emitter__=AsyncMock())
            create.assert_awaited_once()
            display.assert_awaited_once_with(path='/tmp/final.hwpx')
            payload = result['response'] if stream else result
            self.assertEqual(len(payload['output']), 3)
            self.assertEqual(http.await_count, 4)
            recovery = http.call_args_list[2].kwargs
            self.assertEqual(recovery['config'].tool_config.function_calling_config.mode, 'ANY')
            self.assertEqual(len(recovery['config'].tools), 1)
            self.assertIsNone(http.call_args_list[3].kwargs['config'].tools)
            self.assertNotIn('deliver_terminal_files', tools)

    async def test_duplicate_cards_and_missing_path_evidence(self):
        ns = helpers.Gemini.pipe.__globals__
        bridge = ns['_TerminalBridge'](AsyncMock(), {'__metadata__': {'machine_id': 'one'}})
        fn = AsyncMock(side_effect=[{'path': '/tmp/report.hwpx', 'exists': True},
                                   {'path': '/tmp/report.hwpx', 'exists': True},
                                   {'path': '/resolved/missing.hwpx', 'exists': False}])
        bridge.delivery_tools({'display_file': {'type': 'machine', 'tool_id': 'machine:one', 'callable': fn}})
        with patch.dict(ns, {'_terminal_helper': lambda *a: None}):
            await bridge.deliver_files(['/tmp/report.hwpx'])
            await bridge.deliver_files(['/tmp/report.hwpx'])
            result = json.loads(await bridge.deliver_files(['/tmp/missing.hwpx']))
        self.assertEqual(len(bridge.output), 2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['errors'][0]['code'], 'file_not_found')
        self.assertEqual(result['errors'][0]['tool_result']['path'], '/resolved/missing.hwpx')

    async def test_inspection_or_existing_delivery_skips_recovery(self):
        ns = helpers.Gemini.pipe.__globals__
        bridge = ns['_TerminalBridge'](AsyncMock(), {})
        generate = AsyncMock()
        with patch.object(self.client.aio.models, 'generate_content', generate):
            response = self.response('Done')
            result = await self.pipe._recover_file_delivery(self.client, 'model', [], None, response, bridge)
            self.assertIs(result, response)
            bridge.terminal_work = True
            bridge.delivery_attempted = True
            await self.pipe._recover_file_delivery(self.client, 'model', [], None, response, bridge)
        generate.assert_not_awaited()
