"""Launch the delivery board profile, or validate it without hardware IO."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_config import board_arguments


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', default='config/runtime.target.json')
    p.add_argument('--data-dir', type=Path, default=ROOT / 'logs')
    p.add_argument('--allow-motion', action='store_true')
    p.add_argument('--check', action='store_true', help='Files/metadata only; no FPGA download or serial IO')
    a = p.parse_args()
    args = board_arguments(a.profile)
    args += ['--data-dir', str(a.data_dir.resolve())]
    if a.allow_motion:
        args += ['--allow-motion']
    command = [sys.executable, '-B', str(ROOT / 'app.py')] + args
    if a.check:
        print(json.dumps({'status': 'PASS', 'command': command}, ensure_ascii=False, indent=2))
        return
    os.execv(sys.executable, command)


if __name__ == '__main__':
    main()
