"""Offline measured calibration CLI. Never opens a servo or board connection."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kinematic_calibration import capture_template, fit_calibration, make_candidate


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    template = commands.add_parser('template', help='Create nine grid points x three blank contact readings')
    template.add_argument('--output', required=True)
    template.add_argument('--side-mm', type=float, default=100.)
    fit = commands.add_parser('fit', help='Fit measured/simulation contacts; only real ACCEPT can emit candidate')
    fit.add_argument('--machine', required=True)
    fit.add_argument('--captures', required=True)
    fit.add_argument('--report', required=True)
    fit.add_argument('--candidate', help='Optional new path; never the source machine.json')
    args = parser.parse_args(argv)
    if args.command == 'template':
        _write(args.output, capture_template(args.side_mm)); return 0
    inputs={Path(args.machine).resolve(),Path(args.captures).resolve()}
    outputs=[Path(args.report).resolve()]+([Path(args.candidate).resolve()] if args.candidate else [])
    if any(path in inputs for path in outputs) or len(set(outputs))!=len(outputs):
        parser.error('Report/candidate paths must be distinct and must not overwrite either input')
    machine, dataset = _read(args.machine), _read(args.captures)
    result = fit_calibration(machine, dataset)
    _write(args.report, result)
    print(json.dumps({key: result[key] for key in ('status','source','applicable_to_hardware','independent_validation','fit','quantized_fit','reasons')}, ensure_ascii=True))
    if args.candidate:
        try:
            candidate = make_candidate(machine, dataset, result)
        except ValueError as error:
            print('Candidate not written: '+str(error)); return 2
        _write(args.candidate, candidate)
    return 0 if result['status']=='ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
