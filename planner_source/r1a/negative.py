"""Deliberately corrupted validation inputs must exit nonzero; source binding too."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from . import evidence


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',required=True); args=parser.parse_args()
    run=Path(args.run).resolve(); exe=run/'wls_vectors.exe'
    lines=(run/'vectors.txt').read_text().splitlines()
    header=lines[3]; payload=lines[4].split()  # normal paired second call
    probes=[]
    edits=[('nan_reference',49,'nan'),('inf_reference',50,'inf'),('nan_abs_tol',54,'nan'),
           ('negative_abs_tol',54,'-1'),('inf_rel_tol',55,'inf'),('negative_rel_tol',55,'-1'),
           ('zero_backward_tol',56,'0'),('nan_backward_tol',56,'nan')]
    folder=run/'negative'; folder.mkdir()
    for label,index,value in edits:
        tokens=list(payload); tokens[index]=value
        file=folder/f'{label}.txt'; file.write_text('1\n'+header+'\n'+' '.join(tokens)+'\n')
        p=subprocess.run([str(exe),str(file),str(folder/f'{label}.csv')],capture_output=True,text=True)
        (folder/f'{label}.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode!=2 or 'HARNESS_ERROR' not in p.stderr: raise AssertionError(f'corrupt input accepted: {label}')
        probes.append(dict(name=label,exit_code=p.returncode,rejected=True))
    # Reproduce the reviewer's stale-result re-signing attempt using the real
    # verification primitive required by report and HLS entry points.
    with tempfile.TemporaryDirectory(dir=run,prefix='binding_negative_') as temp:
        root=Path(temp); (root/'source/config').mkdir(parents=True)
        (root/'source/config/contract.json').write_text('{}')
        source=root/'source/kernel.cpp'; source.write_text('original tested source')
        evidence.freeze(root); (root/'old.log').write_text('PASS')
        evidence.record(root,'native',['old_test.exe'],0,['old.log'])
        source.write_text('#error this was never compiled')
        try: evidence.verify(root)
        except ValueError as exc:
            probes.append(dict(name='changed_source_old_logs',rejected=True,reason=str(exc)))
        else: raise AssertionError('changed source accepted')
    evidence.write_new(run/'negative_summary.json',dict(status='PASS',probes=probes))
    print(f"NEGATIVE_GATE_PASS probes={len(probes)}")


if __name__=='__main__': main()
