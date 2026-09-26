"""Shared skill discovery and current-account workspace creation. No security sandbox."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

CORE = Path(__file__).resolve().parents[1]
ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def inside(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError(f'Expected a relative asset path: {relative!r}')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f'Missing asset or path outside root: {relative}')
    return str(path)


def read_catalog(root):
    path = Path(inside(root, 'catalog.json'))
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('skills'), list):
        raise ValueError(f'Unsupported catalog schema: {path}')
    return data


def catalog(core=CORE, site_root=None):
    core = Path(core).resolve()
    merged, templates = {}, {}
    sources = [('core', core, read_catalog(core))]
    site_state, site_instructions = 'not_configured', None
    if site_root:
        site = Path(site_root).resolve()
        if not site.exists():
            site_state = 'not_installed'
        else:
            site_state = 'installed'
            # An existing but broken site should fail visibly, not silently use defaults.
            sources.append(('site', site, read_catalog(site)))
            if (site/'AGENTS.md').exists():
                site_instructions = inside(site, 'AGENTS.md')
    for origin, root, data in sources:
        seen = set()
        for item in data['skills']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id']):
                raise ValueError('Invalid skill id')
            key = item['id']
            if key in seen:
                raise ValueError(f'Duplicate skill id in {origin}: {key}')
            seen.add(key)
            if key in merged and item.get('override') is not True:
                raise ValueError(f'Explicit override=true required for {key}')
            if not isinstance(item.get('enabled', True), bool):
                raise ValueError(f'enabled must be boolean: {key}')
            if not item.get('enabled', True):
                merged[key] = None
                continue
            if not isinstance(item.get('description'), str) or not item['description'].strip():
                raise ValueError(f'Missing description: {key}')
            entry = inside(root, item.get('entrypoint'))
            if Path(entry).name != 'SKILL.md':
                raise ValueError(f'Entrypoint must name SKILL.md: {key}')
            needs = item.get('needs', [])
            if not isinstance(needs, list) or any(not isinstance(n, str) or not ID.fullmatch(n) for n in needs):
                raise ValueError(f'Invalid needs list: {key}')
            merged[key] = {'id': key, 'description': item['description'], 'entrypoint': entry,
                           'origin': origin, 'needs': needs}
        seen_templates = set()
        items = data.get('templates', [])
        if not isinstance(items, list):
            raise ValueError('templates must be a list')
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id']):
                raise ValueError('Invalid template id')
            key = item['id']
            if key in seen_templates or (key in templates and item.get('override') is not True):
                raise ValueError(f'Duplicate template: {key}')
            seen_templates.add(key)
            templates[key] = {'id': key, 'path': inside(root, item.get('path')), 'origin': origin}
    return {'schema_version': 1, 'core_version': sources[0][2].get('version'),
            'site_status': site_state, 'site_instructions': site_instructions,
            'skills': [v for v in merged.values() if v is not None],
            'templates': list(templates.values())}


def workspace():
    import pwd
    # Resolve the OS account, not a request-supplied user id or untrusted HOME.
    account = pwd.getpwuid(os.geteuid())
    home = Path(account.pw_dir).resolve()
    base = home / '.openwebui-workspaces'
    if base.is_symlink():
        raise ValueError('Workspace base must not be a symlink')
    base.mkdir(mode=0o700, exist_ok=True)
    if base.stat().st_uid != os.geteuid():
        raise ValueError('Workspace base must be owned by the current account')
    path = Path(tempfile.mkdtemp(prefix='task-', dir=base))
    return {'path': str(path), 'execution_user': account.pw_name,
            'execution_uid': os.geteuid(), 'note': 'Uses the actual Terminal account; this is not user isolation.'}


def init_site(path):
    root = Path(path)
    root.mkdir(parents=True, exist_ok=False)
    (root/'skills').mkdir()
    (root/'templates').mkdir()
    (root/'AGENTS.md').write_text('# 학교 공통 지침\n\n관리자가 검토한 학교 공통 규칙만 기록합니다. 사용자 개인정보·API 키는 넣지 않습니다.\n공통 core/AGENTS.md의 작업 폴더·원본 보존·파일 전달 규칙을 따릅니다.\n', encoding='utf-8')
    (root/'catalog.json').write_text(json.dumps({'schema_version':1,'version':'school-1','skills':[],'templates':[]}, indent=2)+'\n', encoding='utf-8')
    return {'path': str(root.resolve()), 'status':'created', 'templates':'not_installed'}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('catalog', 'validate'):
        child = sub.add_parser(name)
        child.add_argument('--site-root')
    sub.add_parser('workspace')
    child = sub.add_parser('init-site')
    child.add_argument('--path', required=True)
    args = parser.parse_args()
    try:
        if args.command in ('catalog', 'validate'):
            result = catalog(site_root=args.site_root)
        elif args.command == 'workspace':
            result = workspace()
        else:
            result = init_site(args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
