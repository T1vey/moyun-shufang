"""Read actual HLS-generated xz20_wls_step_hw.h; never guess array offsets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pl_contract import ABI, TOP, ARRAYS, validate_registers


def extract(path):
    text = Path(path).read_text(encoding='utf-8')
    definitions = dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b', text, re.M))
    result = {}
    for field in ('j','e','w','scales','dq','mu','mode','return'):
        suffix = 'ADDR_AP_RETURN' if field == 'return' else 'ADDR_'+field.upper()+('_BASE' if field in ('j','e','w','scales','dq') else '_DATA')
        matches = [int(value, 0) for name, value in definitions.items() if name.endswith('_'+suffix)]
        if len(matches) != 1:
            raise ValueError('HLS 头文件缺少唯一的 '+suffix)
        result[field] = matches[0]
    result['header_sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    result.update(abi=ABI, top=TOP)
    # HLS versions that emit array dimensions must agree with the software ABI.
    for field, count in ARRAYS.items():
        for suffix, expected in (('_DEPTH_'+field.upper(), count), ('_WIDTH_'+field.upper(),32)):
            values = [int(v,0) for name,v in definitions.items() if name.endswith(suffix)]
            if values and values != [expected]:
                raise ValueError('HLS 数组尺寸不匹配：'+suffix)
    validate_registers(result, require_identity=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('header', type=Path)
    parser.add_argument('output', type=Path, help='与 bit 同名，例如 drawing.registers.json')
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.header), indent=2)+'\n', encoding='utf-8')
    print('REGISTER_MAP_WRITTEN', args.output)
