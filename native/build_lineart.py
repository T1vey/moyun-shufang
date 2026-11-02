"""Build C++ CPU baseline / tracing kernels, locally or with an ARM cross compiler."""
import argparse,hashlib,json,subprocess,sys,os
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--cxx',default='g++');ap.add_argument('--platform',default=sys.platform,choices=['win32','linux']);ap.add_argument('--output',type=Path);a=ap.parse_args()
root=Path(__file__).resolve().parent;source=root/'lineart.cpp'
os.environ['PATH']=str(Path(a.cxx).resolve().parent)+os.pathsep+os.environ.get('PATH','')
out=a.output or root/'build'/('tcb_lineart.dll' if a.platform=='win32' else 'libtcb_lineart.so');out.parent.mkdir(parents=True,exist_ok=True)
flags=['-O2','-std=c++11','-fno-fast-math','-ffp-contract=off','-fno-associative-math','-shared']
flags+=['-static','-static-libgcc','-static-libstdc++'] if a.platform=='win32' else ['-fPIC']
cmd=[a.cxx]+flags+[str(source),'-o',str(out)]
subprocess.run(cmd,check=True)
Path(str(out)+'.json').write_text(json.dumps(dict(abi='0x4c4e0101',command=cmd,platform=a.platform,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),library_sha256=hashlib.sha256(out.read_bytes()).hexdigest()),indent=2),encoding='utf-8')
print(out)
