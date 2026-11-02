"""Board-side: time planning of the reference portrait through the running service (no execute)."""
import json, sys, time, urllib.request
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = 'http://127.0.0.1:8785'


def call(path, body=None, token=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', **({'X-Console-Token': token} if token else {})},
                                 method='GET' if body is None else 'POST')
    with OP.open(req, timeout=30) as r:
        return json.load(r)


def wait(job_id, token, limit=600):
    t = time.monotonic()
    while time.monotonic() - t < limit:
        jobs = call('/api/jobs')
        job = next((j for j in jobs.get('jobs', []) if j.get('id') == job_id), None)
        if job and job.get('status') in ('DONE', 'ERROR', 'FAILED', 'CANCELLED'):
            return job, time.monotonic() - t
        time.sleep(0.2)
    raise TimeoutError(job_id)


status = call('/api/status')
token = status['token']
print('ik_backend', status.get('ik_backend'), status.get('accelerator_abi') or '')
assert call('/api/jobs').get('active') is None, 'service busy'
paths = json.load(open(sys.argv[1], encoding='utf-8'))
runs = []
for i in range(int(sys.argv[2]) if len(sys.argv) > 2 else 3):
    s = call('/api/strokes', dict(paths=paths), token)
    sj, s_wall = wait(s['id'], token)
    t0 = time.monotonic()
    p = call('/api/plan', dict(image_job=s['id']), token)
    pj, p_wall = wait(p['id'], token)
    runs.append(dict(run=i, strokes_s=round(s_wall, 3), plan_wall_s=round(p_wall, 3), status=pj.get('status'),
                     detail=pj.get('detail'), error=pj.get('error'), metrics=(pj.get('result') or {}).get('metrics')))
    print(json.dumps(runs[-1], ensure_ascii=False)[:600], flush=True)
json.dump(dict(capabilities=status, runs=runs), open(sys.argv[3] if len(sys.argv) > 3 else '/home/xilinx/fp32_check/plan_bench.json', 'w'),
          ensure_ascii=False, indent=1)
