"""Offline CPU benchmark using saved calibration. Never connects to the arm."""
import argparse,json,sys,time,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tcb705.config import load
from tcb705.model import Model
from tcb705.web_executor import settings
from handwriting.recognizer import recognize,bank,native
from handwriting.planner import compile_stroke

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args();c=load(args.config);model=Model(c);bank();rows=[]
    startq=model.from_sdk(settings(c)['home']['joint_degrees'])
    shapes=[('horizontal',[[.2,.3],[.8,.3]]),('vertical',[[.5,.2],[.5,.8]]),
            ('left-fall',[[.7,.2],[.63,.45],[.5,.65],[.25,.82]]),
            ('horizontal-turn',[[.2,.2],[.78,.2],[.78,.8]])]
    for size in (40,60,100):
        q=startq;pred='home'
        for name,raw in shapes:
            begin=time.perf_counter();match=recognize(raw);recognized=time.perf_counter()
            p=compile_stroke(match,raw,size,c,model,q,pred,lambda:False)
            row=dict(shape=name,size_mm=size,module=match['module'],recognition_ms=round((recognized-begin)*1000,2),
                     total_ms=round((time.perf_counter()-begin)*1000,2),**p.metrics)
            rows.append(row);q=p.q_end;pred=p.fingerprint
            print(name,size,row['total_ms'],flush=True)
    result=dict(mode='offline_cpu_no_motion',native_recognizer=native() is not None,
                median_ms=round(statistics.median(r['total_ms'] for r in rows),2),rows=rows)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
