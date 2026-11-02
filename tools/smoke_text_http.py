"""Exercise a localhost SIMULATION instance end to end. Refuses a real backend."""
import json
from pathlib import Path
import time
import urllib.request
import uuid

BASE='http://127.0.0.1:8098'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))


def raw(path,data=None):
    req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),
        headers={} if data is None else {'Content-Type':'application/json'})
    with opener.open(req,timeout=30) as r:return json.loads(r.read())


def main():
    state=raw('/api/state');token=state['pair']['token'];cid='smoke_'+uuid.uuid4().hex[:16]
    def api(path,data=None):
        return raw(path+('&' if '?' in path else '?')+'t='+token,None if data is None else dict(data,cid=cid))
    cap=api('/api/text/capabilities')
    if cap.get('simulation') is not True:raise RuntimeError('Refusing non-simulation instance')
    if state['workflow']['phase'] not in ('idle','completed','cancelled','error'):raise RuntimeError('Instance has a pending job')
    preview=api('/api/text/preview',dict(text='一二三四五六七',font_size_mm=40))
    assert (preview['columns'],preview['rows'],preview['page_count'])==(3,2,2)
    data={k:preview[k] for k in ('text','font_size_mm','preview_id','revision')}
    data.update(request_id=uuid.uuid4().hex,start_requested=True)
    state=api('/api/text/submit',data);jid=state['job_id'];phases=[]
    def wait(wanted):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            s=api('/api/text/status?cid='+cid+'&job_id='+jid)
            if not phases or phases[-1]!=s['phase']:phases.append(s['phase'])
            if s['phase'] in ('error','cancelled'):raise AssertionError(s)
            if s['phase']==wanted:return s
            time.sleep(.2)
        raise AssertionError('timed out')
    first=wait('awaiting_paper')
    duplicate=api('/api/text/submit',data);assert duplicate['job_id']==jid and duplicate['phase']=='awaiting_paper'
    api('/api/text/next-page',dict(job_id=jid,page_index=0,paper_ready=True))
    final=wait('completed');assert final['page_index']==1
    report=dict(simulation=True,physical_motion=False,job_id=jid,first_page=first,final=final,phases=phases,
                checks=['paired phone input','3 columns / 2 rows','native IK','frozen trajectory simulation',
                        'duplicate submit not replayed','paper confirmation','second page complete'])
    path=Path('reports/text_calligraphy_20261022/http_smoke.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
