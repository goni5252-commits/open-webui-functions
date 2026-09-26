import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_harness_package import load, ROOT

h = load('harness')


class SharedHarnessTests(unittest.TestCase):
    def test_core_catalog_and_missing_optional_site(self):
        result = h.catalog(ROOT, '/nonexistent-site-test')
        self.assertEqual(result['site_status'], 'not_installed')
        self.assertEqual(len(result['skills']), 6)
        self.assertIn('hwpx', [v['id'] for v in result['skills']])
        self.assertEqual(result['templates'], [])

    def test_site_init_is_non_destructive_and_no_school_assets_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'site'
            h.init_site(root)
            with self.assertRaises(FileExistsError): h.init_site(root)
            result = h.catalog(ROOT, root)
            self.assertEqual(result['site_status'], 'installed')
            self.assertEqual(result['templates'], [])
            self.assertEqual(result['site_instructions'], str(root.resolve()/'AGENTS.md'))

    def test_explicit_override_disable_and_new_feature_without_pipe_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'site'
            h.init_site(root)
            (root/'skills/local').mkdir()
            (root/'skills/local/SKILL.md').write_text('local rules')
            entries = [{'id':'family-letter-generator','description':'school rules','entrypoint':'skills/local/SKILL.md','override':True},
                       {'id':'attendance-report','description':'new feature','entrypoint':'skills/local/SKILL.md'},
                       {'id':'design-md','enabled':False,'override':True}]
            (root/'catalog.json').write_text(json.dumps({'schema_version':1,'skills':entries}))
            result = h.catalog(ROOT, root)
            by_id = {x['id']:x for x in result['skills']}
            self.assertEqual(by_id['family-letter-generator']['origin'], 'site')
            self.assertIn('attendance-report', by_id)
            self.assertNotIn('design-md', by_id)
            entries[0].pop('override')
            (root/'catalog.json').write_text(json.dumps({'schema_version':1,'skills':entries}))
            with self.assertRaisesRegex(ValueError, 'override'): h.catalog(ROOT, root)

    def test_asset_traversal_symlink_and_missing_template_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base/'site'
            h.init_site(root)
            outside = base/'private.md'
            outside.write_text('private')
            (root/'link.md').symlink_to(outside)
            for path in ('../private.md', str(outside), 'link.md', 'missing.hwpx'):
                with self.assertRaises(ValueError): h.inside(root, path)
            (root/'catalog.json').write_text(json.dumps({'schema_version':1,'skills':[], 'templates':[{'id':'family-letter','path':'templates/missing.hwpx'}]}))
            with self.assertRaises(ValueError): h.catalog(ROOT, root)

    def test_workspace_uses_account_home_not_env_and_unique_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for user in ('teacher-a','teacher-b'):
                home = Path(tmp)/user
                home.mkdir()
                with patch('pwd.getpwuid', return_value=SimpleNamespace(pw_dir=str(home), pw_name=user)), patch.dict('os.environ', {'HOME':'/another-user'}):
                    first, second = h.workspace(), h.workspace()
                    self.assertNotEqual(first['path'], second['path'])
                    self.assertTrue(Path(first['path']).is_relative_to(home.resolve()))
                    self.assertEqual(first['execution_user'], user)
                    paths.append(first['path'])
            self.assertNotEqual(paths[0], paths[1])

    def test_symlinked_workspace_base_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)/'home'
            home.mkdir()
            (home/'.openwebui-workspaces').symlink_to(Path(tmp))
            with patch('pwd.getpwuid', return_value=SimpleNamespace(pw_dir=str(home), pw_name='test')):
                with self.assertRaises(ValueError): h.workspace()
