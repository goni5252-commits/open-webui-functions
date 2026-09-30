"""Native PDF bytes and GPT-6.1 contracts; no live WebUI or paid API calls."""
import base64
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from test_responses import m, completed


class NativePdfTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pipe = m.Pipe()
        self.pipe.valves.PDF_MISTRAL_PAGE_THRESHOLD = 0
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = b'%PDF-1.7\noriginal scan bytes\n%%EOF'
        self.path = Path(self.temp.name) / 'original.pdf'
        self.path.write_bytes(self.raw)
        self.records = {
            'pdf': types.SimpleNamespace(user_id='u', filename='scan.PDF', meta={}, path='trusted-key'),
            'doc': types.SimpleNamespace(user_id='u', filename='form.hwpx', meta={}, path='other-key'),
            'mime': types.SimpleNamespace(user_id='u', filename='document', meta={'content_type':'application/pdf'}, path='trusted-key'),
        }
        self.files = Mock(side_effect=self.records.get)
        self.storage = Mock(return_value=str(self.path))
        self.access = AsyncMock(return_value=False)
        modules = {}
        for name, values in {
            'open_webui.models.files': {'Files': types.SimpleNamespace(get_file_by_id=self.files)},
            'open_webui.models.users': {'Users':types.SimpleNamespace(get_user_by_id=Mock(return_value=types.SimpleNamespace(id='u')))},
            'open_webui.utils.access_control.files': {'has_access_to_file':self.access},
            'open_webui.storage.provider': {'Storage':types.SimpleNamespace(get_file=self.storage)},
        }.items():
            modules[name] = types.ModuleType(name)
            vars(modules[name]).update(values)
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def inject(self, entries=None, body=None, metadata=None, value=None, **valves):
        result = m.ResponsesBody(model='gpt-6.1-sol', input=value if value is not None else 'read this')
        return await self.pipe._inject_native_pdf_context(result, m.Pipe.Valves(**{'PDF_MISTRAL_PAGE_THRESHOLD': 0, **valves}),
            {'id':'u'}, body or {}, metadata or {}, entries)

    async def test_all_pdf_bytes_nested_ids_deduplicated_mixed_media_preserved(self):
        value = [{'role':'user','content':[{'type':'input_text','text':'HWPX parsed table'},
                  {'type':'input_image','image_url':'data:image/png;base64,eA=='}]}]
        result = await self.inject([{'file':{'id':'pdf'},'path':'/untrusted'}, {'id':'pdf'}, {'id':'doc'}, {'id':'mime'}], value=value)
        blocks = result.input[-1]['content']
        self.assertEqual(blocks[:2], value[0]['content'][:2])
        self.assertEqual(len(blocks), 4)
        self.assertEqual(base64.b64decode(blocks[2]['file_data'].split(',',1)[1]), self.raw)
        self.assertEqual(self.storage.call_args_list[0].args, ('trusted-key',))
        self.assertEqual(self.files.call_count, 3)

    async def test_sources_and_earlier_turn(self):
        result = await self.inject([], body={'messages':[{'role':'user','files':[{'id':'pdf'}]}]}, metadata={'files':[{'id':'mime'}]})
        self.assertEqual(len(result.input[-1]['content']), 3)

    async def test_denied_file_never_read(self):
        self.records['pdf'].user_id = 'other'
        with self.assertRaisesRegex(ValueError, '접근'):
            await self.inject([{'id':'pdf'}])
        self.storage.assert_not_called()

    async def test_shared_file_allowed(self):
        self.records['pdf'].user_id = 'other'
        self.access.return_value = True
        result = await self.inject([{'id':'pdf'}])
        self.assertEqual(result.input[-1]['content'][-1]['type'],'input_file')

    async def test_missing_file_explicit_error(self):
        with self.assertRaisesRegex(ValueError, '찾지'):
            await self.inject([{'id':'missing'}])

    async def test_unreadable_explicit_error(self):
        self.storage.side_effect = OSError('secret storage path')
        with self.assertRaisesRegex(ValueError, 'PDF 원본을 읽지'):
            await self.inject([{'id':'pdf'}])

    async def test_invalid_and_oversized(self):
        self.path.write_bytes(b'not a PDF')
        with self.assertRaisesRegex(ValueError, '유효한 PDF'):
            await self.inject([{'id':'pdf'}])
        self.path.write_bytes(b'%PDF-' + b'x' * 600_000)
        with self.assertRaisesRegex(ValueError, '한도'):
            await self.inject([{'id':'pdf'},{'id':'mime'}], PDF_NATIVE_MAX_MB=1)

    async def test_no_files_or_non_pdf_does_not_modify_input(self):
        self.assertEqual((await self.inject([])).input,'read this')
        self.assertEqual((await self.inject([{'id':'doc'}])).input,'read this')
        self.storage.assert_not_called()

    async def test_existing_native_bytes_not_added_twice(self):
        block = {'type':'input_file','filename':'scan.PDF','file_data':'data:application/pdf;base64,' + base64.b64encode(self.raw).decode()}
        result = await self.inject([{'id':'pdf'}], value=[{'role':'user','content':[block]}])
        self.assertEqual(result.input[-1]['content'], [block])

    async def test_path_only_pdf_rejected(self):
        with self.assertRaisesRegex(ValueError, '첨부 ID'):
            await self.inject([{'filename':'secret.pdf','path':str(self.path)}])
        self.storage.assert_not_called()

    async def test_existing_inline_files_count_toward_limit(self):
        encoded = 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-' + b'x' * 1_000_000).decode()
        with self.assertRaisesRegex(ValueError, '한도'):
            await self.inject([{'id':'pdf'}], value=[{'role':'user','content':[
                {'type':'input_file','filename':'old.pdf','file_data':encoded}]}], PDF_NATIVE_MAX_MB=1)

    async def test_disabled_native_input_and_tasks_do_not_read_files(self):
        self.pipe.valves.PDF_NATIVE_INPUT = False
        self.pipe.valves.HWPX_NATIVE_PARSER = False
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe._run_nonstreaming_loop = AsyncMock(return_value='ok')
        args = ({'model':'gpt-6.1-sol','messages':[{'role':'user','content':'read'}], 'stream':False},
                {'id':'u','email':'u@test'}, None, AsyncMock(), None, {}, {}, [{'id':'pdf'}])
        await self.pipe._pipe_impl(*args)
        self.storage.assert_not_called()
        self.pipe.valves.PDF_NATIVE_INPUT = True
        self.pipe._run_task_model_request = AsyncMock(return_value='title')
        await self.pipe._pipe_impl(*args, __task__={'type':'title'})
        self.storage.assert_not_called()

    async def test_regular_pipe_invokes_native_input_before_response(self):
        self.pipe.valves.HWPX_NATIVE_PARSER = False
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe._run_nonstreaming_loop = AsyncMock(return_value='ok')
        result = await self.pipe._pipe_impl(
            {'model':'gpt-6.1-sol','messages':[{'role':'user','content':'read'}], 'stream':False},
            {'id':'u','email':'u@test'}, None, AsyncMock(), None, {}, {}, [{'id':'pdf'}])
        self.assertEqual(result, 'ok')
        wire = self.pipe._run_nonstreaming_loop.call_args.args[0].model_dump()
        self.assertEqual(wire['model'], 'gpt-6.1-sol')
        self.assertTrue(any(b['type']=='input_file' for item in wire['input'] for b in item.get('content',[]) if isinstance(b,dict)))


class Sol61Tests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_model_list_and_disable(self):
        pipe = m.Pipe()
        pipe.valves.MODEL_ID = 'gpt-6-sol'
        ids = [p['id'] for p in await pipe.pipes()]
        self.assertIn('gpt-6.1-sol', ids)
        self.assertIn('gpt-6.1-sol-auto', ids)
        pipe.valves.ENABLE_GPT61_SOL_MODEL = False
        self.assertNotIn('gpt-6.1-sol', [p['id'] for p in await pipe.pipes()])

    async def test_reasoning_and_wire_compatibility(self):
        self.assertEqual(m.ModelFamily.base_model('openai_responses.gpt-6.1-sol-auto'), 'gpt-6.1-sol')
        self.assertNotIn('none', m.ModelFamily.reasoning_efforts('gpt-6.1-sol'))
        self.assertTrue(m.ModelFamily.supports('function_calling', 'gpt-6.1-sol'))
        normalize = m._prepare_responses_request
        for effort in ('none','minimal','max'):
            wire = normalize({'model':'gpt-6.1-sol','reasoning':{'effort':effort}, 'temperature':0.5, 'top_p':0.8})
            self.assertNotIn(wire['reasoning']['effort'], ('none','minimal'))
            self.assertNotIn('temperature', wire)
            self.assertNotIn('top_p', wire)

    async def test_fixed_auto_keeps_model_and_supported_effort(self):
        pipe = m.Pipe()
        pipe.send_openai_responses_nonstreaming_request = AsyncMock(
            return_value=completed('{"reasoning_effort":"medium","explanation":"document analysis"}'))
        result = await pipe._route_auto_reasoning(
            router_model='gpt-6-luna', responses_body=m.ResponsesBody(model='gpt-6.1-sol-auto', input='analyze'),
            tools=[], valves=m.Pipe.Valves(), public_alias='gpt-6.1-sol-auto')
        self.assertEqual(result.model, 'gpt-6.1-sol')
        self.assertEqual(result.reasoning['effort'], 'medium')
