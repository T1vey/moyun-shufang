"""Offline publication check. Never contacts a controller or loads an overlay."""
import ast
import json
import re
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    issues = []
    count = 0
    forbidden = {'.bit', '.hwh', '.xsa', '.dcp', '.dll', '.so', '.pyd', '.pem', '.key'}
    pattern = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,})')
    for p in root.rglob('*'):
        if not p.is_file() or any(s in {'.git', '.venv', '__pycache__', 'build', 'dist'} for s in p.relative_to(root).parts):
            continue
        if '.local.' in p.name or p.suffix.lower() in forbidden:
            issues.append(str(p.relative_to(root)))
        data = p.read_bytes()
        if pattern.search(data):
            issues.append('credential-like token: ' + str(p.relative_to(root)))
        if p.suffix == '.py':
            ast.parse(data.decode('utf-8-sig'), filename=str(p))
            count += 1
    for expected in ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/validation_summary.md']:
        if not (root / expected).is_file():
            issues.append('missing ' + expected)
    print(json.dumps({'status': 'PASS' if not issues else 'FAIL', 'python_sources': count, 'issues': issues}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(issues))

if __name__ == '__main__':
    main()
