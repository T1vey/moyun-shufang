"""Offline merged regression entry point. No board/robot/network targets permitted."""
import datetime,hashlib,ipaddress,json,os,pathlib,socket,sys,time,unittest

ROOT=pathlib.Path(__file__).resolve().parents[3]
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))  # Match unittest discover for existing bare fixture imports.
REPORT=ROOT/'build/tcb705/parallel_20261024/final_software_validation.json'
if '--retry-imports' in sys.argv:REPORT=REPORT.with_name('final_software_validation_retry.json')
LOG=REPORT.with_suffix('.log')
os.environ['TCB705_PL_MANIFEST']=str(REPORT.parent/'offline_no_platform.json')

def local_host(host):
    if host is None:return True
    if isinstance(host,bytes):host=host.decode('ascii')
    if host=='localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False

real_connect=socket.socket.connect
real_connect_ex=socket.socket.connect_ex
real_getaddrinfo=socket.getaddrinfo
def checked_connect(sock,address):
    if not isinstance(address,tuple) or not local_host(address[0]):
        raise AssertionError('Offline regression forbids non-loopback connections: '+repr(address))
    return real_connect(sock,address)
def checked_connect_ex(sock,address):
    if not isinstance(address,tuple) or not local_host(address[0]):
        raise AssertionError('Offline regression forbids non-loopback connections: '+repr(address))
    return real_connect_ex(sock,address)
def checked_getaddrinfo(host,*args,**kwargs):
    if not local_host(host):raise AssertionError('Offline regression forbids external DNS: '+repr(host))
    return real_getaddrinfo(host,*args,**kwargs)
socket.socket.connect=checked_connect;socket.socket.connect_ex=checked_connect_ex
socket.getaddrinfo=checked_getaddrinfo

NAMES=[
    'tests.test_user_gui_workflow','tests.test_user_gui_gallery',
    'tests.test_lineart_attachment','tests.test_lineart_capability','tests.test_lineart_accel.LineartTransport',
    'tests.test_tcb705.HttpTests','tests.test_calligraphy_stop_workflow','tests.test_calligraphy_speed',
    'tests.test_tcb_execution_without_runtime_fk','tests.test_tcb_planning_without_runtime_fk',
    'tests.test_handwriting','tests.test_handwriting_executor','tests.test_handwriting_auth',
    'tests.test_calligraphy','tests.test_calligraphy_merge','tests.test_calligraphy_home',
    'tests.test_text_calligraphy','tests.test_brush_depth_limit',
    'tests.test_tcb_fp32_contract','tests.test_tcb_unknown_residuals','tests.test_tcb_partial_prefix',
    'tests.test_tcb_acceleration','tests.test_tcb705_lineart_plan',
]
if '--retry-imports' in sys.argv:
    NAMES=['tests.test_tcb_execution_without_runtime_fk','tests.test_handwriting_executor']
started=time.time()
with LOG.open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(NAMES))
summary=dict(status='PASS' if result.wasSuccessful() else 'FAIL',
    started_at=datetime.datetime.fromtimestamp(started,datetime.timezone.utc).isoformat(),
    seconds=round(time.time()-started,3),command=[sys.executable,'-X','utf8',str(pathlib.Path(__file__).resolve()),*sys.argv[1:]],
    equivalent_unittest_command=[sys.executable,'-X','utf8','-m','unittest',*NAMES,'-v'],
    tests_run=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)-len(result.expectedFailures)-len(result.unexpectedSuccesses),
    skipped=len(result.skipped),failed=len(result.failures),errors=len(result.errors),
    expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses),
    failures=[dict(test=str(test),traceback=trace) for test,trace in result.failures+result.errors],
    skip_details=[dict(test=str(test),reason=reason) for test,reason in result.skipped],
    hardware_actions=False,board_connections=False,robot_motion=False,
    guards=['non-loopback socket connect/connect_ex blocked','external DNS blocked','nonexistent PL manifest selected; tests use mocks'],
    modules=NAMES,log=str(LOG),source_sha256={})
for rel in ('tcb705/planner.py','tcb705/planning_batches.py','tcb705/web_executor.py','handwriting/planner.py',
            'calligraphy/execution.py','tcb705/accel_contract.py','tcb705/accel_runtime.py','user_gui/workflow.py','lineart_backend.py'):
    summary['source_sha256'][rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
REPORT.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('status','tests_run','passed','skipped','failed','errors','seconds','log')},ensure_ascii=False),flush=True)
sys.exit(0 if result.wasSuccessful() else 1)
