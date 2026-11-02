"""Collect measured RTL cycles and routed timing without claiming board speed."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--hls',type=Path,required=True)
    ap.add_argument('--export',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    work=a.hls/'hls_controller_throughput/hls'
    if not work.is_dir():work=a.hls/'w/hls'
    rpt=work/'sim/report/tcb_planner_parallel_cosim.rpt'
    if not re.search(r'Verilog\s*\|\s*Pass',rpt.read_text()):
        raise ValueError('RTL co-simulation did not pass')
    transactions=work/'sim/verilog/tcb_planner_parallel.performance.result.transaction.xml'
    cycles=[int(x) for x in re.findall(r'transaction\s+\d+:\s+(\d+)',transactions.read_text())]
    if len(cycles)!=3 or any(n<=0 for n in cycles):
        raise ValueError('Expected exactly three 64-point transactions')
    contract=a.hls/'hls_contract/hls/sim/report/tcb_planner_parallel_cosim.rpt'
    if not re.search(r'Verilog\s*\|\s*Pass',contract.read_text()):
        raise ValueError('Failure/cancel contract RTL did not pass')
    synth=ET.parse(work/'syn/report/tcb_planner_parallel_csynth.xml').getroot()
    resources={p.tag:int(p.text) for p in synth.findall('./AreaEstimates/Resources/*')}
    verify=json.loads((a.export/'build_verified.json').read_text())
    if verify['setup_slack_ns']<0 or verify['hold_slack_ns']<0 or verify['drc_errors']:
        raise ValueError('Full-platform routed timing/DRC failed')
    from tcb705.accel_contract import clock_hz,TOP_FP32
    clock=clock_hz(a.export/'tcb705_planner_fp32.hwh',TOP_FP32)
    if clock!=100000000:raise ValueError('Routed platform is not configured at 100 MHz')
    rates=[64*clock/n for n in cycles]
    if min(rates)<=80000:raise ValueError('Throughput requirement not achieved')
    hashes={}
    for p in sorted((ROOT/'hls_source/tcb705_parallel_fp32').iterdir()):
        if p.suffix not in ('.cpp','.hpp','.h'):continue
        src=a.hls/'src'/p.name
        if p.read_bytes()!=src.read_bytes():raise ValueError('Build/source mismatch: '+p.name)
        hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    artifacts={}
    for name in ('tcb705_planner_fp32.bit','tcb705_planner_fp32.hwh','tcb705_parallel_fp32.xsa'):
        p=a.export/name
        if not p.is_file() or p.stat().st_size==0:raise ValueError('Missing '+name)
        artifacts[name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    result=dict(status='PASS',clock_hz=clock,points_per_transaction=64,
        transaction_cycles=cycles,transaction_points_per_second=rates,
        minimum_points_per_second=min(rates),hls_resources=resources,
        routed=verify,source_sha256=hashes,artifacts=artifacts,
        compute_precision='FP32; integer CORDIC; packed FP64 DDR transport',
        offline_numerical_budget=dict(position_m=1e-5,orientation_rad=1e-4),
        runtime_fk_verification=False,deployed=False,robot_moved=False,
        scope='RTL AXI test model plus full-platform routed timing. Excludes Python, real DDR contention, CPU fallback, and robot execution.')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    main()
