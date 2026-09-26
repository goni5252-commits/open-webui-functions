"""GPT-6 OCR migration and request behavior, with mocked HTTP only."""
import copy
import unittest
from unittest.mock import AsyncMock
from test_responses import m, completed


class OCRGPT6Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = m.Pipe()

    async def test_saved_settings_migrate_without_mutation(self):
        saved = dict(MODEL_ID='gpt-5.6-ocr,gpt-6-ocr,gpt-5.6-auto',
                     OCR_TERRA_FALLBACK=False, OCR_FALLBACK_MODEL='gpt-5.6-terra')
        before = copy.deepcopy(saved)
        self.pipe.valves = m.Pipe.Valves(**saved)
        self.assertEqual(saved, before)
        self.assertFalse(self.pipe.valves.OCR_SOL_FALLBACK)
        self.assertEqual(self.pipe.valves.OCR_FALLBACK_MODEL, 'gpt-6-sol')
        ids = [p['id'] for p in await self.pipe.pipes()]
        self.assertEqual(ids.count('gpt-6-ocr'), 1)
        self.assertNotIn('gpt-5.6-ocr', ids)
        self.assertIn('gpt-5.6-auto', ids)
        self.assertTrue(m.Pipe.Valves(OCR_SOL_FALLBACK=True, OCR_TERRA_FALLBACK=False).OCR_SOL_FALLBACK)
        self.assertEqual(m.Pipe.Valves(OCR_FALLBACK_MODEL='gpt-5.6-sol').OCR_FALLBACK_MODEL, 'gpt-6-sol')

    async def test_both_aliases_enter_dedicated_path(self):
        self.pipe._run_ocr_model = AsyncMock(return_value='ocr-result')
        self.pipe._route_auto_model_and_reasoning = AsyncMock(side_effect=AssertionError('No smart router'))
        for alias in ('gpt-6-ocr', 'gpt-5.6-ocr'):
            result = await self.pipe._pipe_impl(
                {'model': 'openai_responses.' + alias,
                 'messages': [{'role': 'user', 'content': '전사'}]},
                {'id': 'u'}, None, AsyncMock(), None, {}, {})
            self.assertEqual(result, 'ocr-result')
            self.assertEqual(self.pipe._run_ocr_model.call_args.kwargs['responses_body'].model, 'gpt-6-luna')

    async def run_ocr(self, results, **settings):
        self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(side_effect=results)
        body = m.ResponsesBody(model='gpt-6-ocr', input=[{'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'injected RAG text'},
            {'type': 'input_file', 'file_id': 'file-test'}]}])
        result = await self.pipe._run_ocr_model(responses_body=body,
            valves=m.Pipe.Valves(OCR_REQUIRE_TABLE=False, **settings), event_emitter=None,
            metadata={'user_prompt': '원문을 전사하세요'}, body={}, files_arg=[])
        requests = [call.args[0] for call in self.pipe.send_openai_responses_nonstreaming_request.call_args_list]
        for wire in requests:
            self.assertNotIn('tools', wire)
            self.assertNotIn('injected RAG text', str(wire))
            self.assertEqual(wire['input'][0]['content'][1], {'type':'input_file','file_id':'file-test'})
            self.assertFalse(wire['stream'])
        return result, requests

    async def test_luna_success_does_not_call_sol(self):
        result, calls = await self.run_ocr([completed('원문')])
        self.assertEqual(result, '원문')
        self.assertEqual([c['model'] for c in calls], ['gpt-6-luna'])
        self.assertEqual(calls[0]['reasoning']['effort'], 'low')

    async def test_incomplete_luna_retries_sol(self):
        partial = completed('일부')
        partial['status'] = 'incomplete'
        result, calls = await self.run_ocr([partial, completed('전체 원문')])
        self.assertEqual(result, '전체 원문')
        self.assertEqual([c['model'] for c in calls], ['gpt-6-luna', 'gpt-6-sol'])
        self.assertEqual(calls[1]['reasoning']['effort'], 'medium')

    async def test_saved_disabled_fallback_stays_disabled(self):
        partial = completed('일부')
        partial['status'] = 'incomplete'
        _, calls = await self.run_ocr([partial], OCR_TERRA_FALLBACK=False)
        self.assertEqual(len(calls), 1)

    async def test_pdf_batch_ranges_and_cleanup(self):
        from pathlib import Path
        from unittest.mock import Mock
        self.pipe._resolve_owui_file_records = Mock(return_value=[{'path':Path('/mock/scan.pdf'), 'filename':'scan.pdf'}])
        self.pipe._pdf_page_batches = Mock(return_value=[
            {'data':b'pdf1','filename':'part1.pdf','start_page':1,'end_page':10,'total_pages':11},
            {'data':b'pdf2','filename':'part2.pdf','start_page':11,'end_page':11,'total_pages':11}])
        self.pipe.send_openai_file_upload = AsyncMock(side_effect=[{'id':'one'},{'id':'two'}])
        self.pipe.delete_openai_file = AsyncMock()
        self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(side_effect=[completed('첫 묶음'),completed('둘째 묶음')])
        result = await self.pipe._run_ocr_model(responses_body=m.ResponsesBody(model='gpt-6-ocr',input='전사'),
            valves=m.Pipe.Valves(OCR_REQUIRE_TABLE=False), event_emitter=None,
            metadata={'user_prompt':'전사'},body={},files_arg=[])
        self.assertIn('둘째 묶음', result)
        calls = self.pipe.send_openai_responses_nonstreaming_request.call_args_list
        self.assertIn('11~11', calls[1].args[0]['input'][0]['content'][0]['text'])
        self.assertEqual([c.args[0]['model'] for c in calls], ['gpt-6-luna','gpt-6-luna'])
        self.assertEqual(self.pipe.delete_openai_file.await_count, 2)
