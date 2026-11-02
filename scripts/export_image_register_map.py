"""Export the generated z20_pl_image HLS AXI map; never guess offsets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pl_image_contract import ABI, TOP, FIELDS, validate_registers


def extract(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    definitions = dict(re.findall(r"^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b", text, re.M))
    result = {}
    for field in FIELDS:
        suffix = "ADDR_AP_RETURN" if field == "return" else "ADDR_" + field.upper() + "_DATA"
        prefix = "XZ20_PL_IMAGE_CONTROL_"
        matches = [int(value, 0) for name, value in definitions.items()
                   if name == prefix + suffix]
        if len(matches) != 1:
            # 兼容小写/无 _DATA 变体
            matches = [int(value, 0) for name, value in definitions.items()
                       if name.upper().startswith(prefix) and name.upper().endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("HLS 头文件缺少唯一的 " + prefix + suffix)
        result[field] = matches[0]
    result.update(abi=ABI, top=TOP,
                  header_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    validate_registers(result, require_identity=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("header", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(args.header), indent=2) + "\n", encoding="utf-8")
    print("IMAGE_REGISTER_MAP_WRITTEN", args.output)