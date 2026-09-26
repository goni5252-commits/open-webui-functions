"""Build Open WebUI JSON exports without importing server dependencies."""
import argparse
import ast
import copy
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
IDS = ('openai_responses', 'google_gemini', 'google_gemini_rag_bypass', '한글문서_내보내기')


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
    exports = {p: read_export(p) for p in ROOT.glob('function-*.json')}
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
    versioned = ROOT / f'function-{fid}-v{manifest["version"]}.json'
    if versioned.exists():
        items = read_export(versioned)
        if items[0]['content'] != code:
            raise ValueError('This version is already published. Increase the source version first.')
        payload = versioned.read_text(encoding='utf-8')
    else:
        items = copy.deepcopy(read_export(latest))
        old_version = header(items[0]['content'])['version']
        if tuple(map(int, manifest['version'].split('.'))) <= tuple(map(int, old_version.split('.'))):
            raise ValueError('Increase the source version above the current latest export.')
        items[0].pop('user_id', None)
        items[0]['content'] = code
        items[0]['updated_at'] = int(time.time())
        items[0].setdefault('meta', {})['manifest'] = manifest
        items[0]['meta']['description'] = manifest.get('description', '')
        payload = json.dumps(items, ensure_ascii=False, indent=2) + '\n'
        versioned.write_text(payload, encoding='utf-8')
    latest.write_text(payload, encoding='utf-8')
    print(f'Generated {latest.name} and {versioned.name}')


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
