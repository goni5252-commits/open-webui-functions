"""Real SDK configuration checks for shared Terminal instructions; no network calls."""
import json
import logging
import shlex
import unittest
from unittest.mock import AsyncMock
from pydantic import ValidationError
from test_conversation_images import Gemini


class GeminiHarnessTests(unittest.TestCase):
    def setUp(self):
        self.pipe = object.__new__(Gemini)
        self.pipe.valves = Gemini.Valves(DOCUMENT_WORKFLOW_MODE='harness', AUTO_GOOGLE_SEARCH=False)
        self.pipe.log = logging.getLogger('gemini-harness-test')
        self.tool = {'type': 'terminal', 'callable': AsyncMock(return_value='ok'),
                     'spec': {'name': 'run_command', 'description': 'Run a Terminal command',
                              'parameters': {'type': 'object', 'properties': {
                                  'command': {'type': 'string'}}, 'required': ['command']}}}

    def config(self, tools=None, metadata=None, body=None, image=False):
        return self.pipe._configure_generation(
            body or {'model': 'gemini-4-hydrogen', 'messages': [{'role': 'user', 'content': 'PPT 만들어줘'}]},
            'existing instructions', metadata or {},
            {'run_command': self.tool} if tools is None else tools,
            enable_image_generation=image, model_id='gemini-4-hydrogen')

    def test_enabled_config_keeps_existing_tools_and_instructions(self):
        self.pipe.valves.TERMINAL_HARNESS_ROOT = '/home/harness-ppt-kordoc/openwebui-harness'
        config = self.config()
        self.assertIn('existing instructions', config.system_instruction)
        commands = json.loads(config.system_instruction.splitlines()[-1])
        self.assertEqual(commands['status'], 'location_only')
        self.assertEqual(shlex.split(commands['read_command']), [
            'cat', '--', '/home/harness-ppt-kordoc/openwebui-harness/AGENTS.md'])
        self.assertEqual(len([t for t in config.tools if callable(t)]), 1)
        self.tool['callable'].assert_not_called()
        self.assertNotIn('_terminal_harness', self.tool)

    def test_shell_paths_are_quoted_and_site_is_optional(self):
        self.pipe.valves.TERMINAL_HARNESS_ROOT = '/home/shared folder/$(touch nope)'
        self.pipe.valves.TERMINAL_HARNESS_ENTRYPOINT = 'docs/entry file.md'
        self.pipe.valves.TERMINAL_HARNESS_SITE_ROOT = '/home/site;echo nope'
        commands = json.loads(self.pipe._terminal_harness_policy().splitlines()[-1])
        self.assertEqual(shlex.split(commands['catalog_command']), [
            'python3', '/home/shared folder/$(touch nope)/scripts/harness.py',
            'catalog', '--site-root', '/home/site;echo nope'])
        self.assertEqual(shlex.split(commands['read_command'])[-1],
                         '/home/shared folder/$(touch nope)/docs/entry file.md')

    def test_invalid_paths_do_not_emit_commands(self):
        for field, value in [('TERMINAL_HARNESS_ROOT', 'relative'),
                             ('TERMINAL_HARNESS_ROOT', '/a/../b'),
                             ('TERMINAL_HARNESS_SITE_ROOT', '/a\nb'),
                             ('TERMINAL_HARNESS_ENTRYPOINT', '../AGENTS.md'),
                             ('TERMINAL_HARNESS_ENTRYPOINT', '/AGENTS.md'),
                             ('TERMINAL_HARNESS_ENTRYPOINT', '.')]:
            with self.subTest(field=field, value=value):
                original = getattr(self.pipe.valves, field)
                setattr(self.pipe.valves, field, value)
                policy = self.pipe._terminal_harness_policy()
                self.assertIn('설정이 올바르지', policy)
                self.assertNotIn('read_command', policy)
                setattr(self.pipe.valves, field, original)

    def test_defaults_and_disabled_preserve_old_behavior(self):
        self.assertEqual(Gemini.Valves().DOCUMENT_WORKFLOW_MODE, 'simple')
        for field, value in [('DOCUMENT_WORKFLOW_MODE', 'simple'), ('ENABLE_TERMINAL_HARNESS', False)]:
            original = getattr(self.pipe.valves, field)
            setattr(self.pipe.valves, field, value)
            self.assertNotIn('catalog_command', self.config().system_instruction)
            setattr(self.pipe.valves, field, original)
        with self.assertRaises(ValidationError):
            Gemini.Valves(DOCUMENT_WORKFLOW_MODE='typo')

    def test_requires_an_executable_terminal_tool(self):
        for tools in ({}, {'search': {**self.tool, 'type': 'external'}},
                      {'run_command': {**self.tool, 'callable': None}},
                      {'_hidden': self.tool}):
            self.assertNotIn('catalog_command', self.config(tools=tools).system_instruction)

    def test_legacy_background_ocr_image_and_search_only_omit_harness(self):
        for metadata, body, image in [
            ({'params': {'function_calling': 'legacy'}}, None, False),
            ({'task': 'title_generation'}, None, False),
            ({}, {'metadata': {'task': 'tags_generation'}}, False),
            ({}, {'model': 'gemini-4-hydrogen-ocr'}, False),
            ({}, None, True),
            ({'features': {'web_search': True}}, None, False),
        ]:
            with self.subTest(metadata=metadata, body=body, image=image):
                config = self.config(metadata=metadata, body=body, image=image)
                self.assertNotIn('catalog_command', config.system_instruction)

    def test_visual_review_filter_does_not_reintroduce_terminal(self):
        from test_gemini_latency import body
        config = self.config(body=body('이 문항의 문법 오류를 검토해줘'))
        self.assertNotIn('catalog_command', config.system_instruction)
        self.assertFalse(any(callable(t) for t in config.tools or []))

    def test_direct_browser_terminal_is_supported(self):
        direct = {**self.tool, 'callable': None, 'direct': True,
                  '_terminal_bridge': type('Bridge', (), {'execute': AsyncMock()})()}
        self.assertIn('catalog_command', self.config(tools={'run_command': direct}).system_instruction)
