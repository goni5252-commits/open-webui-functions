"""Latest-only export policy and version guard regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('export_builder_test', Path(__file__).resolve().parents[1] / 'scripts/build_exports.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ExportBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'functions').mkdir()
        self.source = self.root / 'functions/example.py'
        self.code = '"""\ntitle: Example\nversion: 1.0.0\ndescription: Example function\n"""\nclass Pipe:\n    value = 1\n'
        self.source.write_text(self.code)
        for patcher in (patch.object(builder, 'ROOT', self.root), patch.object(builder, 'IDS', ('example',))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_build_retains_only_latest_and_allows_documentation_cleanup(self):
        builder.build('example')
        self.source.write_text(self.code.replace('Example function', 'Current description'))
        builder.build('example')
        builder.check()
        self.assertEqual([p.name for p in self.root.glob('*.json')], ['function-example.json'])

    def test_runtime_change_requires_version_bump(self):
        builder.build('example')
        self.source.write_text(self.code.replace('value = 1', 'value = 2'))
        with self.assertRaisesRegex(ValueError, 'Increase'):
            builder.build('example')
        self.source.write_text(self.source.read_text().replace('1.0.0', '1.0.1'))
        builder.build('example')
        builder.check()

    def test_check_rejects_historical_exports(self):
        builder.build('example')
        (self.root / 'function-example-v1.0.0.json').write_text((self.root / 'function-example.json').read_text())
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            builder.check()

    def test_check_rejects_wrong_function_id(self):
        builder.build('example')
        path = self.root / 'function-example.json'
        items = json.loads(path.read_text())
        items[0]['id'] = 'other'
        path.write_text(json.dumps(items))
        with self.assertRaisesRegex(ValueError, 'ID differs'):
            builder.check()
