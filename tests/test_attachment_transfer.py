"""Offline binary-transfer tests; fake only WebUI DB/storage/proxy boundaries."""
import ast
import asyncio
import hashlib
import inspect
import json
import re
import sys
import tempfile
import types
import unittest
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import AsyncMock, Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'functions/openai_responses.py'
ns = dict(asyncio=asyncio, json=json, re=re)
async def maybe(value):
    return await value if inspect.isawaitable(value) else value
ns['_maybe_await'] = maybe
for node in ast.parse(SOURCE.read_text()).body:
    if getattr(node, 'name', '') in ('_TerminalAttachmentTransfer', '_is_terminal_tool'):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
Transfer = ns['_TerminalAttachmentTransfer']

class Request:
    def __init__(self, scope, receive=None):
        self.scope, self.receive = scope, receive
    async def body(self):
        return (await self.receive())['body']

class Response:
    def __init__(self, value=None, status=200, raw=None, stream=False):
        self.status_code = status
        self.background = AsyncMock()
        data = raw if raw is not None else json.dumps(value).encode()
        if stream:
            async def chunks():
                for i in range(0, len(data), 7):
                    yield data[i:i+7]
            self.body_iterator = chunks()
        else:
            self.body = data

class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = types.SimpleNamespace(id='user-a', role='user')
        self.chat = types.SimpleNamespace(user_id='user-a', chat={'history': {
            'currentId': 'assistant', 'messages': {
                'old': {'role':'user', 'files':[{'id':'old-file', 'type':'file'}], 'parentId':None},
                'assistant': {'role':'assistant', 'parentId':'old'},
                'sibling': {'role':'user', 'files':[{'id':'sibling-file', 'type':'file'}]},
            }}})
        self.records = {}
        for fid in ('new-file', 'old-file', 'sibling-file', 'forbidden'):
            path = Path(self.tmp.name) / fid
            path.write_bytes(b'PK\x03\x04\x00\xff\r\n' + fid.encode())
            self.records[fid] = types.SimpleNamespace(
                filename='학교 양식.hwpx', user_id='other' if fid == 'forbidden' else 'user-a', path=str(path))
        self.db_get = AsyncMock(side_effect=lambda fid:self.records.get(fid))
        self.access = AsyncMock(return_value=False)
        self.storage_get = Mock(side_effect=lambda p:p)
        self.get_chat = AsyncMock(side_effect=lambda cid:self.chat)
        self.get_allowed_chat = AsyncMock(return_value=None)
        def mod(name, **attrs):
            obj = types.ModuleType(name)
            obj.__dict__.update(attrs)
            return obj
        modules = {
            'open_webui.models.users': mod('users', Users=types.SimpleNamespace(get_user_by_id=AsyncMock(return_value=self.user))),
            'open_webui.models.chats': mod('chats', Chats=types.SimpleNamespace(get_chat_by_id=self.get_chat, get_chat_by_id_for_user=self.get_allowed_chat)),
            'open_webui.models.files': mod('files', Files=types.SimpleNamespace(get_file_by_id=self.db_get)),
            'open_webui.utils.access_control.files': mod('access', has_access_to_file=self.access),
            'open_webui.storage.provider': mod('storage', Storage=types.SimpleNamespace(get_file=self.storage_get)),
            'starlette.requests': mod('requests', Request=Request),
            'open_webui.routers.terminals': mod('terminals', proxy_terminal=self.proxy),
        }
        self.patcher=patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.remote, self.calls, self.responses = {}, [], []
        self.http_status, self.corrupt, self.bad_ack, self.fail_second = None, False, False, False
        self.emit=AsyncMock()
        self.request=Request({'type':'http','headers':[(b'authorization', b'Bearer user-session'), (b'cookie', b'oauth_session_id=test')],
                              'state': {'token': 'original'}, 'app':'original-app', 'query_string':b'old=discard'})
        self.t=Transfer(self.request, {'id':'user-a'}, {'chat_id':'chat-a'}, {'messages':[]},
                        [{'id':'new-file','type':'file', 'path':'/etc/passwd'}],
                        {'run_command':{'type':'terminal','tool_id':'terminal:server-a'}},
                        types.SimpleNamespace(TERMINAL_ATTACHMENT_MAX_MB=1),self.emit)

    async def proxy(self, server_id, path, request, user):
        headers=dict(request.scope['headers'])
        self.assertEqual(headers[b'x-session-id'], b'chat-a')
        self.assertEqual(headers[b'authorization'], b'Bearer user-session')
        self.assertEqual(request.scope['app'], 'original-app')
        self.assertIs(request.scope['state'], self.request.scope['state'])
        self.assertIs(user,self.user)
        self.assertEqual(server_id,'server-a')
        query={k:v[0] for k,v in parse_qs(request.scope['query_string'].decode()).items()}
        self.assertNotIn('old',query)
        method=request.scope['method']
        self.calls.append((method,path,query))
        if self.http_status:
            r=Response({'error':'secret upstream text'},status=self.http_status)
        elif path=='files/cwd':
            r=Response({'home':'/home/user-a','cwd':'/some/other/directory'})
        elif path=='files/view':
            data=self.remote.get(query['path'])
            r=Response(raw=data,stream=True) if data is not None else Response({},status=404)
        elif path=='files/upload':
            data=await request.body()
            self.assertEqual(int(headers[b'content-length']),len(data))
            parsed=BytesParser(policy=default).parsebytes(b'Content-Type: '+headers[b'content-type']+b'\r\n\r\n'+data)
            parts=list(parsed.iter_parts())
            self.assertEqual(len(parts),1)
            part=parts[0]
            self.assertEqual(part.get_param('name',header='content-disposition'),'file')
            name=part.get_filename()
            target=query['directory']+'/'+name
            raw=part.get_payload(decode=True)
            self.remote[target]=raw+b'bad' if self.corrupt else raw
            r=Response({'path':target, 'size':len(raw)+(1 if self.bad_ack else 0)})
        else:
            raise AssertionError(path)
        self.responses.append(r)
        return r

    async def prepare(self, ids=None):
        return json.loads(await self.t.prepare(ids or ['new-file'],'첨부 원본 양식의 서식을 보존하여 새 파일 생성'))

    async def test_list_reads_metadata_only_and_includes_ancestry(self):
        result=json.loads(await self.t.list_files())
        self.assertEqual({f['file_id'] for f in result['files']},{'new-file','old-file'})
        self.assertFalse(result['transferred'])
        self.storage_get.assert_not_called()
        self.assertEqual(self.calls,[])

    async def test_binary_exact_multipart_proxy_and_cleanup(self):
        result=await self.prepare()
        self.assertTrue(result['ok'],result)
        f=result['files'][0]
        self.assertEqual(self.remote[f['path']],Path(self.records['new-file'].path).read_bytes())
        self.assertEqual(f['filename'],'학교 양식.hwpx')
        self.assertIn('/.openwebui-attachments/',f['path'])
        self.assertNotIn('/etc/passwd',self.storage_get.call_args.args)
        self.assertTrue(all(r.background.await_count==1 for r in self.responses))

    async def test_second_request_reuses_verified_binary(self):
        await self.prepare()
        # New request-local instance; no in-memory transfer cache required.
        self.t=Transfer(self.request,self.t.user_info,self.t.metadata,self.t.body,self.t.files,self.t.registry,self.t.valves,self.emit)
        result=await self.prepare()
        self.assertTrue(result['files'][0]['reused'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_deleted_or_modified_remote_reuploaded(self):
        f=(await self.prepare())['files'][0]
        self.remote[f['path']]=b'x'*f['size']
        result=await self.prepare()
        self.assertTrue(result['ok'])
        self.assertFalse(result['files'][0]['reused'])
        self.remote.clear()
        self.assertTrue((await self.prepare())['ok'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),3)

    async def test_followup_prior_attachment_only(self):
        self.t.files=[]
        result=await self.prepare(['old-file'])
        self.assertTrue(result['ok'])
        self.assertEqual([f['file_id'] for f in result['files']],['old-file'])

    async def test_sibling_or_arbitrary_id_rejected_before_storage(self):
        for fid in ('sibling-file','not-in-chat','../../etc/passwd'):
            self.assertFalse((await self.prepare([fid]))['ok'])
        self.storage_get.assert_not_called()
        self.assertEqual(self.calls,[])

    async def test_inaccessible_file_hidden_and_rejected(self):
        self.t.files.append({'id':'forbidden','type':'file'})
        result=json.loads(await self.t.list_files())
        self.assertNotIn('forbidden',str(result))
        self.assertFalse((await self.prepare(['forbidden']))['ok'])
        self.storage_get.assert_not_called()

    async def test_permission_revoked_after_listing(self):
        await self.t.list_files()
        self.records['new-file'].user_id='other'
        self.assertFalse((await self.prepare())['ok'])
        self.storage_get.assert_not_called()

    async def test_other_chat_denied(self):
        self.chat.user_id='other'
        self.assertFalse((await self.prepare())['ok'])
        self.storage_get.assert_not_called()

    async def test_temporary_chat_denied(self):
        self.t.metadata['chat_id']='local:test'
        self.assertFalse((await self.prepare())['ok'])
        self.assertEqual(self.calls,[])

    async def test_no_or_ambiguous_or_direct_terminal_denied(self):
        registries=[{}, {'x':{'type':'terminal','direct':True,'tool_id':'terminal:server-a'}},
                    {'x':{'type':'terminal','tool_id':'terminal:server-a'},'y':{'type':'terminal','tool_id':'terminal:server-b'}}]
        for registry in registries:
            self.t.registry=registry
            self.assertFalse((await self.prepare())['ok'])
        self.storage_get.assert_not_called()

    async def test_native_proxy_acl_failure_no_secret_in_result(self):
        self.http_status=403
        result=await self.prepare()
        self.assertFalse(result['ok'])
        self.assertIn('403',result['error'])
        self.assertNotIn('secret',str(result))
        self.storage_get.assert_not_called()

    async def test_corrupt_transfer_never_reported_success(self):
        self.corrupt=True
        result=await self.prepare()
        self.assertFalse(result['ok'])
        self.assertEqual(result['prepared_files'],[])

    async def test_wrong_ack_rejected(self):
        self.bad_ack=True
        self.assertFalse((await self.prepare())['ok'])

    async def test_size_limit(self):
        Path(self.records['new-file'].path).write_bytes(b'x'*(1024*1024+1))
        self.assertFalse((await self.prepare())['ok'])
        self.assertFalse(any(c[0]=='POST' for c in self.calls))

    async def test_empty_file(self):
        Path(self.records['new-file'].path).write_bytes(b'')
        self.assertFalse((await self.prepare())['ok'])

    async def test_duplicates_transfer_once_and_filenames_sanitized(self):
        self.records['new-file'].filename='../"학교\r\n'+'긴'*100+'.hwpx'
        result=await self.prepare(['new-file','new-file'])
        self.assertTrue(result['ok'],result)
        path=result['files'][0]['path']
        name=path.rsplit('/',1)[-1]
        self.assertNotIn('"',name)
        self.assertNotIn('\n',name)
        self.assertLess(len(name.encode()),255)
        self.assertEqual(len(result['files']),1)

    async def test_invalid_request(self):
        for ids,purpose in [([], 'x'), (['x']*6,'x'), ('new-file','x'), ([None],'x'), (['new-file'],'')]:
            self.assertFalse(json.loads(await self.t.prepare(ids,purpose))['ok'])
        self.assertEqual(self.calls,[])

    async def test_parallel_prepare_serializes_and_deduplicates(self):
        a,b=await asyncio.gather(self.prepare(),self.prepare())
        self.assertTrue(a['ok'] and b['ok'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    async def test_cancellation_propagates(self):
        self.t._catalog=AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.t.prepare(['new-file'],'task')

    async def test_active_body_branch_preferred(self):
        self.t.body['messages']=[{'id':'sibling','role':'user'}]
        result=json.loads(await self.t.list_files())
        self.assertEqual({f['file_id'] for f in result['files']},{'new-file','sibling-file'})

if __name__=='__main__': unittest.main()
