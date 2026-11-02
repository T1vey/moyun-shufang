"""Extract target ABI offsets and dimensions from the HLS generated header."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ik_target_contract import ABI,TOP,ARRAYS,FIELDS,validate_registers

def extract(path):
    path=Path(path)
    defs=dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b',path.read_text(),re.M))
    result={}
    for field in FIELDS:
        suffix='ADDR_AP_RETURN' if field=='return' else 'ADDR_'+field.upper()+('_BASE' if field in ARRAYS else '_DATA')
        name='XZ20_IK_TARGET_CONTROL_'+suffix
        if name not in defs: raise ValueError('missing HLS field '+name)
        result[field]=int(defs[name],0)
    for field,count in ARRAYS.items():
        for kind,expected in (('DEPTH',count),('WIDTH',32)):
            name='XZ20_IK_TARGET_CONTROL_'+kind+'_'+field.upper()
            if int(defs.get(name,'-1'),0)!=expected: raise ValueError('wrong HLS shape '+name)
    result.update(abi=ABI,top=TOP,header_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    validate_registers(result,True); return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('header',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args(); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(extract(a.header),indent=2)+'\n',encoding='utf-8')
    print('TARGET_REGISTER_MAP_WRITTEN',a.output)
