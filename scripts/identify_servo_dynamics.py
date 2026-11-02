"""Offline unit/sag/lag fit from measurement JSON; never moves a servo."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from servo_identification import identify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',required=True,help='so101-servo-identification-v1 measured or simulation JSON')
    parser.add_argument('--report',required=True,help='New report path, not a live machine.json')
    args=parser.parse_args()
    if Path(args.samples).resolve()==Path(args.report).resolve():parser.error('Report cannot overwrite samples')
    dataset=json.loads(Path(args.samples).read_text(encoding='utf-8-sig'))
    result=identify(dataset)
    Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key]['status'] for key in ('speed','acceleration','load_bias','delay')}))


if __name__=='__main__':main()
