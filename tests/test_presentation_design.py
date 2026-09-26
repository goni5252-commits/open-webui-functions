import json
import shlex
import unittest
from unittest.mock import AsyncMock
from test_responses import m


class HarnessLocatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_locator_does_not_claim_installation_and_quotes_path(self):
        root = "/opt/school harness/$(echo secret)"
        result = json.loads(await m._TerminalHarness(root).locate())
        self.assertEqual(result['status'], 'location_only')
        self.assertEqual(shlex.split(result['read_command']), ['cat', '--', root+'/AGENTS.md'])
        self.assertNotIn('steps', result)

    async def test_invalid_root(self):
        for root in ('relative/path', '/a/../b', '/opt/a\nb', '/opt/a\0b'):
            self.assertFalse(json.loads(await m._TerminalHarness(root).locate())['ok'])

    async def test_registration_gates_and_schema(self):
        for terminal, enabled, task in ((True, True, None), (False, True, None), (True, False, None), (True, True, {'type':'title'})):
            pipe = m.Pipe()
            pipe.valves.ENABLE_TERMINAL_HARNESS = enabled
            pipe._pipe_impl = AsyncMock(return_value='ok')
            registry = {'run_command': {'type': 'terminal', 'tool_id': 'terminal:one'}} if terminal else {}
            await pipe.pipe({'messages': []}, {'id':'u'}, None, AsyncMock(), None, {}, registry, [], task)
            tools = pipe._pipe_impl.call_args.args[6]
            self.assertEqual('get_terminal_harness' in tools, terminal and enabled and not task)
            self.assertNotIn('prepare_presentation_design', tools)
            if 'get_terminal_harness' in tools:
                specs = m.ResponsesBody.transform_owui_tools(tools, strict=True)
                spec = next(s for s in specs if s['name'] == 'get_terminal_harness')
                self.assertEqual(spec['parameters']['properties'], {})

    async def test_generic_settings_migrate_old_disabled_and_respect_new(self):
        self.assertFalse(m.Pipe.Valves(ENABLE_PRESENTATION_DESIGN=False).ENABLE_TERMINAL_HARNESS)
        self.assertTrue(m.Pipe.Valves(ENABLE_PRESENTATION_DESIGN=False, ENABLE_TERMINAL_HARNESS=True).ENABLE_TERMINAL_HARNESS)
        data = json.loads(await m._TerminalHarness('/opt/core', 'custom/AGENTS.md', '/opt/school site').locate())
        self.assertEqual(shlex.split(data['catalog_command']), ['python3','/opt/core/scripts/harness.py','catalog','--site-root','/opt/school site'])
        self.assertFalse(json.loads(await m._TerminalHarness('/opt/core','../AGENTS.md').locate())['ok'])

    async def test_name_collision_reports_error(self):
        pipe = m.Pipe()
        pipe._pipe_impl = AsyncMock()
        result = await pipe.pipe({'messages': []}, {}, None, AsyncMock(), None, {}, {
            'run_command': {'type':'terminal'}, 'get_terminal_harness': {}}, [])
        pipe._pipe_impl.assert_not_called()
        self.assertIn('충돌', result)
