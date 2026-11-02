"""Read actual HLS offsets, including pointer widths; never invent addresses."""
import argparse,hashlib,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lineart_contract import ABI,TOP,FIELDS,validate_registers
def extract(path):
    path=Path(path);defs=dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b',path.read_text(),re.M))
    out=dict(abi=ABI,top=TOP,header_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for field,words in FIELDS.items():
        prefix='XTCB_LINEART_ACCEL_CONTROL_'
        suffix='AP_RETURN' if field=='return' else field.upper()+'_DATA'
        name=prefix+'ADDR_'+suffix
        if name not in defs:raise ValueError('missing register '+name)
        out[field]=int(defs[name],0)
        if int(defs.get(prefix+'BITS_'+suffix,'0'),0)!=words*32:raise ValueError('incorrect width '+field)
    validate_registers(out);return out
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('header',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    a.output.write_text(json.dumps(extract(a.header),indent=2),encoding='utf-8')
