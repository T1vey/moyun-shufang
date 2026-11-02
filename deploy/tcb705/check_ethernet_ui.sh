# Isolated loopback smoke test; never replaces the physical screen or sends motion.
set -eu
cd /home/xilinx/tcb705_releases/20261017_ethernet_preparation/ZYNQArm
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
/home/xilinx/ZYNQArm/.venv/bin/python - <<'PY'
import json,os,pathlib,signal,subprocess,time,urllib.request
root=pathlib.Path.cwd();log=root/'build/tcb705/ethernet_ui_smoke.log'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):
    with opener.open('http://127.0.0.1:18095'+path,timeout=10) as r:return r.read()
with log.open('w') as output:
    process=subprocess.Popen(['/home/xilinx/ZYNQArm/.venv/bin/python','scripts/run_tcb705.py',
        '--no-browser','--backend-port','18885','--web-port','18095',
        '--data-dir',str(root/'build/tcb705/ui_smoke')],stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline=time.monotonic()+60
        while True:
            if process.poll() is not None:raise RuntimeError('isolated UI exited early')
            try:status=json.loads(get('/api/tcb/status'));break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.5)
        assert not status['simulation'] and not status['allow_real']
        assert not status['readiness']['physical_ready']
        html=get('/debug').decode()
        for field in ('local-ip','sdk-port','remote-ip','web-port','snapshot'):
            assert 'id="'+field+'"' in html
        config=json.loads(get('/api/tcb/config'))
        assert config['controller']['remote_ip']=='' and config['controller']['local_ip']==''
        print(json.dumps({'isolated_ui_ok':True,'new_network_fields':True,
                          'physical_motion_enabled':False,'live_screen_changed':False}))
    finally:
        # Terminate only the temporary process group created above.
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
PY
systemctl is-active tcb705-ui so101-md0700r so101-gt911
