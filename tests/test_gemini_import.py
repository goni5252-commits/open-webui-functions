"""Offline tests of imported Gemini helpers; no SDK/server or API calls.

Compile selected original methods via AST to isolate their behavior from server
dependencies. These tests do not validate full Pipe initialization/integration.
"""
import ast
import base64
import io
import logging
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
import unittest
from unittest.mock import AsyncMock
import xml.etree.ElementTree as ET
import zipfile


def helper_pipe():
    source = Path(__file__).resolve().parents[1] / 'functions/google_gemini.py'
    tree = ast.parse(source.read_text())
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Pipe')
    names = {'_is_hwpx_document', '_hwpx_local_name', '_validate_hwpx_archive',
             '_extract_hwpx_text', '_build_rag_bypass_parts'}
    methods = [n for n in original.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    cls = ast.ClassDef(name='Helpers', bases=[], keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(globals())
    exec(compile(module, str(source), 'exec'), namespace)
    pipe = namespace['Helpers']()
    pipe.log = logging.getLogger('gemini-test')
    pipe.valves = SimpleNamespace(HWPX_MAX_TEXT_CHARS=10000,
        RAG_BYPASS_MAX_INLINE_MB=1, ENABLE_HWPX_SUPPORT=True, USE_VERTEX_AI=False)
    pipe.GEMINI_NATIVE_DOC_MIME_TYPES = {'application/pdf', 'text/plain'}
    return pipe


def archive(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return data.getvalue()


class GeminiImportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = helper_pipe()
        self.entry = {'id': 'test', 'name': 'scan.pdf', 'content_type': 'application/octet-stream'}

    def test_hwpx_numeric_section_order_and_korean(self):
        data = archive({'Contents/section10.xml': '<s><p><t>마지막</t></p></s>',
                        'Contents/section2.xml': '<s><p><t>첫째</t></p><p><t>둘째</t></p></s>'})
        text, stats = self.pipe._extract_hwpx_text(data)
        self.assertEqual(text.split(), ['첫째', '둘째', '마지막'])
        self.assertEqual(stats['sections'], 2)

    def test_hwpx_preview_and_explicit_truncation(self):
        self.pipe.valves.HWPX_MAX_TEXT_CHARS = 3
        text, stats = self.pipe._extract_hwpx_text(archive({'Preview/PrvText.txt': '가나다라마'}))
        self.assertTrue(text.startswith('가나다'))
        self.assertTrue(stats['truncated'])
        self.assertTrue(stats['used_preview_text'])

    def test_hwpx_archive_size_guard(self):
        fake = SimpleNamespace(infolist=lambda: [SimpleNamespace(file_size=33 * 1024 * 1024)])
        with self.assertRaisesRegex(ValueError, '32 MiB'):
            self.pipe._validate_hwpx_archive(fake)

    async def test_pdf_inline_preserves_original_bytes(self):
        data = b'%PDF-1.4\noriginal scan bytes'
        self.pipe._load_owui_file = AsyncMock(return_value=(data, SimpleNamespace()))
        parts, names = await self.pipe._build_rag_bypass_parts([self.entry], require_full_pdf=True)
        self.assertEqual(names, ['scan.pdf'])
        self.assertEqual(parts[0]['inline_data']['mime_type'], 'application/pdf')
        self.assertEqual(base64.b64decode(parts[0]['inline_data']['data']), data)

    async def test_large_pdf_uses_files_api(self):
        data = b'%PDF' + b'x' * (1024 * 1024)
        self.pipe._load_owui_file = AsyncMock(return_value=(data, SimpleNamespace()))
        uploaded = {'file_data': {'file_uri': 'mock://file', 'mime_type': 'application/pdf'}}
        self.pipe._upload_to_google_files_api = AsyncMock(return_value=uploaded)
        parts, _ = await self.pipe._build_rag_bypass_parts([self.entry], require_full_pdf=True)
        self.assertEqual(parts, [uploaded])
        self.pipe._upload_to_google_files_api.assert_awaited_once_with(data, 'application/pdf', 'scan.pdf')

    async def test_ocr_missing_pdf_refuses_text_fallback(self):
        record = SimpleNamespace(data={'content': 'partial extracted text'})
        self.pipe._load_owui_file = AsyncMock(return_value=(None, record))
        with self.assertRaisesRegex(ValueError, 'OCR PDF'):
            await self.pipe._build_rag_bypass_parts([self.entry], require_full_pdf=True)
        parts, _ = await self.pipe._build_rag_bypass_parts([self.entry])
        self.assertIn('partial extracted text', parts[0]['text'])

    async def test_vertex_large_ocr_pdf_refuses_text_fallback(self):
        self.pipe.valves.USE_VERTEX_AI = True
        self.pipe._load_owui_file = AsyncMock(return_value=(b'x' * (1024 * 1024 + 1),
            SimpleNamespace(data={'content': 'partial text'})))
        with self.assertRaisesRegex(ValueError, 'OCR PDF'):
            await self.pipe._build_rag_bypass_parts([self.entry], require_full_pdf=True)


if __name__ == '__main__':
    unittest.main()
