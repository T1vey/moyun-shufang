"""Extract the v2 DDR accelerator control ABI from an HLS generated header."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planner_accel_contract import ABI,TOP,FIELDS,validate_registers

def extract(path):
    path=Path(path)
    defs=dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b',path.read_text(),re.M))
    result={}
    for field,count in FIELDS.items():
        prefix='XPLANNER_ACCEL_V2_CONTROL_'
        name=prefix+'ADDR_'+field.upper()+'_DATA'
        if name not in defs:raise ValueError('missing HLS field '+name)
        result[field]=int(defs[name],0)
        bits=prefix+'BITS_'+field.upper()+'_DATA'
        if int(defs.get(bits,'-1'),0)!=count*32:raise ValueError('wrong HLS register width '+field)
    result.update(abi=ABI,top=TOP,header_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    validate_registers(result,True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('header',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(extract(args.header),indent=2)+'\n',encoding='utf-8')
    print('PLANNER_REGISTER_MAP_WRITTEN',args.output)
