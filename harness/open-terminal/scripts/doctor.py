"""Read-only environment check. Never installs packages or modifies server settings."""
import importlib.util
import json
import shutil
import subprocess


def inspect():
    commands = {name: shutil.which(name) for name in ('python3', 'node', 'npm', 'npx', 'fc-list', 'libreoffice', 'pdftoppm')}
    fonts = []
    if commands['fc-list']:
        result = subprocess.run(['fc-list', ':lang=ko', 'family'], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            fonts = sorted(set(result.stdout.splitlines()))
    return {'commands': commands, 'python_pptx': importlib.util.find_spec('pptx') is not None,
            'korean_font_families': fonts,
            'note': 'Rendering is optional but required for visual QA; fonts are not automatically embedded in PPTX.'}


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
