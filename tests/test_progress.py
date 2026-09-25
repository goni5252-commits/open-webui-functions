import unittest
from unittest.mock import AsyncMock
from test_responses import m, completed


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_notice_once_per_silent_period(self):
        emitter = AsyncMock()
        display = m._ProgressDisplay(emitter)
        t = display.last_activity
        await display.idle_notice(t+44)
        emitter.assert_not_called()
        await display.idle_notice(t+45)
        await display.idle_notice(t+100)
        self.assertEqual(emitter.await_count, 1)
        await display.emit({'type':'chat:message', 'data':{'content':'progress'}})
        await display.idle_notice(display.last_activity+46)
        self.assertEqual(emitter.await_count, 3)

    async def test_compact_keeps_card_and_errors_and_does_not_mutate_input(self):
        emitter = AsyncMock()
        display = m._ProgressDisplay(emitter)
        status = {'type':'status', 'data':{'description':'Running the run_command tool…\nlarge code'}}
        await display.emit(status)
        self.assertEqual(emitter.call_args.args[0]['data']['description'], '도구 실행 · run_command')
        self.assertIn('large code', status['data']['description'])
        await display.emit({'type':'status', 'data':{'description':'Received tool result\nlarge result'}})
        self.assertEqual(emitter.await_count, 1)
        for event in ({'type':'chat:completion', 'data':{'output':[{'type':'file','path':'a.pptx'}]}},
                      {'type':'status','data':{'description':'실패\n상세 오류', 'done':True}},
                      {'type':'status','data':{'description':'Searching','action':'web_search_queries_generated','queries':['a']}}):
            await display.emit(event)
            self.assertEqual(emitter.call_args.args[0], event)

    async def test_detailed_status_is_unchanged(self):
        emitter = AsyncMock()
        event = {'type':'status', 'data':{'description':'Received tool result\nlarge result'}}
        await m._ProgressDisplay(emitter, False).emit(event)
        self.assertEqual(emitter.call_args.args[0], event)

    async def test_lifecycle_pair_and_tool_continuation(self):
        for compact, expected in ((True, 1), (False, 2)):
            pipe = m.Pipe()
            count = 0
            call = {'type':'function_call','id':'fc','call_id':'c','name':'echo','arguments':'{}'}
            async def stream(*args, **kwargs):
                nonlocal count
                count += 1
                yield {'type':'response.created'}
                yield {'type':'response.in_progress'}
                yield {'type':'response.in_progress'}
                yield {'type':'response.completed', 'response': {'status':'completed','output':[call]} if count == 1 else completed('done')}
            pipe.send_openai_responses_streaming_request = stream
            pipe._execute_function_calls = AsyncMock(return_value=[{'type':'function_call_output','call_id':'c','output':'ok'}])
            emitter = AsyncMock()
            result = await pipe._run_streaming_loop(m.ResponsesBody(model='gpt-6-sol', input='test', stream=True), m.Pipe.Valves(COMPACT_STATUS_UPDATES=compact, PERSIST_TOOL_RESULTS=False), emitter)
            self.assertEqual(result, 'done')
            notices = [c.args[0] for c in emitter.call_args_list if c.args[0].get('data',{}).get('description') == '응답을 작성하고 있습니다…']
            self.assertEqual(len(notices), expected)
            self.assertTrue(any(c.args[0].get('data',{}).get('done') for c in emitter.call_args_list))
