"""Check delivery dependencies without loading the FPGA or opening a servo."""
import argparse
import importlib
import json
import platform
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def diagnose(require_pynq=False):
    report = dict(python=sys.version, architecture=platform.machine(),
                  system=platform.platform(), modules={}, errors=[])
    if sys.version_info < (3, 8):
        report['errors'].append('Python 3.8+ required')
    for name in ('numpy', 'scipy', 'PIL', 'cv2', 'skimage', 'svgpathtools', 'serial', 'ezdxf'):
        try:
            module = importlib.import_module(name)
            report['modules'][name] = getattr(module, '__version__', 'imported')
        except Exception as exc:
            report['errors'].append(name + ': ' + str(exc))
    try:
        import pynq
        report['pynq'] = pynq.__version__
    except ImportError:
        report['pynq'] = 'not available'
        if require_pynq:
            report['errors'].append('Use the board PYNQ Python environment')
    try:
        from vision import vendor
        vendor('image_processor'); vendor('dxf_converter')
        from planning import nominal
        nominal()
        from runtime_config import board_arguments
        board_arguments('config/runtime.ps.json')
    except Exception as exc:
        report['errors'].append('application: ' + str(exc))
    report['status'] = 'FAIL' if report['errors'] else 'PASS'
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--require-pynq', action='store_true')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    report = diagnose(a.require_pynq)
    data = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(data, encoding='utf-8')
    print(data)
    return bool(report['errors'])


if __name__ == '__main__':
    sys.exit(main())
