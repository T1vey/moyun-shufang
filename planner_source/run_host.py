"""Run only from a new frozen run/source directory via script 11."""
from datetime import datetime,timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
import numpy as np
from r1a import evidence


def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')
    source=Path(__file__).resolve().parent; run=source.parent
    if not (run/'entrypoints/11_verify_r1ab.ps1').exists(): raise ValueError('use the staging script')
    if (run/'inputs.json').exists(): raise ValueError('run already started; use a fresh run')
    evidence.freeze(run)
    os.environ['R1A_UPSTREAM_DIR']=str(run/'reference/upstream')
    os.environ['PYTHONIOENCODING']='utf-8'
    (run/'tmp').mkdir(); os.environ['TMP']=str(run/'tmp'); os.environ['TEMP']=str(run/'tmp')
    runtime=dict(created_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,platform=platform.platform(),
                 numpy=np.__version__,run=str(run),source=str(source),scope='Windows host only, no AMD tool run')
    evidence.write_new(run/'runtime.json',runtime)
    def stage(name,argv,outputs):
        evidence.verify(run)
        print(f'STAGE {name}',flush=True)
        proc=subprocess.run(argv,cwd=source,capture_output=True)
        raw=proc.stdout+proc.stderr
        (run/f'{name}.raw.log').write_bytes(raw)
        decoded=raw.decode('utf-8',errors='replace')
        log=run/f'{name}.log'; log.write_text(decoded,encoding='utf-8')
        print(decoded[-4000:],flush=True)
        if proc.returncode:
            evidence.write_new(run/'failure.json',dict(stage=name,exit_code=proc.returncode,argv=argv,log=str(log)))
            raise RuntimeError(f'{name} failed: {proc.returncode}; {log}')
        paths=list(outputs() if callable(outputs) else outputs)+[log.name,f'{name}.raw.log']
        evidence.record(run,name,argv,proc.returncode,paths)
    py=sys.executable
    stage('units',[py,'-B','-m','unittest','discover','-s','tests','-v'],['runtime.json'])
    (run/'unit_tests.log').write_bytes((run/'units.log').read_bytes())
    stage('dataset',[py,'-B','-m','r1a.benchmark','--out',str(run),'--review-vectors',str(run/'reference/actual_iterations.txt')],
          ['unit_tests.log','vectors.txt','vectors.json','targets.json','ik_results.jsonl','python_summary.json'])
    stage('compile',[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(run/'entrypoints/compile.cmd')],
          ['wls_vectors.exe','wls_step.dll'])
    stage('native',[str(run/'wls_vectors.exe'),str(run/'vectors.txt'),str(run/'native_results.csv')],['native_results.csv'])
    stage('negative',[py,'-B','-m','r1a.negative','--run',str(run)],
          lambda:['negative_summary.json']+[p.relative_to(run).as_posix() for p in (run/'negative').glob('*')])
    stage('backends',[py,'-B','-m','r1a.compare','--run',str(run)],['backend_results.jsonl','backend_summary.json'])
    stage('trajectories',[py,'-B','-m','r1b.benchmark','--run',str(run)],
          lambda:['trajectory_summary.json','drawing_fixtures.json']+[p.relative_to(run).as_posix() for p in (run/'trajectories').glob('*.json')])
    evidence.verify(run)
    p=subprocess.run([py,'-B','-m','r1a.report','--run',str(run)],cwd=source)
    if p.returncode: raise RuntimeError('report rejected evidence')
    p=subprocess.run([py,'-B','-m','r1a.report','--run',str(run),'--verify-only'],cwd=source)
    if p.returncode: raise RuntimeError('final evidence verification failed')


if __name__=='__main__': main()
