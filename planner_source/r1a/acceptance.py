"""Read verified receipts; refuse re-signing changed or incompletely tested runs."""
import argparse
import csv
from pathlib import Path
import re
import numpy as np
from .evidence import verify,read,sha,write_new,safe_path

STAGES=['units','dataset','compile','native','negative','backends','trajectories']


def validate(run):
    run=Path(run).resolve(); binding=verify(run,STAGES)
    for filename in ('wls_vectors.exe','wls_step.dll','compile.log','unit_tests.log','native.log'):
        if not (run/filename).is_file(): raise ValueError(f'missing required evidence {filename}')
    log=(run/'unit_tests.log').read_text(encoding='utf-8')
    match=re.search(r'Ran (\d+) tests',log)
    if not match or not re.search(r'^OK$',log,re.M): raise ValueError('unit result missing')
    lines=(run/'vectors.txt').read_text().splitlines(); count=int(lines[0])
    if len(lines)!=count*2+1: raise ValueError('vector file incomplete')
    rows=list(csv.DictReader((run/'native_results.csv').open()))
    if len(rows)!=count or len({r['id'] for r in rows})!=count: raise ValueError('native coverage mismatch')
    for i,r in enumerate(rows):
        identity,mode,expected=lines[1+2*i].split()
        payload=np.array([float(x) for x in lines[2+2*i].split()])
        if payload.shape!=(57,): raise ValueError('vector shape')
        reference=payload[49:54]; absolute,relative,back=payload[54:57]
        if not np.isfinite(reference).all() or not np.isfinite([absolute,relative,back]).all(): raise ValueError('invalid oracle')
        err,allowed,residual=[float(r[k]) for k in ('error_inf','allowed_error','backward_error')]
        if not np.isfinite([err,allowed,residual]).all() or min(err,residual)<0: raise ValueError('non-finite measurement')
        if r['id']!=identity or int(r['status'])!=int(expected) or r['passed']!='1': raise ValueError('native failure')
        tolerance=absolute+relative*np.max(np.abs(reference))
        if abs(allowed-tolerance)>1e-12*max(1,abs(tolerance)): raise ValueError('wrong recorded tolerance')
        if err>tolerance or residual>back: raise ValueError('error gate failed')
    for f in ('negative_summary.json','backend_summary.json','trajectory_summary.json'):
        if read(run/f)['status']!='PASS': raise ValueError(f'failed {f}')
    return binding,int(match[1]),rows


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',required=True)
    parser.add_argument('--verify-only',action='store_true'); args=parser.parse_args()
    run=Path(args.run).resolve(); binding,units,rows=validate(run)
    if args.verify_only:
        report=read(run/'experiment.json')
        if report['binding']!=binding: raise ValueError('acceptance receipt mismatch')
        manifest=read(run/'manifest.json')
        for p,digest in manifest['files'].items():
            if sha(safe_path(run,p))!=digest: raise ValueError(f'acceptance changed {p}')
        print('R1AB_EVIDENCE_VERIFIED'); return
    if (run/'experiment.json').exists() or (run/'manifest.json').exists():
        raise ValueError('report exists; use --verify-only, do not re-sign')
    native=dict(cases=len(rows),failed=0,max_abs_error=max(float(r['error_inf']) for r in rows),
        max_backward_error=max(float(r['backward_error']) for r in rows))
    report=dict(stage='R1AB_HOST_GATE_PASS',binding=binding,unit_tests=units,native=native,
        python=read(run/'python_summary.json'),negative=read(run/'negative_summary.json'),
        backends=read(run/'backend_summary.json'),trajectories=read(run/'trajectory_summary.json'),
        runtime=read(run/'runtime.json'),scope='host numerical and nominal trajectory validation only',
        hls_csim='NOT_RUN',hls_csynth='NOT_RUN',hls_cosim='NOT_RUN',z20='NOT_RUN',physical='NOT_RUN',
        ii='待测',latency='待测',dsp='待测',lut='待测',ff='待测',bram='待测',timing='待测')
    write_new(run/'experiment.json',report)
    backend=report['backends']; trajectory=report['trajectories']
    lines=['# R1a 修复 + R1b 主机验收','',f'运行目录：`{run}`。范围：名义模型离线规划，不授权物理动作。','',
        f'- 单元测试：{units} 项通过。',f'- C++ 单步：{native["cases"]} 次，0 失败，包含旧审查 1,728 个真实迭代输入。',
        f'- 最大 dq 绝对差：{native["max_abs_error"]:.8g} rad；最大后向误差：{native["max_backward_error"]:.8g}。',
        '- 保留 v1 的 dq 绝对/相对门槛和 5e-5 后向误差门槛；法方程组装改为 double，Cholesky 与接口仍 float。',
        f'- 损坏参考、容差、源码/旧日志组合：{len(report["negative"]["probes"])} 个负面探针均被拒绝。',
        f'- 完整 IK 双后端：{backend["targets"]} 个目标，{backend["calls"]} 次；接受结果重验物理误差/限位，所有终态写入 history。',
        f'- 连续绘画：{trajectory["paths"]} 条名义路径，{trajectory["evaluations"]} 个后端/策略组合，{trajectory["successful"]} 组通过整条轨迹检查。','',
        '## 双后端静态求解','', '| 状态 | Python（float 输入、double 求解） | C++（double 组装、float 分解） |','|---|---:|---:|']
    counts=backend['status_counts']
    for k in sorted(set(counts['python_f32_input'])|set(counts['cpp_mixed'])):
        lines.append(f'| {k} | {counts["python_f32_input"].get(k,0)} | {counts["cpp_mixed"].get(k,0)} |')
    lines+=['','失败没有被剔除；状态差异与完整历史在 backend_results.jsonl。不能由这些主机时间推导 A9 或 FPGA 加速。','',
        '## R1b 轨迹结果','','| 路径/后端/恢复 | 状态 | 目标数 | 恢复调用 | 计划时长 s |','|---|---|---:|---:|---:|']
    for r in trajectory['results']:
        lines.append(f'| {r["name"]} | {r["status"]} | {r["completed_targets"]}/{r["total_targets"]} | {r["recovery_calls"]} | {r["duration_s"]:.3f} |')
    lines+=['','恢复和基线有相同每目标迭代上限；收益按配对结果报告。',
        '首点从独立 q0 分段进入，前一有效解热启动；笔画间 LIFT/TRAVEL/LOWER；任一点失败或取消，整条 commands=None。',
        '关节插值采用逐段五次平滑启停，速度/加速度有解析上界，并采样检查笛卡尔位置和倾角。速度不恒定，是保守原型。','',
        '## 可追溯性','',
        'inputs.json 在任何测试前冻结；receipts/ 记录阶段顺序、输入哈希、命令、退出码、日志与输出哈希。变更后拒绝验收；报告不允许覆盖。',
        '该链防止无意混用和旧日志重签，不是针对文件所有者恶意重写全部证据的密码学认证。','',
        '## 仍未验证','',
        '名义笔轴/笔尖/纸面不代表真实标定；本轮不读写串口，不输出可直接执行的电机指令，没有碰撞证明。',
        'AMD C 仿真、综合、RTL 联仿、Z20 上板、硬件反馈/超时和实际画线精度全部未验证。double 组装会增加硬件成本，是否满足资源和时序待测。',
        'R0 仍是原公式单步消融而非完整上游复现；R1b 输入是 SI JSON 线/圆弧，ArmVision 原始格式导入尚未接入。','']
    with (run/'ACCEPTANCE.md').open('x',encoding='utf-8') as f: f.write('\n'.join(lines))
    write_new(run/'manifest.json',dict(schema=2,binding=binding,files={p.relative_to(run).as_posix():sha(p)
        for p in sorted(run.rglob('*')) if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}))
    print(f'R1AB_HOST_GATE_PASS units={units} vectors={len(rows)} trajectories={trajectory["evaluations"]}')


if __name__=='__main__': main()
