"""Run selected hardware-free regressions and save a machine-readable result."""
from pathlib import Path
import json
import platform
import sys
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT), str(ROOT/'tests')]
MODULES=['test_tcb_fp32_contract','test_tcb_partial_prefix','test_tcb_unknown_residuals',
         'test_glyph_library_integrity','test_audio_player','test_audio_es8388',
         'test_audio_resampling','test_hwr']

if __name__=='__main__':
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    start=time.perf_counter()
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in MODULES)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'date':'2026-11-02','scope':'desktop offline; no FPGA load or robot motion',
            'python':platform.python_version(),'platform':platform.platform(),
            'modules':MODULES,'tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),
            'elapsed_s':round(time.perf_counter()-start,3),'passed':result.wasSuccessful()}
    out=ROOT/'docs/public_release_validation.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(not result.wasSuccessful())
