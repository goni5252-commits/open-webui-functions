"""Fetch an isolated DESIGN.md with the public getdesign CLI; no user data uploaded."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def fetch(slug, output_dir, runner=subprocess.run):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,79}', slug) or '..' in slug:
        raise ValueError('Use a catalog slug, not a URL/path/command')
    parent = Path(output_dir).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='design-', dir=parent)).resolve()
    # File-backed logs avoid keeping unbounded npm output in memory.
    log = root / 'download.log'
    with log.open('w+', encoding='utf-8') as stream:
        result = runner(['npx', '-y', 'getdesign@latest', 'add', slug], cwd=root,
                        stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                        timeout=120, text=True)
    if result.returncode:
        raise RuntimeError(f'getdesign exited {result.returncode}; inspect {log}')
    files = [p for p in root.rglob('DESIGN.md') if not p.is_symlink()
             and root in p.resolve().parents and p.is_file() and 0 < p.stat().st_size <= 200000]
    if len(files) != 1:
        raise ValueError(f'Expected one nonempty DESIGN.md (<=200KB); found {len(files)} in {root}')
    raw = files[0].read_bytes()
    text = raw.decode('utf-8-sig')
    if not text.strip() or text.lstrip().lower().startswith(('<!doctype html', '<html')):
        raise ValueError('Empty/HTML response instead of Markdown')
    provenance = {'status': 'downloaded', 'slug': slug, 'path': str(files[0]),
                  'source': f'https://getdesign.md/{slug}/design-md',
                  'sha256': hashlib.sha256(raw).hexdigest()}
    (root / 'source.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('slug')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(fetch(args.slug, args.output_dir), ensure_ascii=False))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
