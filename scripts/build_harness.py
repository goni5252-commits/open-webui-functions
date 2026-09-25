"""Create/check a deterministic harness archive with an exact file manifest."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'harness/open-terminal'
ARCHIVE = ROOT / 'harness/open-terminal-harness-v1.0.0.zip'
DIGEST = ARCHIVE.with_suffix('.zip.sha256')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = sorted(p for p in SOURCE.rglob('*') if p.is_file() and p.suffix in ('.md', '.py', '.json', '.txt'))
    payloads = {'openwebui-harness/' + p.relative_to(SOURCE).as_posix(): p.read_bytes() for p in files}
    if args.check:
        with ZipFile(ARCHIVE) as z:
            assert set(z.namelist()) == set(payloads), 'Archive file manifest mismatch'
            assert all(z.read(n) == data for n, data in payloads.items()), 'Stale archive'
        assert DIGEST.read_text().split()[0] == hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), 'Digest mismatch'
        print('OK: harness archive and SHA-256 match source')
    else:
        with ZipFile(ARCHIVE, 'w', compression=ZIP_DEFLATED) as z:
            for name, data in payloads.items():
                info = ZipInfo(name, date_time=(2026, 9, 25, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, data)
        DIGEST.write_text(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() + '  ' + ARCHIVE.name + '\n')
        print(ARCHIVE)


if __name__ == '__main__':
    main()
