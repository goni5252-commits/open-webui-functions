import json
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from test_responses import m


class PresentationDesignTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_does_not_claim_download(self):
        plan = json.loads(await m._PresentationDesign.prepare('getdesign', 'linear.app'))
        self.assertEqual(plan['status'], 'plan_only')
        self.assertIn('display_file', plan['steps'][-1])
        self.assertIn('Korean', plan['steps'][4])
        self.assertNotIn('download_command', json.loads(await m._PresentationDesign.prepare('attachment', '')))

    async def test_reject_injection_and_paths(self):
        for slug in ('--help', '../notion', 'a;id', 'a\nb', '$(id)', 'https://getdesign.md/a', 'a/b', 'a'*81):
            with self.subTest(slug=slug):
                self.assertFalse(json.loads(await m._PresentationDesign.prepare('getdesign', slug))['ok'])

    async def test_isolated_download_and_error_handling(self):
        plan = json.loads(await m._PresentationDesign.prepare('getdesign', 'vercel'))
        argv = shlex.split(plan['download_command'])
        self.assertEqual(argv[:2], ['python3', '-c'])
        script = compile(argv[2], '<download>', 'exec')
        for mode in ('ok', 'failure', 'empty', 'html'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                def run(args, **kwargs):
                    self.assertEqual(args, ['npx', '-y', 'getdesign@latest', 'add', 'vercel'])
                    self.assertEqual(kwargs['cwd'], Path(directory).resolve())
                    self.assertEqual(kwargs['timeout'], 120)
                    if mode != 'empty':
                        Path(directory, 'DESIGN.md').write_text('<html>error' if mode == 'html' else '# Design\nCanvas: #FFFFFF')
                    return type('Result', (), {'returncode': int(mode == 'failure'), 'stderr': 'failed', 'stdout': ''})()
                with patch('tempfile.mkdtemp', return_value=directory), patch('subprocess.run', side_effect=run), patch('builtins.print') as output:
                    if mode == 'ok':
                        exec(script, {})
                        self.assertEqual(json.loads(output.call_args.args[0])['status'], 'downloaded')
                    else:
                        with self.assertRaises(RuntimeError): exec(script, {})

    async def test_registration_gates_and_schema(self):
        for terminal, enabled, task in ((True, True, None), (False, True, None), (True, False, None), (True, True, {'type':'title'})):
            pipe = m.Pipe()
            pipe.valves.ENABLE_PRESENTATION_DESIGN = enabled
            pipe._pipe_impl = AsyncMock(return_value='ok')
            registry = {'run_command': {'type': 'terminal', 'tool_id': 'terminal:one'}} if terminal else {}
            await pipe.pipe({'messages': []}, {'id':'u'}, None, AsyncMock(), None, {}, registry, [], task)
            tools = pipe._pipe_impl.call_args.args[6]
            self.assertEqual('prepare_presentation_design' in tools, terminal and enabled and not task)
            if 'prepare_presentation_design' in tools:
                specs = m.ResponsesBody.transform_owui_tools(tools, strict=True)
                spec = next(s for s in specs if s['name'] == 'prepare_presentation_design')
                self.assertEqual(set(spec['parameters']['required']), {'source', 'slug'})

    async def test_name_collision_reports_error(self):
        pipe = m.Pipe()
        pipe._pipe_impl = AsyncMock()
        result = await pipe.pipe({'messages': []}, {}, None, AsyncMock(), None, {}, {
            'run_command': {'type':'terminal'}, 'prepare_presentation_design': {}}, [])
        pipe._pipe_impl.assert_not_called()
        self.assertIn('충돌', result)
