import json
import unittest
from unittest.mock import AsyncMock, patch
from test_responses import m, completed


class FinalFileDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self):
        self.emitter = AsyncMock()
        self.display = AsyncMock(side_effect=lambda path: {'path': path, 'full_path': path, 'exists': True})
        self.tool = {'type': 'terminal', 'tool_id': 'machine:one', 'callable': self.display}
        return m._TerminalBridge(self.emitter, {'__metadata__': {'chat_id': 'chat'}})

    async def show(self, bridge, path, call_id):
        return await bridge.execute({'name': 'display_file', 'call_id': call_id,
                                     'arguments': json.dumps({'path': path})}, self.tool)

    async def test_same_file_replaces_card_but_rechecks_file(self):
        bridge = self.bridge()
        with patch.object(m, '_terminal_helper', return_value=None):
            await self.show(bridge, '/tmp/a/../report.hwpx', 'first')
            await self.show(bridge, '/tmp/report.hwpx', 'second')
        self.assertEqual(self.display.await_count, 2)
        self.assertEqual(len(bridge.output), 2)
        self.assertEqual(bridge.output[0]['call_id'], 'second')
        self.assertEqual(bridge.output[1]['call_id'], 'second')
        events = [c.args[0] for c in self.emitter.call_args_list]
        self.assertEqual(sum(e['type'] == 'machine:display_file' for e in events), 1)
        for stream in (True, False):
            final = bridge.final_response('done', {'stream': stream})
            output = final['response']['output'] if stream else final['output']
            self.assertEqual(len(output), 3)

    async def test_different_files_and_machines_remain_distinct(self):
        bridge = self.bridge()
        with patch.object(m, '_terminal_helper', return_value=None):
            await self.show(bridge, '/tmp/a.txt', 'a')
            await self.show(bridge, '/tmp/b.txt', 'b')
            self.tool = {**self.tool, 'tool_id': 'machine:two'}
            await self.show(bridge, '/tmp/a.txt', 'c')
        self.assertEqual(len(bridge.file_cards), 3)

    async def test_delivery_failure_creates_no_success_card(self):
        bridge = self.bridge()
        bridge.delivery_tools({'display_file': self.tool})
        self.display.side_effect = lambda path: {'path': path, 'exists': False}
        with patch.object(m, '_terminal_helper', return_value=None):
            result = json.loads(await bridge.deliver_files(['/tmp/missing.txt']))
        self.assertFalse(result['ok'])
        self.assertEqual(result['delivered'], [])
        self.assertEqual(bridge.output, [])
        self.assertFalse(bridge.needs_delivery())

    async def test_only_explicit_final_paths_are_displayed(self):
        bridge = self.bridge()
        bridge.delivery_tools({'display_file': self.tool})
        with patch.object(m, '_terminal_helper', return_value=None):
            result = json.loads(await bridge.deliver_files(['/tmp/final.hwpx', '/tmp/final.hwpx']))
        self.assertTrue(result['ok'])
        self.display.assert_awaited_once_with(path='/tmp/final.hwpx')
        self.assertEqual(len(bridge.output), 2)

    async def test_missing_delivery_recovered_once_without_repeating_creation(self):
        pipe = m.Pipe()
        bridge = self.bridge()
        create = AsyncMock(return_value='created /tmp/final.txt; intermediate /tmp/build.py')
        registry = {'display_file': self.tool,
                    'run_command': {'type': 'terminal', 'tool_id': 'machine:one', 'callable': create}}
        tools = {n: {**t, '_terminal_bridge': bridge} for n, t in registry.items()}
        tools.update(bridge.delivery_tools(registry))
        seen = []
        def call(name, args, cid):
            return {'type': 'function_call', 'name': name, 'arguments': json.dumps(args), 'call_id': cid, 'id': cid}
        responses = [
            {'status': 'completed', 'output': [call('run_command', {'command': 'create final'}, 'a')]},
            completed('Created file'),
            {'status': 'completed', 'output': [call('deliver_terminal_files', {'paths': ['/tmp/final.txt']}, 'b')]},
            completed('Delivered file')]
        async def stream(payload, *args, **kwargs):
            seen.append(payload.get('tool_choice'))
            yield {'type': 'response.completed', 'response': responses[len(seen)-1]}
        pipe.send_openai_responses_streaming_request = stream
        body = m.ResponsesBody(model='gpt-6-sol', input=[{'role': 'user', 'content': 'Create a text file'}])
        with patch.object(m, '_terminal_helper', return_value=None):
            await pipe._run_streaming_loop(body, m.Pipe.Valves(PERSIST_TOOL_RESULTS=False), bridge.emit, {}, tools)
        create.assert_awaited_once()
        self.display.assert_awaited_once_with(path='/tmp/final.txt')
        self.assertEqual(seen[2], {'type': 'function', 'name': 'deliver_terminal_files'})
        self.assertIsNone(seen[3])
        self.assertEqual(len(bridge.file_cards), 1)

    async def test_no_terminal_work_needs_no_recovery(self):
        bridge = self.bridge()
        bridge.delivery_tools({'display_file': self.tool})
        self.assertFalse(bridge.needs_delivery())
        bridge.terminal_work = True
        await bridge.deliver_files([])
        self.assertFalse(bridge.needs_delivery())
        self.display.assert_not_awaited()
