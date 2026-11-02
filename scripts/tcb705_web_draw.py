"""Drive the running TCB705 backend (app.py --allow-real, web profile) end to end:
strokes -> local plan (7-axis IK on PL/CPU, start read from the controller) -> execute.

  python scripts/tcb705_web_draw.py --circle 30            # plan only, prints metrics + preview path
  python scripts/tcb705_web_draw.py --circle 30 --execute  # draws (person at E-stop)
  python scripts/tcb705_web_draw.py --plan-job <id> --execute
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.arm_studio import BoardClient  # noqa: E402


def wait(client, jid, timeout=900):
    t0 = time.monotonic(); last = ''
    while time.monotonic() - t0 < timeout:
        s = client.get_jobs(); j = next((j for j in s['jobs'] if j['id'] == jid), None)
        if j and j.get('detail') != last:
            last = j.get('detail'); print('JOB', jid, j['status'], last, flush=True)
        if j and j['status'] != 'RUNNING' and s.get('active') != jid:
            return j
        time.sleep(0.3)
    raise SystemExit('job timeout ' + jid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8785)
    ap.add_argument('--circle', type=float, help='circle diameter mm at paper centre')
    ap.add_argument('--plan-job'); ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    client = BoardClient(port=args.port)
    caps = client.fetch_status()
    print('BACKEND', json.dumps({k: caps.get(k) for k in ('robot_type', 'simulation', 'allow_real', 'ik_backend', 'readiness')}, ensure_ascii=False))
    pid = args.plan_job
    if pid is None:
        if not args.circle:
            raise SystemExit('give --circle or --plan-job')
        cfg = client._request('/api/config')
        cfg = cfg.get('config', cfg)
        w, h = cfg['paper']['width_mm'], cfg['paper']['height_mm']; r = args.circle / 2
        n = max(24, int(math.ceil(math.pi * args.circle / 1.0)))
        pts = [[round(w / 2 + r * math.cos(2 * math.pi * k / n), 4), round(h / 2 + r * math.sin(2 * math.pi * k / n), 4)] for k in range(n + 1)]
        paths = dict(units='mm', width_mm=w, height_mm=h, coordinate_system='full_canvas_xy_up', paths=[pts])
        sid = client._request('/api/strokes', method='POST', data={'paths': paths})['id']
        j = wait(client, sid)
        if j['status'] != 'DONE':
            raise SystemExit('strokes failed: %s' % j.get('detail'))
        pid = client._request('/api/plan', method='POST', data={'image_job': sid})['id']
        j = wait(client, pid)
        if j['status'] != 'DONE':
            raise SystemExit('plan failed: %s' % j.get('detail'))
        print('PLAN', pid, json.dumps(j.get('result', {}).get('metrics', {}), ensure_ascii=False)[:800])
        print('PREVIEW', 'http://127.0.0.1:%d/api/plans/%s/preview.svg' % (args.port, pid))
    if not args.execute:
        return 0
    xid = client._request('/api/execute', method='POST', data={'plan_job': pid, 'confirm_physical': True})['id']
    j = wait(client, xid, timeout=3600)
    print('EXECUTE', j['status'], j.get('detail'))
    print('RESULT', json.dumps({k: v for k, v in (j.get('result') or {}).items() if k != 'log'}, ensure_ascii=False))
    return 0 if j['status'] == 'DONE' else 2


if __name__ == '__main__':
    sys.exit(main())
