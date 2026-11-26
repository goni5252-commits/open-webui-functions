"""Request text compatibility and observable execution without logging file contents."""
import unittest
from unittest.mock import AsyncMock, patch
from test_responses import m


class RequestContextTests(unittest.TestCase):
    def test_current_prompt_wins_over_stale_legacy_prompt_and_retrieval(self):
        metadata = {'base_user_prompt': 'test.txt를 만들어줘', 'user_prompt': '학교명을 바꿔줘'}
        self.assertEqual(m._original_user_prompt(metadata, [{'role': 'user', 'content': 'retrieved document'}]),
                         'test.txt를 만들어줘')

    def test_legacy_and_message_fallback(self):
        self.assertEqual(m._original_user_prompt({'user_prompt': 'legacy'}, []), 'legacy')
        self.assertEqual(m._original_user_prompt({'base_user_prompt': None},
                         [{'role': 'user', 'content': [{'type': 'text', 'text': 'latest'}]}]), 'latest')


class ExecutionDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_evidence_excludes_arguments_and_result(self):
        fn = AsyncMock(return_value='private file contents')
        call = {'name': 'run_command', 'call_id': 'c', 'arguments': '{"command":"private command"}'}
        with self.assertLogs(m.__name__, level='INFO') as logs:
            result = await m.Pipe._execute_function_calls([call], {'run_command': {'callable': fn}})
        fn.assert_awaited_once_with(command='private command')
        text = '\n'.join(logs.output)
        self.assertIn('Tool execution started: run_command', text)
        self.assertIn('Tool execution returned: run_command', text)
        self.assertNotIn('private', text)
        self.assertEqual(result[0]['output'], 'private file contents')

    async def test_exception_is_not_logged_as_returned(self):
        fn = AsyncMock(side_effect=RuntimeError('private upstream detail'))
        with self.assertLogs(m.__name__, level='INFO') as logs:
            with self.assertRaises(RuntimeError):
                await m.Pipe._execute_function_calls(
                    [{'name': 'run_command', 'call_id': 'c', 'arguments': '{}'}],
                    {'run_command': {'callable': fn}})
        text = '\n'.join(logs.output)
        self.assertIn('Tool execution raised: run_command (RuntimeError)', text)
        self.assertNotIn('returned', text)
        self.assertNotIn('private', text)

    async def test_display_failure_is_observable_without_duplicate_execution(self):
        fn = AsyncMock(return_value={'exists': False, 'path': '/private/report.txt'})
        bridge = m._TerminalBridge(AsyncMock(), {})
        with patch.object(m, '_terminal_helper', return_value=None), self.assertLogs(m.__name__, level='INFO') as logs:
            await bridge.execute({'name': 'display_file', 'call_id': 'c', 'arguments': '{"path":"/private/report.txt"}'},
                                 {'type': 'terminal', 'tool_id': 'machine:one', 'callable': fn})
        fn.assert_awaited_once()
        self.assertIn('failed=True structured=False', '\n'.join(logs.output))
        self.assertNotIn('/private', '\n'.join(logs.output))
        self.assertEqual(bridge.output, [])
