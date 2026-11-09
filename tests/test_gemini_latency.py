"""Attachment latency regressions; real SDK config, mocked network/storage."""
import copy
import json
import logging
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import test_conversation_images as helpers

Gemini, DATA = helpers.Gemini, helpers.DATA


def pipe():
    result = object.__new__(Gemini)
    result.valves = Gemini.Valves()
    result.log = logging.getLogger('gemini-latency')
    return result


def body(text='그럼 이렇게 설명해도 되는걸까'):
    return {'model': 'gemini-3.8-flash', 'stream': True, 'messages': [
        {'role': 'user', 'content': [{'type': 'text', 'text': text},
         {'type': 'image_url', 'image_url': {'url': '/api/v1/files/abc/content'}}]}],
        'files': [{'id': 'abc', 'type': 'image', 'content_type': 'image/png'}]}


class AttachmentRoutingTests(unittest.TestCase):
    def test_same_file_aliases_count_once_and_keep_low(self):
        p = pipe()
        b = body()
        b['metadata'] = {'files': [{'type': 'file', 'file': {'id': 'abc', 'meta': {'content_type': 'image/png'}}}]}
        self.assertEqual(p._count_request_attachments(b), (1, 1, 0))
        self.assertEqual(p._select_auto_thinking_level(b, b['model'])[0], 'low')
        b['files'].append({'id': 'different', 'content_type': 'image/png'})
        self.assertEqual(p._count_request_attachments(b), (2, 2, 0))

    def test_image_block_supplies_type_when_file_metadata_has_no_mime(self):
        p = pipe()
        b = body()
        b['files'] = [{'id': 'abc', 'type': 'file'}]
        self.assertEqual(p._count_request_attachments(b), (1, 1, 0))
        self.assertEqual(p._select_auto_thinking_level(b, b['model'])[0], 'low')

    def test_old_document_does_not_promote_current_thanks(self):
        p = pipe()
        b = {'messages': [{'role': 'user', 'content': '분석', 'files': [
            {'id': 'old', 'content_type': 'application/pdf'}]},
            {'role': 'assistant', 'content': '답변'}, {'role': 'user', 'content': '고마워'}]}
        self.assertEqual(p._select_auto_thinking_level(b, 'gemini-3.8-flash')[0], 'low')
        b['messages'][-1]['content'] = '정리를 엄밀하게 증명해줘'
        self.assertEqual(p._select_auto_thinking_level(b, 'gemini-3.8-flash')[0], 'high')

    def test_current_pdf_keeps_analysis_level_and_collections_normalize(self):
        p = pipe()
        b = {'messages': [{'role': 'user', 'content': '비교해줘'}], 'files': [
            {'type': 'collection', 'files': [{'id': 'pdf', 'content_type': 'application/pdf'}]}]}
        self.assertEqual(p._count_request_attachments(b), (1, 0, 1))
        self.assertEqual(p._select_auto_thinking_level(b, 'gemini-3.8-flash')[0], 'medium')

    def test_reading_vs_edit_followup(self):
        p = pipe()
        session = SimpleNamespace(entries={'image': {'role': 'user'}})
        for question in ('그럼 이렇게 설명해도 되는걸까', '이 문제 풀어줘', '고마워', '이미지 분석해줘'):
            self.assertFalse(p._needs_conversation_images(body(question), session), question)
        for question in ('배경만 파랗게 바꿔줘', '이번에는 수채화로', 'a little warmer', '고양이를 그려줘'):
            self.assertTrue(p._needs_conversation_images(body(question), session), question)


class PayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_image_and_file_id_share_identity_after_preparation(self):
        p = pipe()
        p._optimize_image_for_api = lambda url: url
        p._load_owui_file = AsyncMock(return_value=(b'\x89PNG\r\n\x1a\noriginal-image-bytes', None))
        b = body()
        b['messages'][0]['content'][1]['image_url']['url'] = DATA
        metadata = {'files': b['files']}
        result, _ = await p._prepare_content(b['messages'], metadata)
        self.assertEqual(sum('inline_data' in part for part in result[0]['parts']), 1)
        self.assertEqual(p._count_request_attachments(b, metadata), (1, 1, 0))
        self.assertEqual(p._select_auto_thinking_level(b, b['model'], metadata)[0], 'low')

    async def test_dedup_current_media_preserves_history_text_and_original(self):
        p = pipe()
        p._optimize_image_for_api = lambda url: url
        p._load_owui_file = AsyncMock(return_value=(b'\x89PNG\r\n\x1a\noriginal-image-bytes', None))
        p._fetch_file_as_base64 = AsyncMock(return_value=DATA)
        b = body()
        b['messages'].insert(0, {'role': 'user', 'content': [
            {'type': 'text', 'text': '이전 자료'}, {'type': 'image_url', 'image_url': {'url': '/files/abc'}}]})
        original = copy.deepcopy(b)
        result, _ = await p._prepare_content(b['messages'], {'files': b['files']})
        self.assertEqual(b, original)
        self.assertEqual([sum('inline_data' in part for part in turn['parts']) for turn in result], [1, 1])
        self.assertEqual(result[0]['parts'][0]['text'], '이전 자료')
        self.assertTrue(any(part.get('text') == '그럼 이렇게 설명해도 되는걸까' for part in result[-1]['parts']))
        p._fetch_file_as_base64.assert_awaited_once()

    def test_identical_bytes_and_base64_dedup_but_distinct_images_remain(self):
        a = {'inline_data': {'mime_type': 'image/png', 'data': b'abc'}}
        b = {'inline_data': {'mime_type': 'image/png', 'data': 'YWJj'}}
        c = {'inline_data': {'mime_type': 'image/png', 'data': b'different'}}
        text = {'text': 'compare'}
        self.assertEqual(Gemini._deduplicate_media_parts([a, text, b, c]), [a, text, c])

    async def test_usage_and_timings_logged_even_without_ui_status(self):
        p = pipe()
        p.valves.LIVE_PROGRESS_STATUS = False
        p.log = Mock()
        usage = p._build_usage_dict(SimpleNamespace(prompt_token_count=100, candidates_token_count=20,
            thoughts_token_count=40, total_token_count=167, cached_content_token_count=10))
        self.assertEqual(usage['total_tokens'], 167)
        self.assertEqual(usage['completion_tokens'], 60)
        self.assertEqual(usage['completion_tokens_details']['reasoning_tokens'], 40)
        self.assertEqual(usage['prompt_tokens_details']['cached_tokens'], 10)
        now = time.perf_counter()
        timing = {'api_started_at': now-3, 'prepare_s': 1, 'streaming': True}
        await p._finish_progress_timing(None, started_at=now-4, first_visible_at=now-1,
            reasoning_level='low', timing=timing, usage=usage)
        record = json.loads(p.log.info.call_args.args[1])
        self.assertEqual(record['first_answer_s'], 3)
        self.assertEqual(record['api_to_first_answer_s'], 2)
        self.assertEqual(record['usage'], usage)
        self.assertIn('api_started_at', timing)

    async def test_ui_labels_total_time_truthfully(self):
        p = pipe()
        emitter = AsyncMock()
        await p._finish_progress_timing(emitter, started_at=time.perf_counter()-4,
            reasoning_level='low', first_visible_at=time.perf_counter()-2)
        description = emitter.call_args.args[0]['data']['description']
        self.assertIn('총 처리', description)
        self.assertIn('첫 응답', description)
        self.assertNotIn('Thought for', description)


class AttachmentPipelineTests(unittest.IsolatedAsyncioTestCase):
    setUp = helpers.GeminiFullPipelineTests.setUp
    asyncTearDown = helpers.GeminiFullPipelineTests.asyncTearDown

    async def test_screenshot_question_streams_with_low_and_no_image_tool(self):
        self.pipe.valves.AUTO_THINKING = True
        chunks = object()
        streaming = AsyncMock(return_value=chunks)
        self.pipe._handle_streaming_response = lambda iterator, *a, **kw: iterator
        with patch.object(self.client.aio.models, 'generate_content_stream', streaming), patch.object(
                self.client.aio.models, 'generate_content', AsyncMock()) as nonstream:
            result = await self.pipe.pipe(body())
        self.assertIs(result, chunks)
        nonstream.assert_not_awaited()
        config = streaming.call_args.kwargs['config']
        self.assertFalse(any(callable(t) for t in config.tools or []))
        self.assertEqual(config.thinking_config.thinking_level.value.lower(), 'low')
        self.image_api.assert_not_awaited()

    async def test_explicit_reasoning_wins_over_attachment_router(self):
        self.pipe.valves.AUTO_THINKING = True
        b = body()
        b['reasoning_effort'] = 'high'
        streaming = AsyncMock(return_value=object())
        self.pipe._handle_streaming_response = lambda iterator, *a, **kw: iterator
        with patch.object(self.client.aio.models, 'generate_content_stream', streaming):
            await self.pipe.pipe(b)
        self.assertEqual(streaming.call_args.kwargs['config'].thinking_config.thinking_level.value.lower(), 'high')
