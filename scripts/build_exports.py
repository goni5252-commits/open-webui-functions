"""Build Open WebUI JSON exports without importing server dependencies."""
import argparse
import ast
import copy
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
IDS = ('exaone_auto', 'openai_responses', 'google_gemini', 'google_gemini_rag_bypass', '한글문서_내보내기', '엑셀로_내보내기')


def header(code):
    tree = ast.parse(code)
    compile(tree, '<function>', 'exec')
    doc = ast.get_docstring(tree, clean=False) or ''
    fields = dict(re.findall(r'^([a-z_]+):\s*([^\n]+)', doc, re.M))
    if not re.fullmatch(r'\d+\.\d+\.\d+', fields.get('version', '')):
        raise ValueError('Expected a version: major.minor.patch in the module header')
    return fields


def read_export(path):
    items = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError(f'Expected one function in {path.name}')
    header(items[0]['content'])
    return items


def check():
    expected = {ROOT / f'function-{fid}.json' for fid in IDS}
    actual = set(ROOT.glob('function-*.json'))
    if actual != expected:
        raise ValueError('Keep exactly one latest function-<id>.json export per function')
    exports = {p: read_export(p) for p in actual}
    for p, items in exports.items():
        if p.name != f'function-{items[0]["id"]}.json':
            raise ValueError(f'{p.name}: function ID differs from filename')
    for fid in IDS:
        code = (ROOT / 'functions' / f'{fid}.py').read_text(encoding='utf-8')
        manifest = header(code)
        matches = [items[0] for items in exports.values()
                   if items[0]['id'] == fid
                   and header(items[0]['content'])['version'] == manifest['version']]
        if not matches or any(item['content'] != code for item in matches):
            raise ValueError(f'{fid}: matching version export is missing or differs from source')
        for item in matches:
            if item.get('meta', {}).get('manifest', {}).get('version') != manifest['version']:
                raise ValueError(f'{fid}: export manifest version differs from source')
    print('OK: Python syntax, JSON exports, matching source versions')


def build(fid):
    code = (ROOT / 'functions' / f'{fid}.py').read_text(encoding='utf-8')
    manifest = header(code)
    latest = ROOT / f'function-{fid}.json'
    if latest.exists():
        items = copy.deepcopy(read_export(latest))
        old_code = items[0]['content']
        old_version = header(old_code)['version']
        current = tuple(map(int, manifest['version'].split('.')))
        previous = tuple(map(int, old_version.split('.')))
        # Metadata/documentation cleanup may retain the version; runtime changes may not.
        before, after = ast.parse(old_code), ast.parse(code)
        before.body = before.body[1:]
        after.body = after.body[1:]
        if current < previous or (current == previous and ast.dump(before) != ast.dump(after)):
            raise ValueError('Increase the source version for runtime changes; downgrades are not allowed.')
    else:
        if not any(isinstance(node, ast.ClassDef) and node.name == 'Pipe'
                   for node in ast.parse(code).body):
            raise ValueError('New exports currently support Pipe functions only.')
        items = [{'id': fid, 'name': manifest.get('title', fid), 'type': 'pipe',
                  'is_active': False, 'is_global': False, 'created_at': int(time.time())}]
    items[0].pop('user_id', None)
    items[0]['content'] = code
    items[0]['updated_at'] = int(time.time())
    items[0].setdefault('meta', {})['manifest'] = manifest
    items[0]['meta']['description'] = manifest.get('description', '')
    latest.write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Generated {latest.name}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('function', nargs='?', choices=IDS)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        if args.check:
            check()
        elif args.function:
            build(args.function)
            check()
        else:
            parser.error('Specify a function ID or --check')
    except (ValueError, OSError, SyntaxError, KeyError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
