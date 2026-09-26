"""Offline HWPX regression tests; OWUI DB boundaries are mocked."""
import asyncio
import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys
import json
import shutil
import subprocess
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile, ZIP_STORED
from lxml import etree

spec = importlib.util.spec_from_file_location('hwpx_export', Path(__file__).resolve().parents[1] / 'functions/한글문서_내보내기.py')
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==')

class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_async_db(self):
        self.assertEqual(await h._call_db(lambda: 3), 3)
        self.assertEqual(await h._call_db(AsyncMock(return_value=4)), 4)

    async def test_structured_content_and_reasoning(self):
        msg = {'content': '', 'output': [
            {'type': 'reasoning', 'summary': [{'text': '비공개 생각'}]},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': '최종 답변'}]}]}
        self.assertEqual(h.get_msg_text(msg), '최종 답변')
        self.assertEqual(h.get_msg_text({'content': None}), '')

    async def test_multimodal_image(self):
        self.assertIn('![이미지](/api/v1/files/abc/content)', h.get_msg_text({'content': [
            {'type': 'image_url', 'image_url': {'url': '/api/v1/files/abc/content'}}]}))

    async def test_owned_image_async(self):
        collector = h.ImageCollector(h.Action.Valves())
        files = SimpleNamespace(get_file_by_id=AsyncMock(return_value=SimpleNamespace(user_id='u', data={'bytes': PNG})))
        with patch.object(h, 'Files', files):
            await collector.prepare([{'content':'![x](/api/v1/files/abc/content)'}], 'u')
        self.assertEqual(collector.resolve_image('/api/v1/files/abc/content')[1:], (1,1))
        files.get_file_by_id.assert_awaited_once()

    async def test_denied_image_never_reads_storage(self):
        collector = h.ImageCollector(h.Action.Valves())
        files = SimpleNamespace(get_file_by_id=AsyncMock(return_value=SimpleNamespace(user_id='other', path='/secret')))
        with patch.object(h, 'Files', files), patch.object(h, 'Users', None), patch.object(collector, '_read_authorized_file') as read:
            await collector.prepare([{'content':'![x](/api/v1/files/abc/content)'}], 'u')
            read.assert_not_called()
        self.assertIsNone(collector.resolve_image('/api/v1/files/abc/content'))

    async def test_shared_image_access(self):
        collector = h.ImageCollector(h.Action.Valves())
        files = SimpleNamespace(get_file_by_id=AsyncMock(return_value=SimpleNamespace(user_id='other', data={'bytes': PNG})))
        users = SimpleNamespace(get_user_by_id=AsyncMock(return_value=SimpleNamespace(id='u')))
        access = AsyncMock(return_value=True)
        with patch.object(h, 'Files', files), patch.object(h, 'Users', users), patch.object(h, 'has_access_to_file', access):
            await collector.prepare([{'content':'![x](/api/v1/files/abc/content)'}], 'u')
        access.assert_awaited_once()
        self.assertIsNotNone(collector.resolve_image('/api/v1/files/abc/content'))

    async def test_image_limits_and_external_urls(self):
        c = h.ImageCollector(h.Action.Valves(MAX_EMBED_IMAGE_MB=1))
        self.assertIsNone(c.resolve_image('https://example.org/private.png'))
        self.assertIsNone(c.resolve_image('data:image/png;base64,' + base64.b64encode(b'x' * 1100000).decode()))
        self.assertIsNone(c.resolve_image('data:image/png;base64,' + base64.b64encode(b'not an image').decode()))
        self.assertEqual(c.skipped, 3)

    async def test_real_hwpx_package(self):
        v = h.Action.Valves()
        c = h.ImageCollector(v)
        body = '# 한글 제목\n\n**굵게** 본문 & <안내>\n\n| 항목 | 값 |\n|---|---|\n| 이름 | 가나 |\n\n![이미지](data:image/png;base64,' + base64.b64encode(PNG).decode() + ')'
        raw = h.build_from_messages([{'role':'assistant','content':body}], '검증 문서', v, c)
        with ZipFile(io.BytesIO(raw)) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.infolist()[0].filename, 'mimetype')
            self.assertEqual(z.infolist()[0].compress_type, ZIP_STORED)
            self.assertEqual(z.read('mimetype'), b'application/hwp+zip')
            for name in z.namelist():
                if name.endswith(('.xml', '.hpf', '.rdf')):
                    etree.fromstring(z.read(name))
            section = z.read('Contents/section0.xml').decode()
            self.assertIn('한글 제목', section)
            self.assertIn('hp:tbl', section)
            self.assertEqual(z.read('BinData/image1.png'), PNG)

    async def test_settings_isolation_and_input_unchanged(self):
        action = h.Action()
        body = {'messages':[{'role':'assistant','content':'본문'}]}
        call = AsyncMock(return_value={'ok':True})
        await action.action(body, {'id':'u','valves':{'include_images':False}}, AsyncMock(), call)
        self.assertTrue(action.valves.include_images)
        self.assertEqual(body, {'messages':[{'role':'assistant','content':'본문'}]})
        call.assert_awaited_once()

    async def test_download_javascript_acknowledgment(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for the browser JS contract test')
        call = AsyncMock(return_value={'ok': True})
        await h.Action().action({'title': '인용 " 및 역슬래시', 'messages': [{'role':'assistant','content':'본문'}]}, {}, AsyncMock(), call)
        code = call.call_args.args[0]['data']['code']
        harness = """
        const code = JSON.parse(process.argv[1]);
        let clicks = 0;
        global.document = {createElement: () => ({click: () => clicks++, remove: () => {}}), body: {appendChild: () => {}}};
        global.setTimeout = fn => fn();
        const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
        new AsyncFunction(code)().then(result => {
            if (!result || result.ok !== true || clicks !== 1) process.exit(1);
        }).catch(() => process.exit(2));
        """
        subprocess.run([node, '-e', harness, json.dumps(code)], check=True, capture_output=True)

    async def test_download_error_no_success(self):
        events=[]
        async def emit(event): events.append(event)
        result = await h.Action().action({'messages':[{'role':'assistant','content':'본문'}]}, {}, emit, AsyncMock(return_value={'error':'disconnected'}))
        self.assertIn('error', result)
        self.assertFalse(any(e.get('data',{}).get('type')=='success' for e in events))
        self.assertTrue(events[-2]['data']['done'])

    async def test_no_browser_or_empty_reply(self):
        a=h.Action()
        self.assertIn('error', await a.action({'messages':[]}, {}, AsyncMock(), None))
        call=AsyncMock()
        self.assertIn('error', await a.action({'messages':[{'role':'user','content':'질문'}]}, {}, AsyncMock(), call))
        call.assert_not_awaited()

    async def test_owned_chat_output_recovery(self):
        chats=SimpleNamespace(get_chat_by_id_and_user_id=AsyncMock(return_value=SimpleNamespace(title='제목')))
        stored=SimpleNamespace(get_message_by_id=AsyncMock(return_value=SimpleNamespace(output=[{'type':'message','content':[{'type':'output_text','text':'복원된 답변'}]}])))
        with patch.object(h,'Chats',chats), patch.object(h,'ChatMessages',stored):
            result=await h.Action().action({'chat_id':'c','messages':[{'id':'m','role':'assistant','content':''}]},{'id':'u'},AsyncMock(),AsyncMock(return_value={'ok':True}))
        self.assertIsNone(result)
        stored.get_message_by_id.assert_awaited_once_with('c-m')

    async def test_unauthorized_chat_not_recovered(self):
        chats=SimpleNamespace(get_chat_by_id_and_user_id=AsyncMock(return_value=None))
        stored=SimpleNamespace(get_message_by_id=AsyncMock())
        with patch.object(h,'Chats',chats), patch.object(h,'ChatMessages',stored):
            result=await h.Action().action({'chat_id':'c','messages':[{'id':'m','role':'assistant','content':''}]},{'id':'u'},AsyncMock(),AsyncMock())
        self.assertIn('error',result)
        stored.get_message_by_id.assert_not_awaited()

if __name__=='__main__':
    unittest.main()
