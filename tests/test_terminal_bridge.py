"""Offline regression checks for v1.7.3/1.7.4 terminal output transport."""
import json
import unittest
from types import MappingProxyType
from unittest.mock import patch

from test_responses import m


class TerminalBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mapping_headers_and_renderer_output_survive_finalization(self):
        events = []

        async def emit(event):
            events.append(event)

        async def display_file(path):
            return ({'path': path, 'exists': True}, MappingProxyType({'Content-Type': 'application/json'}))

        bridge = m._TerminalBridge(emit, {'__metadata__': {'chat_id': 'test-chat'}})
        call = {'name': 'display_file', 'arguments': json.dumps({'path': '/tmp/report.txt'}), 'call_id': 'call-1'}
        tool = {'type': 'terminal', 'tool_id': 'terminal:test', 'callable': display_file}
        with patch.object(m, '_terminal_helper', return_value=None):
            result = await bridge.execute(call, tool)
        self.assertIsInstance(result, str)
        self.assertEqual(json.loads(result)['path'], '/tmp/report.txt')
        output = bridge.output[1]
        self.assertEqual(output['output'], [{'type': 'input_text', 'text': result}])
        self.assertTrue(any(event['type'] == 'terminal:display_file' for event in events))
        for stream in (True, False):
            final = bridge.final_response('Done', {'stream': stream, 'model': 'test'})
            payload = final['response'] if stream else final
            self.assertEqual(payload['output'][1], output)
            self.assertEqual(payload['output'][-1]['content'][0]['text'], 'Done')

    async def test_failed_file_result_does_not_create_card_or_refresh(self):
        events = []

        async def emit(event):
            events.append(event)

        async def display_file(path):
            return ({'path': path, 'exists': False}, MappingProxyType({}))

        bridge = m._TerminalBridge(emit, {})
        with patch.object(m, '_terminal_helper', return_value=None):
            result = await bridge.execute(
                {'name': 'display_file', 'arguments': '{"path":"/tmp/missing"}', 'call_id': 'call-2'},
                {'type': 'terminal', 'tool_id': 'terminal:test', 'callable': display_file},
            )
        self.assertFalse(json.loads(result)['exists'])
        self.assertEqual(bridge.output, [])
        self.assertEqual(events, [])
