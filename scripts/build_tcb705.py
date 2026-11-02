"""Build the CPU core and offline runner; optionally compile ARM Linux SDK probe."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import platform

ROOT=Path(__file__).resolve().parents[1]
def build(compiler=None,sdk=False):
    compiler=compiler or os.environ.get('CXX') or shutil.which('g++')
    if not compiler:raise SystemExit('请安装 g++ 或通过 --cxx 指定 C++ 编译器')
    os.environ['PATH']=str(Path(compiler).resolve().parent)+os.pathsep+os.environ.get('PATH','')
    out=ROOT/'build/tcb705';out.mkdir(parents=True,exist_ok=True)
    common=[compiler,'-std=c++14','-O3','-fno-fast-math','-ffp-contract=off','-Wall','-Wextra','-Werror']
    win=sys.platform=='win32'
    core=out/('tcb_core.dll' if win else 'libtcb_core.so')
    flags=['-shared']+(['-static-libgcc','-static-libstdc++'] if win else ['-fPIC'])
    # -pthread: core.cpp splits independent batch rows over both A9 cores (identical results).
    subprocess.run(common+flags+([] if win else ['-pthread'])+[str(ROOT/'native/tcb_planner/core.cpp'),'-o',str(core)],check=True)
    # Software execution of the exact HLS source for differential tests only.
    # This library never represents actual FPGA use or FPGA timing.
    sim=out/('tcb_pl_sim.dll' if win else 'libtcb_pl_sim.so')
    subprocess.run(common+flags+(['-Wl,--export-all-symbols'] if win else [])+
        ['-Wno-unknown-pragmas','-Wno-unused-function','-I'+str(ROOT/'native/tcb_planner'),
         str(ROOT/'hls_source/tcb705/tcb_planner_accel.cpp'),'-o',str(sim)],check=True)
    runner=ROOT/'native/huacheng_bridge/runner.cpp'
    if runner.exists():
        subprocess.run(common+(['-static'] if win else ['-pthread'])+[str(runner),'-o',str(out/('tcb_runner.exe' if win else 'tcb_runner'))],check=True)
    subprocess.run(common+(['-static'] if win else ['-pthread'])+
        [str(ROOT/'native/huacheng_bridge/stream_selftest.cpp'),'-o',str(out/('tcb_stream_selftest.exe' if win else 'tcb_stream_selftest'))],check=True)
    if sdk:
        if sys.platform!='linux' or not platform.machine().startswith('arm') or sys.maxsize>2**32:raise SystemExit('ARM32 SDK 工具需在 Linux armhf 上原生编译；交叉编译请用 CMake toolchain')
        vendor=ROOT/'vendor/huacheng'
        subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra',str(ROOT/'native/huacheng_bridge/sdk_probe.cpp'),str(ROOT/'native/huacheng_bridge/sdk_adapter.cpp'),'-I'+str(vendor/'include'),'-L'+str(vendor/'armhf'),'-lxoip','-Wl,-rpath,$ORIGIN/../../vendor/huacheng/armhf','-pthread','-o',str(out/'tcb_sdk_probe')],check=True)
        sdk_flags=['-I'+str(vendor/'include'),'-L'+str(vendor/'armhf'),'-lxoip',
                   '-Wl,-rpath,$ORIGIN/../../vendor/huacheng/armhf','-pthread']
        subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra',
            str(ROOT/'native/huacheng_bridge/commission_probe.cpp'),str(ROOT/'native/huacheng_bridge/sdk_adapter.cpp')]
            +sdk_flags+['-o',str(out/'tcb_commission_probe')],check=True)
        subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-shared','-fPIC','-Wl,--no-undefined',
            str(ROOT/'native/huacheng_bridge/sdk_target_sink.cpp')]+sdk_flags+
            ['-o',str(out/'libtcb_sdk_transport.so')],check=True)
        # SDK V2.4.1 motion server used by tcb705/sdk_motion.py (moveJoints/moveLine/setGlobalSpeed).
        subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra',str(ROOT/'native/huacheng_bridge/sdk_server.cpp')]
            +sdk_flags+['-o',str(out/'tcb_sdk_server')],check=True)
    subprocess.run([sys.executable,str(ROOT/'native/build_lineart.py'),'--cxx',compiler],check=True)
    print('Build complete:',out)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--cxx');ap.add_argument('--sdk',action='store_true');a=ap.parse_args();build(a.cxx,a.sdk)
