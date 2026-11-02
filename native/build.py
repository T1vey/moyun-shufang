"""Build on desktop or directly on the ARM board; never deploys or opens devices.

Example: python native/build.py --cxx g++
Cross ARM: --cxx arm-linux-gnueabihf-g++ --platform linux --output /build/libso101_geometry.so
"""
import argparse
import json
import hashlib
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cxx', default='g++')
    p.add_argument('--platform', choices=('win32', 'linux', 'darwin'), default=sys.platform)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parent
    name = ('so101_geometry.dll' if a.platform == 'win32' else
            'libso101_geometry.dylib' if a.platform == 'darwin' else 'libso101_geometry.so')
    output = a.output or root/'build'/name
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = ['-O2', '-std=c++11', '-fno-fast-math', '-ffp-contract=off', '-fno-associative-math']
    flags += (['-shared', '-static-libgcc', '-static-libstdc++'] if a.platform == 'win32'
              else ['-fPIC', '-dynamiclib' if a.platform == 'darwin' else '-shared'])
    command = [a.cxx]+flags+[str(root/'geometry.cpp'), '-o', str(output)]
    subprocess.run(command, check=True)
    manifest = dict(command=command, abi='0x534e0101', fp='binary64; no fast-math; FP contraction off',
                    source_sha256=hashlib.sha256((root/'geometry.cpp').read_bytes()).hexdigest(),
                    library_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    platform=a.platform, scope='build only; no board performance claim')
    output.with_suffix(output.suffix+'.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(output.resolve())


if __name__ == '__main__':
    main()
