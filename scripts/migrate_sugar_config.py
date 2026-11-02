"""Generate the new scheme configuration; never overwrite the input or move motors."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from new_scheme_config import migrate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('machine',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.machine.resolve()==args.output.resolve():parser.error('Output must differ from input')
    if args.output.exists():parser.error('Output exists; choose a new filename')
    updated=migrate(json.loads(args.machine.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(updated,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),motion_sent=False,physical_acceptance='PENDING')))


if __name__=='__main__':main()
