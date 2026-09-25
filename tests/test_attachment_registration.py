import ast
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from test_responses import m

class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, tools, enabled=True, task=None):
        pipe=m.Pipe()
        pipe.valves.ENABLE_TERMINAL_ATTACHMENT_TRANSFER=enabled
        pipe._pipe_impl=AsyncMock(return_value='normal response')
        emitter=AsyncMock()
        result=await pipe.pipe({'messages':[]},{'id':'u'},None,emitter,None,{'chat_id':'c'},tools,[],task)
        self.assertEqual(result,'normal response')
        return pipe._pipe_impl.call_args.args[6]

    async def test_admin_gets_tools_without_eager_copy(self):
        tools={'run_command':{'type':'terminal','tool_id':'terminal:one','callable':AsyncMock()}}
        registry=await self.check(tools)
        self.assertIn('prepare_terminal_files',registry)
        self.assertIn('list_chat_attachments',registry)
        self.assertIn('_terminal_bridge',registry['run_command'])
        tools['run_command']['callable'].assert_not_called()

    async def test_disabled_leaves_terminal_bridge(self):
        registry=await self.check({'x':{'type':'terminal','tool_id':'terminal:one'}},False)
        self.assertNotIn('prepare_terminal_files',registry)
        self.assertIn('_terminal_bridge',registry['x'])

    async def test_no_terminal_does_not_add_tools(self):
        registry=await self.check({'x':{'type':'mcp'}})
        self.assertNotIn('prepare_terminal_files',registry)

    async def test_direct_only_unchanged(self):
        registry=await self.check({'x':{'type':'terminal','direct':True}})
        self.assertNotIn('prepare_terminal_files',registry)

    async def test_background_task_unchanged(self):
        registry=await self.check({'x':{'type':'terminal','tool_id':'terminal:one'}},task={'type':'title'})
        self.assertNotIn('prepare_terminal_files',registry)

    async def test_both_tool_schemas_are_callable(self):
        registry=await self.check({'x':{'type':'terminal','tool_id':'terminal:one'}})
        specs=m.ResponsesBody.transform_owui_tools(registry, strict=True)
        specs={s['name']:s for s in specs}
        self.assertTrue(specs['prepare_terminal_files']['strict'])
        self.assertEqual(set(specs['prepare_terminal_files']['parameters']['required']),{'file_ids','purpose'})

    def test_original_functions_preserved(self):
        original=Path(__file__).resolve().parents[1]/'function-openai_responses-v1.7.4.json'
        new=Path(m.__file__).read_text()
        def functions(text):
            out={}
            def visit(nodes,prefix=''):
                for n in nodes:
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        out[prefix+n.name]=ast.dump(n,include_attributes=False)
                    elif isinstance(n,ast.ClassDef): visit(n.body,prefix+n.name+'.')
            visit(ast.parse(text).body)
            return out
        before,after=functions(json.loads(original.read_text())[0]["content"]),functions(new)
        changed={k for k,v in before.items() if after.get(k)!=v}
        self.assertEqual(changed,{'Pipe.pipe','Pipe._pipe_impl'})

if __name__=='__main__': unittest.main()
