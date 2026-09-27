"""Offline image workflow regressions. Provider HTTP and WebUI storage are mocked.

Optional Google SDK contract checks run when google-genai is installed. No paid
API requests. Shared helpers are extracted from the standalone exports by AST.
"""
import ast
import asyncio
import base64
import copy
import hashlib
import inspect
import io
import json
import logging
import os
import typing
from pydantic import BaseModel, Field
from pathlib import Path
import re
import sys
import time
import types as pytypes
import unittest
from unittest.mock import AsyncMock, patch
from collections.abc import Mapping
from contextvars import ContextVar
import contextlib
from typing import Any, Dict, List, Optional, Callable, Union, AsyncIterator
from test_responses import m, completed

ROOT = Path(__file__).resolve().parents[1]
PNG = b'\x89PNG\r\n\x1a\noriginal-image-bytes'
DATA = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
REF = 'data:image/png;base64,' + base64.b64encode(b'reference-image').decode()


def load_gemini_helpers():
    path = ROOT / 'functions/google_gemini.py'
    tree = ast.parse(path.read_text())
    pipe = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Pipe')
    common = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_ConversationImages')
    ns = {**vars(typing), **globals()}
    try:
        from google.genai import types, errors
        ns.update(types=types, ClientError=errors.ClientError, ServerError=errors.ServerError, APIError=errors.APIError)
    except ImportError:
        ns['types'] = pytypes.SimpleNamespace(HttpOptions=lambda **kw: pytypes.SimpleNamespace(**kw),
            HttpRetryOptions=lambda **kw: pytypes.SimpleNamespace(**kw))
        ns.update(ClientError=type('ClientError', (Exception,), {}),
                  ServerError=type('ServerError', (Exception,), {}), APIError=type('APIError', (Exception,), {}))
    ns.update(Request=object, EncryptedStr=str, Users=pytypes.SimpleNamespace(get_user_by_id=AsyncMock()))
    constants = [n for n in tree.body if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Name) and n.target.id.endswith('_OPTIONS')]
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[common], type_ignores=[])), str(path), 'exec'), ns)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future] + constants + [pipe], type_ignores=[])), str(path), 'exec'), ns)
    ns['Pipe'].Valves.model_rebuild(_types_namespace=ns)
    return ns['Pipe'], ns['_ConversationImages']


Gemini, GeminiImages = load_gemini_helpers()


class ImageSessionTests(unittest.IsolatedAsyncioTestCase):
    def session(self, cls=m._ConversationImages, messages=None, files=None, **kwargs):
        generate = AsyncMock(return_value=([(PNG, 'image/png')], {'total_tokens': 12}))
        session = cls(messages or [], files or [], {}, None, AsyncMock(), generate, **kwargs)
        return session, generate

    def test_export_helpers_remain_identical(self):
        nodes = []
        for name in ('openai_responses', 'google_gemini'):
            tree = ast.parse((ROOT / f'functions/{name}.py').read_text())
            node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_ConversationImages')
            nodes.append(ast.dump(node, include_attributes=False))
        self.assertEqual(*nodes)

    async def test_create_edit_reference_new_and_branch_replay_both_providers(self):
        for cls in (m._ConversationImages, GeminiImages):
            session, api = self.session(cls, max_calls=4)
            created = await session.run('고양이를 그려줘', 'create', '', [])
            source = created['images'][0]['image_id']
            self.assertTrue(created['ok'])
            self.assertEqual(api.call_args.args[2], [])
            reference = session._add(REF, 'user', 1)
            edited = await session.run('배경만 파랗게', 'edit', source, [reference])
            self.assertTrue(edited['ok'])
            self.assertEqual(api.call_args.args[2], [(PNG, 'image/png'), (b'reference-image', 'image/png')])
            await session.run('완전히 다른 풍경', 'create', '', [])
            self.assertEqual(api.call_args.args[2], [])
            markdown = session.drain()
            self.assertIn('![Generated Image', markdown)
            self.assertEqual(session.drain(), '')
            replay, _ = self.session(cls, [{'role': 'assistant', 'content': markdown}])
            self.assertIn(source, replay.entries)
            other, _ = self.session(cls)
            self.assertNotIn(source, other.entries)

    async def test_missing_source_does_not_generate(self):
        session, api = self.session()
        for source in ('', 'invented'):
            result = await session.run('바꿔줘', 'edit', source, [])
            self.assertFalse(result['ok'])
        api.assert_not_awaited()

    async def test_create_with_source_rejected_and_references_explicit(self):
        session, api = self.session(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':DATA}}]}])
        source = next(iter(session.entries))
        self.assertFalse((await session.run('new', 'create', source, []))['ok'])
        self.assertTrue((await session.run('new using reference', 'create', '', [source]))['ok'])
        self.assertEqual(api.call_args.args[2], [(PNG, 'image/png')])

    async def test_duplicate_parallel_calls_bill_once(self):
        session, api = self.session()
        results = await asyncio.gather(*(session.run('cat', 'create', '', []) for _ in range(3)))
        api.assert_awaited_once()
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(session.rendered), 1)

    async def test_failure_cached_and_budget_bounded(self):
        session, api = self.session(max_calls=1)
        api.side_effect = TimeoutError('provider timeout')
        self.assertFalse((await session.run('cat', 'create', '', []))['ok'])
        self.assertFalse((await session.run('cat', 'create', '', []))['ok'])
        self.assertFalse((await session.run('dog', 'create', '', []))['ok'])
        api.assert_awaited_once()
        self.assertEqual(session.rendered, [])

    async def test_no_image_is_failure(self):
        session, api = self.session()
        api.return_value = ([], {})
        self.assertFalse((await session.run('cat', 'create', '', []))['ok'])
        self.assertEqual(session.rendered, [])

    def test_catalog_contains_branch_roles_and_no_payloads(self):
        messages = [{'role':'system','content':f'![system]({REF})'},
                    {'role':'assistant','content':f'![old]({DATA})'},
                    {'role':'user','files':[{'type':'image','id':'upload-1'}], 'content':'edit'}]
        session, _ = self.session(messages=messages)
        self.assertEqual(len(session.entries), 2)
        self.assertNotIn('base64', session.policy())
        self.assertNotIn('/api/v1/files/', session.policy())
        self.assertIn('assistant', session.policy())

    async def test_remote_urls_refuse_fetch(self):
        session, api = self.session(messages=[{'role':'user','content':f'![image](http://127.0.0.1/private.png)'}])
        image_id = next(iter(session.entries))
        result = await session.run('edit', 'edit', image_id, [])
        self.assertFalse(result['ok'])
        api.assert_not_awaited()

    async def test_webui_authorization_and_original_bytes(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as file:
            file.write(PNG); file.flush()
            record = pytypes.SimpleNamespace(user_id='owner', path=file.name, meta={'content_type':'image/png'})
            user = pytypes.SimpleNamespace(id='viewer')
            authorize = AsyncMock(return_value=False)
            storage = pytypes.SimpleNamespace(get_file=lambda path: path)
            modules = {
                'open_webui.models.files': pytypes.SimpleNamespace(Files=pytypes.SimpleNamespace(get_file_by_id=AsyncMock(return_value=record))),
                'open_webui.models.users': pytypes.SimpleNamespace(Users=pytypes.SimpleNamespace(get_user_by_id=AsyncMock(return_value=user))),
                'open_webui.utils.access_control.files': pytypes.SimpleNamespace(has_access_to_file=authorize),
                'open_webui.storage.provider': pytypes.SimpleNamespace(Storage=storage),
            }
            session, api = self.session(files=[{'type':'image','id':'file-1'}])
            session.user = {'id':'viewer'}
            source = next(iter(session.entries))
            with patch.dict(sys.modules, modules):
                self.assertFalse((await session.run('denied', 'edit', source, []))['ok'])
                api.assert_not_awaited()
                authorize.return_value = True
                self.assertTrue((await session.run('allowed', 'edit', source, []))['ok'])
                self.assertEqual(api.call_args.args[2], [(PNG, 'image/png')])

    async def test_status_failure_does_not_lose_paid_result(self):
        session, api = self.session()
        session.emitter = AsyncMock(side_effect=RuntimeError('disconnected UI'))
        result = await session.run('cat', 'create', '', [])
        self.assertTrue(result['ok'])
        self.assertIn('![Generated Image', session.drain())
        api.assert_awaited_once()

    async def test_webui_storage_contract(self):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def db_context():
            yield 'test-db'
        class Upload:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        upload = AsyncMock(return_value=pytypes.SimpleNamespace(id='saved-file'))
        user = pytypes.SimpleNamespace(id='owner')
        modules = {
            'fastapi': pytypes.SimpleNamespace(UploadFile=Upload, BackgroundTasks=lambda: object()),
            'starlette.datastructures': pytypes.SimpleNamespace(Headers=lambda values: values),
            'open_webui.models.users': pytypes.SimpleNamespace(Users=pytypes.SimpleNamespace(get_user_by_id=AsyncMock(return_value=user))),
            'open_webui.routers.files': pytypes.SimpleNamespace(upload_file=upload),
            'open_webui.internal.db': pytypes.SimpleNamespace(get_async_db_context=db_context),
        }
        session, _ = self.session()
        session.request, session.user = object(), {'id':'owner'}
        with patch.dict(sys.modules, modules):
            result = await session.run('cat', 'create', '', [])
        self.assertTrue(result['ok'])
        self.assertIn('/api/v1/files/saved-file/content', session.drain())
        self.assertIs(upload.call_args.kwargs['user'], user)
        self.assertFalse(upload.call_args.kwargs['process'])
        self.assertEqual(upload.call_args.kwargs['file'].file.getvalue(), PNG)


class OpenAIImageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipe_registers_tool_and_removes_duplicate_image_engines(self):
        pipe = m.Pipe()
        pipe._run_streaming_loop = AsyncMock(return_value='ok')
        original = {'generate_image': {'spec': {'name':'generate_image'}},
                    'edit_image': {'spec':{'name':'edit_image'}}}
        await pipe._pipe_impl({'model':'openai_responses.gpt-6-sol','stream':True,
                              'messages':[{'role':'user','content':'고양이를 그려줘'}],
                              'extra_tools':[{'type':'image_generation'}]},
                             {'id':'u'}, None, AsyncMock(), None, {'model':{'id':'openai_responses.gpt-6-sol'}}, original)
        body = pipe._run_streaming_loop.call_args.args[0]
        names = [t.get('name') for t in body.tools]
        self.assertIn('conversation_image', names)
        self.assertNotIn('generate_image', names)
        self.assertNotIn('edit_image', names)
        self.assertNotIn('image_generation', [t.get('type') for t in body.tools])
        self.assertEqual(len(original), 2)
        self.assertIn('self-contained prompt', body.instructions)

    async def test_transport_receives_selected_model_original_and_references(self):
        pipe = m.Pipe()
        pipe.send_openai_images_request = AsyncMock(return_value={'data':[{'b64_json':base64.b64encode(PNG).decode()}]})
        valves = m.Pipe.Valves(CONVERSATION_IMAGE_MODEL='gpt-image-2.5-flare', IMAGE_QUALITY='xhigh')
        session = pipe._conversation_image_session({'messages':[{'role':'assistant','content':f'![old]({DATA})'},
            {'role':'user','content':[{'type':'input_image','image_url':REF}]}]}, valves, {}, None, AsyncMock(), {}, [])
        source, reference = session.entries
        await session.run('only background', 'edit', source, [reference])
        params = pipe.send_openai_images_request.call_args.args[0]
        self.assertEqual(params['model'], 'gpt-image-2.5-flare')
        self.assertEqual(params['quality'], 'xhigh')
        self.assertEqual(params['image'], [PNG, b'reference-image'])
        self.assertIn('Edit image 1', params['prompt'])

    async def test_stream_and_nonstream_render_image_once_and_keep_tool_output_small(self):
        for stream in (True, False):
            pipe = m.Pipe()
            session, api = ImageSessionTests().session()
            call = {'type':'function_call','call_id':'call1','name':'conversation_image',
                    'arguments':json.dumps({'prompt':'cat','operation':'create','source_id':'','reference_ids':[]})}
            requests = []
            async def events(body, **kwargs):
                requests.append(copy.deepcopy(body))
                if len(requests) == 1:
                    yield {'type':'response.completed','response':{'output':[call]}}
                else:
                    yield {'type':'response.completed','response':completed('완료했습니다.')}
            pipe.send_openai_responses_streaming_request = events
            emit = AsyncMock()
            method = pipe._run_streaming_loop if stream else pipe._run_nonstreaming_loop
            result = await method(m.ResponsesBody(model='gpt-6-sol', input='cat'),
                m.Pipe.Valves(PERSIST_TOOL_RESULTS=False), emit, {}, session.tools())
            self.assertEqual(result.count('![Generated Image'), 1)
            self.assertIn('완료했습니다.', result)
            outputs = [x for x in requests[1]['input'] if x.get('type') == 'function_call_output']
            self.assertNotIn('base64', outputs[0]['output'])
            api.assert_awaited_once()

    async def test_disabled_and_background_skip_image_tool(self):
        for task in (None, 'title_generation'):
            pipe = m.Pipe()
            pipe.valves.ENABLE_CONVERSATION_IMAGES = False if task is None else True
            pipe._run_nonstreaming_loop = AsyncMock(return_value='chat')
            pipe._run_task_model_request = AsyncMock(return_value='title')
            await pipe._pipe_impl({'model':'gpt-6-sol','messages':[{'role':'user','content':'draw'}]},
                {'id':'u'}, None, AsyncMock(), None, {}, {}, __task__=task)
            if task:
                pipe._run_task_model_request.assert_awaited_once()
                pipe._run_nonstreaming_loop.assert_not_awaited()
            else:
                body = pipe._run_nonstreaming_loop.call_args.args[0]
                self.assertNotIn('conversation_image', [t.get('name') for t in body.tools or []])


class GeminiImageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def pipe(self):
        pipe = Gemini.__new__(Gemini)
        pipe.valves = pytypes.SimpleNamespace(AUTO_IMAGE_MODEL='gemini-3.1-flash-image', CONVERSATION_IMAGE_MAX_CALLS=2)
        pipe._prepare_model_id = lambda s: s
        pipe._check_image_generation_support = lambda s: 'image' in s
        pipe._configure_generation = lambda *args, **kwargs: pytypes.SimpleNamespace()
        pipe._build_usage_dict = lambda value: value or {}
        pipe._close_client = AsyncMock()
        return pipe

    async def test_transport_skips_thought_images_and_preserves_source(self):
        pipe = self.pipe()
        response = pytypes.SimpleNamespace(candidates=[pytypes.SimpleNamespace(content=pytypes.SimpleNamespace(parts=[
            pytypes.SimpleNamespace(thought=True, inline_data=pytypes.SimpleNamespace(data=b'thought',mime_type='image/png')),
            pytypes.SimpleNamespace(thought=False, inline_data=pytypes.SimpleNamespace(data=PNG,mime_type='image/png'))]))])
        generate = AsyncMock(return_value=response)
        client = pytypes.SimpleNamespace(aio=pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(generate_content=generate)))
        pipe._get_client = lambda: client
        session = pipe._conversation_image_session({'messages':[{'role':'assistant','content':f'![old]({DATA})'}]}, {}, {}, None, AsyncMock())
        source = next(iter(session.entries))
        result = await session.run('배경만 변경', 'edit', source, [])
        self.assertTrue(result['ok'])
        self.assertEqual(len(session.rendered), 1)
        request = generate.call_args.kwargs
        self.assertEqual(request['model'], 'gemini-3.1-flash-image')
        self.assertEqual(request['contents'][0]['parts'][-1]['inline_data']['data'], PNG)
        pipe._close_client.assert_awaited_once_with(client)

    async def test_wrapper_keeps_image_when_final_text_request_fails(self):
        pipe = self.pipe()
        async def impl(body, metadata, emitter, tools, request, user, holder):
            session, _ = ImageSessionTests().session(GeminiImages)
            await session.run('cat', 'create', '', [])
            holder.append(session)
            return 'Error generating content: final API timeout'
        pipe._conversation_pipe_impl = impl
        result = await pipe.pipe({'messages':[]})
        self.assertIn('final API timeout', result)
        self.assertEqual(result.count('![Generated Image'), 1)

    async def test_dedicated_edit_limit_and_system_instruction_preservation(self):
        pipe = Gemini.__new__(Gemini)
        pipe.valves = Gemini.Valves(IMAGE_HISTORY_MAX_REFERENCES=2)
        pipe.log = logging.getLogger('gemini-dedicated-image')
        old = {'inline_data':{'mime_type':'image/png','data':base64.b64encode(b'old').decode()}}
        current = [{'inline_data':{'mime_type':'image/png','data':base64.b64encode(value).decode()}}
                   for value in (b'first', b'second')]
        pipe._gather_history_images = AsyncMock(return_value=[old])
        pipe._extract_images_from_message = AsyncMock(return_value=('배경을 바꿔줘', current))
        contents, _ = await pipe._build_image_generation_contents([
            {'role':'system','content':'Keep the brand style.'}, {'role':'user','content':'배경을 바꿔줘'}], AsyncMock())
        sent = [part for part in contents[0]['parts'] if 'inline_data' in part]
        self.assertEqual(sent, current)
        text = contents[0]['parts'][0]['text']
        self.assertIn('Keep the brand style.', text)
        self.assertIn('Preserve all visual details', text)

    async def test_sdk_callable_schema_and_dispatch(self):
        try:
            from google.genai import types
        except ImportError:
            self.skipTest('google-genai optional SDK contract dependency not installed')
        session, api = ImageSessionTests().session(GeminiImages)
        tool = Gemini._named_native_tool('conversation_image', session.run, set())
        declaration = types.FunctionDeclaration.from_callable_with_api_option(callable=tool, api_option='GEMINI_API')
        self.assertEqual(declaration.name, 'conversation_image')
        self.assertEqual(set(declaration.parameters.properties), {'prompt','operation','source_id','reference_ids'})
        config = types.GenerateContentConfig(tools=[tool])
        self.assertTrue(callable(config.tools[0]))
        result = await tool(prompt='cat', operation='create', source_id='', reference_ids=[])
        self.assertTrue(result['ok'])
        api.assert_awaited_once()


class GeminiFullPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            self.skipTest('google-genai optional SDK contract dependency not installed')
        self.types = types
        transport = patch('google.genai._api_client.has_aiohttp', False)
        transport.start()
        self.addCleanup(transport.stop)
        self.client = genai.Client(api_key='offline-test-key')
        self.pipe = Gemini.__new__(Gemini)
        self.pipe.valves = Gemini.Valves(LIVE_PROGRESS_STATUS=False, AUTO_THINKING=False)
        self.pipe.log = logging.getLogger('gemini-image-integration')
        self.pipe._request_user = ContextVar('test_image_user', default=None)
        self.pipe._prepare_content = AsyncMock(return_value=([{'role':'user','parts':[{'text':'original request'}]}], None))
        self.pipe._progress_timeline_messages = lambda **kwargs: []
        self.pipe._emit_live_progress = AsyncMock()
        self.pipe._finish_progress_timing = AsyncMock()
        self.pipe._process_grounding_metadata = AsyncMock(side_effect=lambda metadata, answer, emitter: answer)
        self.image_api = AsyncMock(return_value=types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role='model', parts=[types.Part.from_bytes(data=PNG, mime_type='image/png')]))]))
        self.image_client = pytypes.SimpleNamespace(aio=pytypes.SimpleNamespace(models=pytypes.SimpleNamespace(generate_content=self.image_api)))
        clients = iter([self.client, self.image_client])
        self.pipe._get_client = lambda: next(clients)
        self.pipe._close_client = AsyncMock()

    async def asyncTearDown(self):
        if hasattr(self, 'client'):
            await self.client.aio.aclose()
            self.client.close()

    def response(self, text):
        t = self.types
        return t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model',parts=[t.Part(text=text)]))])

    def tool_response(self):
        t = self.types
        return t.GenerateContentResponse(candidates=[t.Candidate(content=t.Content(role='model',parts=[t.Part(
            function_call=t.FunctionCall(name='conversation_image', args={'prompt':'self-contained cat prompt',
                'operation':'create', 'source_id':'', 'reference_ids':[]}), thought_signature=b'signed-tool-part')]))])

    async def test_real_sdk_afc_from_text_model_renders_image_and_keeps_model(self):
        http = AsyncMock(side_effect=[self.tool_response(), self.response('완료')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model':'gemini-3.7-flash','stream':True,
                'messages':[{'role':'user','content':'고양이를 그려줘'}]}, __event_emitter__=AsyncMock())
        self.assertIn('![Generated Image', result)
        self.image_api.assert_awaited_once()
        self.assertTrue(all(c.kwargs['model'] == 'gemini-3.7-flash' for c in http.call_args_list))
        self.assertEqual(self.image_api.call_args.kwargs['model'], 'gemini-3.1-flash-image')
        self.assertEqual(self.image_api.call_args.kwargs['config'].http_options.retry_options.attempts, 1)
        self.assertEqual(http.await_count, 2)

    async def test_prompt_only_uses_no_image_api(self):
        http = AsyncMock(return_value=self.response('프롬프트 예시입니다.'))
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model':'gemini-3.7-flash','messages':[
                {'role':'user','content':'이미지 생성 프롬프트를 만들어줘'}]})
        self.assertEqual(result, '프롬프트 예시입니다.')
        self.image_api.assert_not_awaited()

    async def test_legacy_ui_mode_still_exposes_internal_image_tool(self):
        http = AsyncMock(side_effect=[self.tool_response(), self.response('완료')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model':'gemini-3.7-flash','messages':[{'role':'user','content':'그려줘'}]},
                __metadata__={'params':{'function_calling':'legacy'}})
        self.assertIn('![Generated Image', result)
        self.image_api.assert_awaited_once()

    async def test_search_stage_keeps_signatures_and_then_calls_image(self):
        searched = self.response('검색으로 확인한 배경 정보')
        searched.candidates[0].content.parts[0].thought_signature = b'search-signature'
        searched.candidates[0].grounding_metadata = self.types.GroundingMetadata(
            grounding_chunks=[{'web':{'uri':'https://example.com/source','title':'source'}}],
            grounding_supports=[{'segment':{'end_index':3}, 'grounding_chunk_indices':[0]}])
        http = AsyncMock(side_effect=[searched, self.tool_response(), self.response('완료')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model':'gemini-3.7-flash','messages':[
                {'role':'user','content':'최신 정보를 찾아 포스터를 그려줘'}]},
                __metadata__={'features':{'web_search':True}})
        self.assertIn('![Generated Image', result)
        self.image_api.assert_awaited_once()
        self.assertEqual(http.await_count, 3)
        parts = http.call_args_list[1].kwargs['contents'][1].parts
        self.assertEqual(parts[0].thought_signature, b'search-signature')
        groundings = self.pipe._process_grounding_metadata.call_args.args[0]
        self.assertEqual(groundings[0].grounding_supports, [])
        self.assertEqual(len(searched.candidates[0].grounding_metadata.grounding_supports), 1)
        self.assertIn('https://example.com/source', str(http.call_args_list[1].kwargs['contents']))

    async def test_final_text_failure_preserves_generated_image_without_retry(self):
        http = AsyncMock(side_effect=[self.tool_response(), RuntimeError('final text failed')])
        with patch.object(self.client.aio.models, '_generate_content', http):
            result = await self.pipe.pipe({'model':'gemini-3.7-flash','messages':[{'role':'user','content':'고양이를 그려줘'}]})
        self.assertIn('final text failed', result)
        self.assertIn('![Generated Image', result)
        self.image_api.assert_awaited_once()

    async def test_background_task_does_not_expose_image_tool(self):
        http = AsyncMock(return_value=self.response('title'))
        with patch.object(self.client.aio.models, '_generate_content', http):
            await self.pipe.pipe({'model':'gemini-3.7-flash','messages':[{'role':'user','content':'고양이 그림을 그려줘'}]}, __task__='title_generation')
        tools = http.call_args.kwargs['config'].tools or []
        self.assertFalse(any(getattr(tool, '__name__', '') == 'conversation_image' for tool in tools))
        self.image_api.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
