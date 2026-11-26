"""Tool lifecycle evidence, redaction and SDK round configuration, offline."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock
from test_conversation_images import Gemini
from test_gemini_latency import pipe

Bridge = Gemini.pipe.__globals__['_TerminalBridge']


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self, result='{"exit_code": 0}', **kwargs):
        emitter = AsyncMock()
        bridge = Bridge(emitter, {}, progress=True, diagnostics=True)
        bridge._execute = AsyncMock(return_value=result, **kwargs)
        return bridge, emitter

    def call(self):
        return {'name': 'run_command', 'arguments': json.dumps({
            'command': 'python attribution_guard.py --key SECRET_TOKEN'}), 'call_id': 'x'}

    async def test_lifecycle_contains_evidence_without_payloads(self):
        bridge, emitter = self.bridge('{"exit_code": 3, "stderr": "SECRET_OUTPUT"}')
        with self.assertLogs('google_ai.pipe.tools', level='INFO') as logs:
            result = await bridge.execute(self.call(), {})
        self.assertIn('SECRET_OUTPUT', result)  # Preserve tool evidence for the caller.
        events = [x.args[0] for x in emitter.await_args_list]
        self.assertEqual([x['data']['done'] for x in events], [False, True])
        self.assertIn('무결성 검사', events[0]['data']['description'])
        self.assertIn('실패', events[-1]['data']['description'])
        self.assertIn('종료 코드 3', events[-1]['data']['description'])
        visible = str(events) + str(logs.output)
        self.assertNotIn('SECRET_TOKEN', visible)
        self.assertNotIn('SECRET_OUTPUT', visible)
        self.assertIn(bridge.trace_id, visible)
        bridge._execute.assert_awaited_once()

    async def test_exception_is_visible_and_not_retried(self):
        bridge, emitter = self.bridge(side_effect=RuntimeError('SECRET_ERROR'))
        with self.assertLogs('google_ai.pipe.tools', level='INFO') as logs:
            with self.assertRaises(RuntimeError):
                await bridge.execute(self.call(), {})
        self.assertIn('RuntimeError', emitter.await_args_list[-1].args[0]['data']['description'])
        self.assertNotIn('SECRET_ERROR', str(logs.output))
        bridge._execute.assert_awaited_once()

    async def test_cancellation_is_propagated(self):
        bridge, emitter = self.bridge(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await bridge.execute(self.call(), {})
        self.assertIn('취소', emitter.await_args_list[-1].args[0]['data']['description'])

    async def test_status_transport_failure_does_not_repeat_tool(self):
        bridge, emitter = self.bridge()
        emitter.side_effect = RuntimeError('UI disconnected')
        await bridge.execute(self.call(), {})
        bridge._execute.assert_awaited_once()

    async def test_opt_out_and_request_local_counters(self):
        a, b = Bridge(None, {}), Bridge(None, {})
        self.assertNotEqual(a.trace_id, b.trace_id)
        a._execute = AsyncMock(return_value={'ok': True})
        await a.execute(self.call(), {})
        self.assertEqual(a.tool_count, 1)
        self.assertEqual(b.tool_count, 0)

    def test_round_limit_applies_only_to_callable_config(self):
        p = pipe()
        p.valves.AUTO_GOOGLE_SEARCH = False
        p.valves.NATIVE_TOOL_MAX_ROUNDS = 37
        tool = {'type': 'terminal', 'callable': AsyncMock(), 'spec': {
            'name': 'run_command', 'parameters': {'type': 'object', 'properties': {}}}}
        config = p._configure_generation({}, '', {}, {'run_command': tool}, model_id='gemini-4-hydrogen')
        self.assertEqual(config.automatic_function_calling.maximum_remote_calls, 37)
        config = p._configure_generation({}, '', {}, {}, model_id='gemini-4-hydrogen')
        self.assertIsNone(config.automatic_function_calling)
