"""Generated-register contract for a complete bounded target solver."""
from ik_contract import model_matches_nominal

ABI = 'so101-ik-target-v1'
TOP = 'z20_ik_target'
MAGIC = 0x534F0301
ARRAYS = dict(q_init=5,target_position=3,target_axis=3,weights=6,scales=6,
              tool=3,tool_axis=3,limits=10,q_result=5)
FIELDS = dict(ARRAYS,mu=1,max_step=1,position_tolerance=1,tilt_tolerance=1,
              stagnation_cost_change=1,max_iterations=1,line_search_trials=1,
              stagnation_window=1,mode=1,position_error=1,tilt_error=1,
              iterations_used=1,evaluations_used=1,abi_version=1,**{'return':1})
STATUSES = {0:'OK',1:'INVALID_INPUT',2:'NUMERIC',3:'MAX_ITER',4:'STAGNATION',5:'LIMIT_STALL'}

def validate_registers(registers, require_identity=False):
    if not isinstance(registers,dict):
        raise ValueError('需要完整目标求解器寄存器映射')
    if require_identity or 'abi' in registers or 'top' in registers:
        if registers.get('abi')!=ABI or registers.get('top')!=TOP:
            raise ValueError('需要 so101-ik-target-v1 映射；不能使用单步核映射')
    occupied={0,4,8,12}
    for field,count in FIELDS.items():
        offset=registers.get(field)
        if type(offset) is not int or offset<16 or offset%4:
            raise ValueError('无效寄存器 '+field)
        addresses=set(range(offset,offset+4*count,4))
        if addresses & occupied: raise ValueError('寄存器重叠 '+field)
        occupied.update(addresses)
    return max(occupied)+4

def validate_ip(description, required):
    parts=str(description.get('type','')).split(':')
    if len(parts)!=4 or parts[2]!=TOP:
        raise ValueError('hwh 中不是 z20_ik_target')
    if type(description.get('addr_range')) is not int or description['addr_range']<required:
        raise ValueError('AXI 地址窗口不足')

def validate_overlay_files(bitfile, ip_name='z20_ik_target_0'):
    """Check generated metadata and optional release hashes before PL download."""
    import hashlib
    import json
    from pathlib import Path
    import xml.etree.ElementTree as ET
    bitfile = Path(bitfile).resolve()
    files = {s: bitfile.with_suffix(s) for s in ('.bit', '.hwh', '.registers.json')}
    for path in files.values():
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing target overlay artifact: ' + str(path))
    registers = json.loads(files['.registers.json'].read_text(encoding='utf-8'))
    required = validate_registers(registers, True)
    tree = ET.parse(files['.hwh']).getroot()
    modules = [m for m in tree.iter('MODULE') if m.get('INSTANCE') == ip_name]
    if len(modules) != 1 or modules[0].get('VLNV') != 'xilinx.com:hls:z20_ik_target:1.0':
        raise ValueError('HWH target IP identity mismatch')
    offsets = {}
    for reg in modules[0].iter('REGISTER'):
        props = {p.get('NAME'): p.get('VALUE') for p in reg.findall('PROPERTY')}
        if 'ADDRESS_OFFSET' in props:
            offsets[reg.get('NAME')] = int(props['ADDRESS_OFFSET'], 0)
    for field in FIELDS:
        name = 'Memory_' + field if field in ARRAYS else 'ap_return' if field == 'return' else field
        if offsets.get(name) != registers[field]:
            raise ValueError('HWH register offset mismatch: ' + field)
    ranges = [m for m in tree.iter('MEMRANGE') if m.get('INSTANCE') == ip_name]
    if not any(int(m.get('HIGHVALUE'), 0) - int(m.get('BASEVALUE'), 0) + 1 >= required for m in ranges):
        raise ValueError('HWH target address window missing')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files.values()}
    seal = bitfile.with_suffix('.artifacts.json')
    if seal.is_file():
        doc = json.loads(seal.read_text(encoding='utf-8'))
        if doc.get('abi') != ABI or doc.get('files') != hashes:
            raise ValueError('Overlay artifacts changed since packaging')
    return registers, hashes
