"""Page-threshold PDF routing with real generated PDFs and fake Mistral HTTP."""
import asyncio
import base64
import io
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
import test_native_pdf as native
from test_responses import m, FakeResponse, FakeSession


def pdf_bytes(pages):
    writer = m.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def ocr_payload(pages=2):
    return {'pages': [{'index': i, 'markdown': f'문서 {i + 1}\n|A|B|\n|-|-|\n|1|2|'} for i in range(pages)]}


class HybridPdfTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native.NativePdfTests.asyncSetUp
    inject = native.NativePdfTests.inject

    async def test_boundary_49_50_and_native_replay_removed(self):
        self.assertEqual(m.Pipe.Valves().PDF_MISTRAL_PAGE_THRESHOLD, 50)
        self.pipe._mistral_pdf_text = AsyncMock(return_value='[페이지 1]\nOCR 본문')
        for pages in (49, 50):
            with self.subTest(pages=pages):
                self.pipe._mistral_pdf_text.reset_mock()
                raw = pdf_bytes(pages)
                self.path.write_bytes(raw)
                value = [{'role': 'user', 'content': [{'type':'input_text', 'text':'읽어줘'},
                    {'type':'input_file','filename':'scan.PDF',
                     'file_data':'data:application/pdf;base64,' + base64.b64encode(raw).decode()}]}]
                result = await self.inject([{'id':'pdf'}], value=value, PDF_MISTRAL_PAGE_THRESHOLD=50)
                blocks = result.input[-1]['content']
                if pages == 49:
                    self.pipe._mistral_pdf_text.assert_not_called()
                    self.assertEqual(sum(b['type']=='input_file' for b in blocks), 1)
                else:
                    self.pipe._mistral_pdf_text.assert_awaited_once()
                    self.assertFalse(any(b['type']=='input_file' for b in blocks))
                    self.assertIn('OCR 본문', blocks[-1]['text'])
                    self.assertEqual(blocks[0]['text'], '읽어줘')

    async def test_long_pdf_text_reaches_normal_pipe(self):
        self.path.write_bytes(pdf_bytes(50))
        self.pipe.valves.PDF_MISTRAL_PAGE_THRESHOLD = 50
        self.pipe.valves.HWPX_NATIVE_PARSER = False
        self.pipe.valves.ENABLE_CONVERSATION_IMAGES = False
        self.pipe._mistral_pdf_text = AsyncMock(return_value='[페이지 1] OCR 결과')
        self.pipe._run_nonstreaming_loop = AsyncMock(return_value='ok')
        result = await self.pipe._pipe_impl(
            {'model':'gpt-6.1-sol','messages':[{'role':'user','content':'read'}], 'stream':False},
            {'id':'u','email':'u@test'}, None, AsyncMock(), None, {}, {}, [{'id':'pdf'}])
        self.assertEqual(result, 'ok')
        response = self.pipe._run_nonstreaming_loop.call_args.args[0]
        self.assertIn('OCR 결과', str(response.input))
        self.assertNotIn('input_file', str(response.input))

    async def test_threshold_applies_per_file_not_sum(self):
        self.path.write_bytes(pdf_bytes(30))
        self.pipe._mistral_pdf_text = AsyncMock()
        result = await self.inject([{'id':'pdf'}, {'id':'mime'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        self.assertEqual(sum(b['type']=='input_file' for b in result.input[-1]['content']), 2)
        self.pipe._mistral_pdf_text.assert_not_called()

    async def test_mixed_short_and_long(self):
        self.path.write_bytes(pdf_bytes(49))
        long_path = self.path.with_name('long.pdf')
        long_path.write_bytes(pdf_bytes(50))
        self.records['mime'].path = 'long-key'
        self.storage.side_effect = lambda key: str(long_path if key == 'long-key' else self.path)
        self.pipe._mistral_pdf_text = AsyncMock(return_value='long OCR')
        result = await self.inject([{'id':'pdf'}, {'id':'mime'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        blocks = result.input[-1]['content']
        self.assertEqual(sum(b['type']=='input_file' for b in blocks), 1)
        self.assertIn('long OCR', blocks[-1]['text'])
        self.pipe._mistral_pdf_text.assert_awaited_once()

    async def test_zero_threshold_preserves_long_original(self):
        self.path.write_bytes(pdf_bytes(50))
        self.pipe._mistral_pdf_text = AsyncMock()
        result = await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=0)
        self.assertEqual(result.input[-1]['content'][-1]['type'], 'input_file')
        self.pipe._mistral_pdf_text.assert_not_called()

    async def test_ocr_failure_does_not_fall_back_to_native(self):
        self.path.write_bytes(pdf_bytes(50))
        self.pipe._mistral_pdf_text = AsyncMock(side_effect=ValueError('OCR failed'))
        with self.assertRaisesRegex(ValueError, 'OCR failed'):
            await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)

    async def test_page_count_failure_is_explicit(self):
        with self.assertRaisesRegex(ValueError, '페이지 수'):
            await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        with patch.object(m, 'PdfReader', None):
            with self.assertRaisesRegex(ValueError, 'pypdf'):
                await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)

    async def test_encrypted_pdf_rejected_before_ocr(self):
        writer = m.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.encrypt('password')
        output = io.BytesIO()
        writer.write(output)
        self.path.write_bytes(output.getvalue())
        self.pipe._mistral_pdf_text = AsyncMock()
        with self.assertRaisesRegex(ValueError, '암호화'):
            await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        self.pipe._mistral_pdf_text.assert_not_called()

    async def test_acl_rechecked_for_cached_ocr(self):
        self.path.write_bytes(pdf_bytes(50))
        self.pipe._mistral_pdf_text = AsyncMock(return_value='cached OCR')
        await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        self.records['pdf'].user_id = 'other'
        with self.assertRaisesRegex(ValueError, '접근'):
            await self.inject([{'id':'pdf'}], PDF_MISTRAL_PAGE_THRESHOLD=50)
        self.pipe._mistral_pdf_text.assert_awaited_once()


class MistralTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pipe = m.Pipe()
        self.valves = m.Pipe.Valves(PDF_MISTRAL_API_KEY='test-only-key')
        self.data = pdf_bytes(2)
        self.session = FakeSession(FakeResponse(chunks=[json.dumps(ocr_payload()).encode()]))
        self.pipe._get_or_init_http_session = AsyncMock(return_value=self.session)

    async def call(self, user='u', data=None, valves=None):
        return await self.pipe._mistral_pdf_text(data or self.data, 2, user, valves or self.valves)

    async def test_request_bytes_markdown_and_cache_reuse(self):
        text = await self.call()
        self.assertIn('[페이지 2]', text)
        self.assertIn('|A|B|', text)
        url, request = self.session.calls[0]
        self.assertEqual(url, 'https://api.mistral.ai/v1/ocr')
        self.assertEqual(request['headers']['Authorization'], 'Bearer test-only-key')
        self.assertFalse(request['json']['include_image_base64'])
        self.assertFalse(request['allow_redirects'])
        encoded = request['json']['document']['document_url'].split(',', 1)[1]
        self.assertEqual(base64.b64decode(encoded), self.data)
        self.assertEqual(await self.call(), text)
        self.assertEqual(len(self.session.calls), 1)

    async def test_concurrent_duplicate_only_charged_once(self):
        results = await asyncio.gather(self.call(), self.call())
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.session.calls), 1)

    async def test_cache_scope_invalidation_and_bound(self):
        await self.call()
        await self.call(user='other')
        await self.call(data=self.data + b'\n')
        await self.call(valves=self.valves.model_copy(update={'PDF_MISTRAL_MODEL':'other-model'}))
        await self.call(valves=self.valves.model_copy(update={'PDF_MISTRAL_API_KEY':'other-key'}))
        self.assertEqual(len(self.session.calls), 5)
        for user in range(10):
            await self.call(user=str(user))
        self.assertEqual(len(self.pipe._pdf_ocr_cache), 8)

    async def test_cache_expiry(self):
        await self.call()
        self.pipe._pdf_ocr_cache = {k: (m.perf_counter()-1801, text)
                                    for k, (_, text) in self.pipe._pdf_ocr_cache.items()}
        await self.call()
        self.assertEqual(len(self.session.calls), 2)

    async def test_missing_key_and_environment_key(self):
        valves = self.valves.model_copy(update={'PDF_MISTRAL_API_KEY':''})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'PDF_MISTRAL_API_KEY'):
                await self.call(valves=valves)
        self.assertFalse(self.session.calls)
        with patch.dict(os.environ, {'MISTRAL_API_KEY':'env-test-only'}):
            await self.call(valves=valves)
        self.assertEqual(self.session.calls[0][1]['headers']['Authorization'], 'Bearer env-test-only')

    async def test_http_error_and_cancellation_not_cached(self):
        self.session.response.status = 401
        with self.assertRaises(ValueError):
            await self.call()
        self.assertFalse(self.pipe._pdf_ocr_cache)
        self.pipe._get_or_init_http_session.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.call()
        self.assertFalse(self.pipe._pdf_ocr_cache)

    async def test_bad_partial_duplicate_empty_responses_not_cached(self):
        for payload in ({}, {'pages':[]}, {'pages':[{'index':0,'markdown':'a'}]},
                        {'pages':[{'index':0,'markdown':'a'},{'index':0,'markdown':'b'}]},
                        {'pages':[{'index':0,'markdown':''},{'index':1,'markdown':''}]},
                        {'pages':[{'index':0,'markdown':None},{'index':1,'markdown':'b'}]}):
            with self.subTest(payload=payload):
                self.session.response.chunks = [json.dumps(payload).encode()]
                with self.assertRaises(ValueError):
                    await self.call()
                self.assertFalse(self.pipe._pdf_ocr_cache)
        self.session.response.chunks = [b'invalid json']
        with self.assertRaises(ValueError):
            await self.call()

    async def test_response_size_and_text_limit(self):
        self.session.response.chunks = [b'x' * 8_000_001]
        with self.assertRaises(ValueError):
            await self.call()
        payload = ocr_payload()
        payload['pages'][0]['markdown'] = 'x' * 1_000_001
        self.session.response.chunks = [json.dumps(payload).encode()]
        with self.assertRaisesRegex(ValueError, '임의로 자르지'):
            await self.call()
        self.assertFalse(self.pipe._pdf_ocr_cache)
