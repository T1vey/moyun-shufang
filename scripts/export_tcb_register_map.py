"""Extract the seven-axis DDR control ABI from the actual HLS header."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tcb705.accel_contract import ABI,TOP,ABI_FP32,TOP_FP32,FIELDS,validate_registers

def extract(path):
    path=Path(path)
    defs=dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b',path.read_text(),re.M))
    variants=[('XTCB_PLANNER_ACCEL_CONTROL_',ABI,TOP),('XTCB_PLANNER_PARALLEL_CONTROL_',ABI_FP32,TOP_FP32)]
    matches=[row for row in variants if row[0]+'ADDR_CONFIG_WORDS_DATA' in defs]
    if len(matches)!=1:raise ValueError('ambiguous or unsupported HLS seven-axis header')
    prefix,abi,top=matches[0]
    result={}
    for field,count in FIELDS.items():
        name=prefix+'ADDR_'+field.upper()+'_DATA'
        if name not in defs:raise ValueError('missing HLS field '+name)
        result[field]=int(defs[name],0)
        bits=prefix+'BITS_'+field.upper()+'_DATA'
        if int(defs.get(bits,'-1'),0)!=count*32:raise ValueError('wrong HLS register width '+field)
    result.update(abi=abi,top=top,header_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if abi==ABI_FP32:result['supported_modes']=[1]
    validate_registers(result,True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('header',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(extract(args.header),indent=2)+'\n',encoding='utf-8')
    print('PLANNER_REGISTER_MAP_WRITTEN',args.output)
