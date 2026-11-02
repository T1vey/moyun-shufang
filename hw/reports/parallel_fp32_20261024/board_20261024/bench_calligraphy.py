"""Board-side: calligraphy path generation + planning through the service API (never execute)."""
import json, sys, time, urllib.request
release = sys.argv[1]
sys.path.insert(0, release)
from tcb705.config import load
from calligraphy.composer import revision
cfg = load('/home/xilinx/tcb705_data/tcb705.machine.json')
rev = revision(cfg)
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, token=None):
    req = urllib.request.Request('http://127.0.0.1:8785' + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', **({'X-Console-Token': token} if token else {})},
                                 method='GET' if body is None else 'POST')
    try:
        with OP.open(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return dict(http_error=e.code, body=e.read().decode('utf-8', 'replace')[:300])


def wait(job_id, limit=900):
    t = time.monotonic()
    while time.monotonic() - t < limit:
        job = next((j for j in call('/api/jobs').get('jobs', []) if j.get('id') == job_id), None)
        if job and job.get('status') in ('DONE', 'ERROR', 'FAILED', 'CANCELLED'):
            return job, time.monotonic() - t
        time.sleep(0.2)
    raise TimeoutError(job_id)


token = call('/api/status')['token']
assert call('/api/jobs').get('active') is None, 'service busy'
cases = [('preset 横', dict(module='heng', size_mm=40)),
         ('text 永和 50mm', dict(schema='brush-text-v1', text='永和', font_size_mm=50, page_index=0, revision=rev)),
         ('text 天道酬勤 40mm', dict(schema='brush-text-v1', text='天道酬勤', font_size_mm=40, page_index=0, revision=rev))]
out = []
for name, body in cases:
    c = call('/api/calligraphy', body, token)
    if 'id' not in c:
        out.append(dict(case=name, stage='calligraphy', error=c)); print(json.dumps(out[-1], ensure_ascii=False)); continue
    cj, c_wall = wait(c['id'])
    if cj.get('status') != 'DONE':
        out.append(dict(case=name, stage='calligraphy', status=cj.get('status'), error=cj.get('error'), detail=cj.get('detail')))
        print(json.dumps(out[-1], ensure_ascii=False)); continue
    p = call('/api/plan', dict(image_job=c['id']), token)
    if 'id' not in p:
        out.append(dict(case=name, stage='plan', error=p)); print(json.dumps(out[-1], ensure_ascii=False)); continue
    pj, p_wall = wait(p['id'])
    m = (pj.get('result') or {}).get('metrics') or {}
    out.append(dict(case=name, paths=cj.get('result'), paths_s=round(c_wall, 2), plan_status=pj.get('status'),
                    plan_error=pj.get('error'), plan_detail=pj.get('detail'), plan_wall_s=round(p_wall, 2),
                    **{k: m.get(k) for k in ('nodes', 'planning_s', 'ik_pl_batch_s', 'ik_cpu_batch_s', 'pl_batch_starts',
                                             'ik_cpu_batches', 'ik_accel_fallbacks', 'frames', 'duration_s',
                                             'execution_prepare_s', 'execution_blocks', 'motion_algorithm_version')}))
    print(json.dumps(out[-1], ensure_ascii=False), flush=True)
json.dump(out, open('/home/xilinx/fp32_check/calligraphy_bench.json', 'w'), ensure_ascii=False, indent=1)
