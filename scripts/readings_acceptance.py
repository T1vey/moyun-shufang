"""Run on board: read-only acceptance, or explicit non-motion command precomputation.

Never enables or executes the arm, and never programs PL. Tokens stay in this process.
"""
import argparse,json,urllib.request

def request(port,path,data=None,header=None):
    body=None if data is None else json.dumps(data).encode()
    r=urllib.request.Request('http://127.0.0.1:%d%s'%(port,path),data=body,
        headers=dict({'Content-Type':'application/json'},**(header or {})))
    with urllib.request.urlopen(r,timeout=15) as f:return json.load(f)

def main():
    p=argparse.ArgumentParser();p.add_argument('--precompute',action='store_true');a=p.parse_args()
    status=request(8785,'/api/status');health=status.get('ik_metrics',{})
    audio=request(8095,'/api/audio/status')
    screen=request(8095,'/api/state');workflow=screen.get('workflow') or {}
    store=request(8785,'/api/masterpiece_store')
    print(json.dumps(dict(platform={k:health.get(k) for k in ('faulted','abi','build_id','clock_hz','error')},
        audio=audio,screen_phase=workflow.get('phase'),masterpiece_store=store),ensure_ascii=False,indent=2))
    if a.precompute:
        if health.get('faulted') or health.get('build_id')!='tcb705-parallel-fp32-audio-20261027':
            raise RuntimeError('New platform has not passed boot checks')
        if workflow.get('phase')!='idle':raise RuntimeError('Wait until the screen workflow is idle')
        result=request(8785,'/api/masterpiece_all',{'mode':'real'}, {'X-Console-Token':status['token']})
        print('PRECOMPUTE_STARTED_NO_MOTION',json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
