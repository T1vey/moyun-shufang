"""Packed binary Zhang-Suen ABI; independent of the seven-axis planner."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
ABI='tcb705-lineart-v1'
TOP='tcb_lineart_accel'
IDENTITY=0x4c410108
STAGES=8
MAX_DIM=1536
BASE=0x40010000
FIELDS={'src':2,'dst':2,'width':1,'height':1,'deleted':1,'identity':1,'return':1}

def validate_registers(registers, require_identity=True):
    if require_identity and (registers.get('abi')!=ABI or registers.get('top')!=TOP):
        raise ValueError('lineart register identity mismatch')
    occupied={0,4,8,12}
    for field,words in FIELDS.items():
        offset=registers.get(field)
        if type(offset) is not int or offset<16 or offset%4:raise ValueError('invalid lineart register '+field)
        slots=set(range(offset,offset+4*words,4))
        if slots&occupied:raise ValueError('overlapping lineart registers')
        occupied|=slots
    return max(occupied)+4

def pack_mask(mask):
    mask=np.asarray(mask,dtype=bool)
    if mask.ndim!=2 or not all(1<=d<=MAX_DIM for d in mask.shape):raise ValueError('lineart dimensions outside 1..1536')
    data=np.packbits(mask.reshape(-1),bitorder='little')
    padded=np.zeros(((mask.size+63)//64)*8,dtype=np.uint8)
    padded[:len(data)]=data
    return padded.view('<u8')

def unpack_mask(words,shape):
    n=int(np.prod(shape))
    return np.unpackbits(np.asarray(words,dtype='<u8').view(np.uint8),bitorder='little')[:n].reshape(shape).astype(bool)

def validate_hwh(path):
    tree=ET.parse(str(path)); modules=[m for m in tree.iter('MODULE') if m.get('INSTANCE')==TOP+'_0']
    if len(modules)!=1 or modules[0].get('MODTYPE')!=TOP:raise ValueError('lineart IP missing or ambiguous')
    ranges={(int(m.get('BASEVALUE'),0),int(m.get('HIGHVALUE'),0)) for m in tree.iter('MEMRANGE') if m.get('INSTANCE')==TOP+'_0'}
    if ranges!={(BASE,BASE+65535)}:raise ValueError('lineart address differs from 0x40010000/64K')
    clocks=modules[0].findall('./PORTS/PORT[@NAME="ap_clk"]')
    if len(clocks)!=1 or int(clocks[0].get('CLKFREQUENCY','0'))!=100000000:raise ValueError('lineart requires FCLK0 100 MHz')
    ps=[m for m in tree.iter('MODULE') if m.get('INSTANCE')=='processing_system7_0']
    if len(ps)!=1:raise ValueError('PS missing')
    params={p.get('NAME'):p.get('VALUE') for p in ps[0].findall('./PARAMETERS/PARAMETER')}
    if params.get('C_USE_S_AXI_HP2')!='1':raise ValueError('HP2 is not enabled')
    return dict(abi=ABI,ip_name=TOP+'_0',base=BASE,size=65536,clock_hz=100000000,
                stages=STAGES,max_dimension=MAX_DIM,packing='row-major-lsb-first-u64')

def validate_manifest_section(cfg,folder,bit):
    entry=cfg.get('lineart')
    if entry is None:return None
    expected=validate_hwh(bit.with_suffix('.hwh'))
    name='tcb_lineart.registers.json'
    if entry!={**expected,'registers':name}:raise ValueError('lineart manifest/HWH mismatch')
    if name not in cfg['files']:raise ValueError('lineart registers are not sealed')
    registers=json.loads((Path(folder)/name).read_text(encoding='utf-8'))
    validate_registers(registers)
    return entry,registers
