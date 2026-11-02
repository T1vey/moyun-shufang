"""Extract the upstream scalar ABI from the actual HLS-generated hardware header."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from upstream_backend import ABI, TOP, FIELDS, validate_map


def extract(path):
    raw = Path(path).read_bytes()
    definitions = dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b',raw.decode('utf-8'),re.M))
    result = dict(abi=ABI,top=TOP,header_sha256=hashlib.sha256(raw).hexdigest())
    for field in FIELDS:
        suffix = '_ADDR_'+field.upper()+'_DATA'
        matches = [int(value,0) for name,value in definitions.items() if name.endswith(suffix)]
        if len(matches)!=1:
            raise ValueError('HLS header requires exactly one '+suffix)
        result[field] = matches[0]
        widths = [int(value,0) for name,value in definitions.items() if name.endswith('_BITS_'+field.upper()+'_DATA')]
        if widths and widths != [32]:
            raise ValueError('Expected float32/int32 scalar: '+field)
    validate_map(result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('header',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    args.output.write_text(json.dumps(extract(args.header),indent=2)+'\n',encoding='utf-8')
    print('UPSTREAM_REGISTER_MAP_WRITTEN',args.output)
