"""Build the small CPU recognition kernel; no FPGA or controller access."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
def build(cxx=None):
    cxx = cxx or os.environ.get('CXX') or shutil.which('g++')
    if not cxx:raise SystemExit('请通过 --cxx 指定 g++')
    out = ROOT/'build/handwriting';out.mkdir(parents=True, exist_ok=True)
    win = sys.platform=='win32'
    dest = out/('handwriting.dll' if win else 'libhandwriting.so')
    subprocess.run([cxx,'-std=c++14','-O3','-fno-fast-math','-shared','-Wall','-Wextra','-Werror']+
                   (['-static-libgcc','-static-libstdc++'] if win else ['-fPIC'])+
                   [str(ROOT/'native/handwriting_match.cpp'),'-o',str(dest)],check=True)
    print(dest)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cxx');build(p.parse_args().cxx)
