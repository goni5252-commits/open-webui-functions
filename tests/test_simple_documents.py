import unittest
from unittest.mock import AsyncMock
from test_responses import m

class SimpleDocumentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_simple_keeps_terminal_but_omits_harness_with_legacy_enabled(self):
        pipe = m.Pipe()
        pipe.valves = m.Pipe.Valves(ENABLE_TERMINAL_HARNESS=True)
        pipe._pipe_impl = AsyncMock(return_value='ok')
        registry = {'run_command': {'type':'terminal','tool_id':'terminal:one'}}
        await pipe.pipe({'messages':[]},{'id':'u'},None,AsyncMock(),None,{},registry,[])
        passed = pipe._pipe_impl.call_args.args[6]
        self.assertNotIn('get_terminal_harness',passed)
        self.assertIn('_terminal_bridge',passed['run_command'])
        self.assertIn('prepare_terminal_files',passed)
        self.assertEqual(m._document_workflow_policy(pipe.valves, passed), m._SIMPLE_DOCUMENT_POLICY)

    async def test_no_terminal_background_and_advanced_gates(self):
        terminal = {'t':{'type':'terminal'}}
        vals = m.Pipe.Valves()
        self.assertEqual(m._document_workflow_policy(vals, {}),'')
        self.assertEqual(m._document_workflow_policy(vals, terminal, {'type':'title'}),'')
        vals.DOCUMENT_WORKFLOW_MODE = 'harness'
        self.assertEqual(m._document_workflow_policy(vals,terminal),'')
        terminal.update(m._TerminalHarness('/opt/h').tools())
        self.assertEqual(m._document_workflow_policy(vals,terminal),m._TerminalHarness.POLICY)
        vals.ENABLE_TERMINAL_HARNESS = False
        self.assertEqual(m._document_workflow_policy(vals,terminal),'')

    async def test_actual_pipe_injects_simple_guidance_without_locator(self):
        pipe = m.Pipe()
        pipe._run_streaming_loop = AsyncMock(return_value='ok')
        await pipe._pipe_impl({'model':'openai_responses.gpt-6-sol','messages':[{'role':'user','content':'PPT 만들어줘'}],'stream':True},
            {'id':'u'},None,AsyncMock(),None,{'model':{'id':'openai_responses.gpt-6-sol'}},
            {'run_command':{'type':'terminal','spec':{'name':'run_command','parameters':{'type':'object','properties':{}}}}})
        body = pipe._run_streaming_loop.call_args.args[0]
        self.assertIn(m._SIMPLE_DOCUMENT_POLICY, body.instructions)
        self.assertNotIn('get_terminal_harness',[t.get('name') for t in body.tools])
