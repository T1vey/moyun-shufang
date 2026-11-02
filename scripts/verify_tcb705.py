"""Repeat the relevant regression suite and save a compact auditable report."""
import argparse
import contextlib
import io
import json
import platform
from pathlib import Path
import sys
import time
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'build/tcb705/verification');args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    report={'python':sys.version,'platform':platform.platform(),'hardware_connected':False,'physical_motion':False,'cloud_stubbed':True,'suites':[]}
    passed=True
    for pattern in ('test_tcb705.py','test_tcb705_web.py','test_tcb705_kinfit.py','test_tcb_acceleration.py','test_tcb_platform.py','test_ge_pl_contract.py','test_tcb_session.py','test_armvision_calibration.py','test_tcb_commissioning.py','test_tcb705_lineart_plan.py','test_user_gui_gallery.py','test_cloud_gallery.py','test_user_gui_workflow.py','test_drawing_quality.py','test_lineart_accel.py','test_lineart_attachment.py','test_cloud_transport.py','test_planner_accel_lifetime.py','test_md0700r_runtime.py'):
        log=io.StringIO();started=time.perf_counter()
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern)
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        (args.output/(pattern+'.txt')).write_text(log.getvalue(),encoding='utf-8')
        row=dict(suite=pattern,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),seconds=time.perf_counter()-started)
        report['suites'].append(row);passed=passed and result.wasSuccessful() and result.testsRun>0
        print(json.dumps(row),flush=True)
    report['passed']=passed;report['tests']=sum(x['tests'] for x in report['suites'])
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
