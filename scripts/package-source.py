"""Package only Git-visible source; ignored credentials, tools and user bodies stay out."""
from pathlib import Path
import hashlib
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / 'artifacts'
out.mkdir(exist_ok=True)
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode('utf-8').split('\0')
with zipfile.ZipFile(out / 'QDrop-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(set(filter(None, files))):
        path = root / name
        if path.is_file():
            archive.write(path, 'QDrop/' + name)
packages = sorted((out / 'android').glob('*.apk')) + sorted(out.glob('*.zip'))
(out / 'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}\n' for p in packages), encoding='utf-8')
print(f'Source: {len(set(filter(None, files)))} files; checksums: {len(packages)} packages')
