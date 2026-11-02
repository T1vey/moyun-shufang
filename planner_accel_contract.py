"""Explicit little-endian DDR ABI for the optional planner accelerator v2."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from ik_target_backend import target_inputs
from ik_contract import model_matches_nominal

ABI='so101-planner-accel-v2'
TOP='planner_accel_v2'
MAGIC=0x534f0401
MODEL_ID=0x535a5958
IK_CHAIN=1
FK_ROWS=2
MAX_IK=64
MAX_FK=1024
POINTERS=('config_words','input_words','output_words','result_words','cancel_words')
FIELDS=dict([(k,2) for k in POINTERS]+[(k,1) for k in ('mode','count','output_capacity','job_id','generation')])
BATCH_STATUS={0:'OK',1:'PARTIAL',2:'CANCELLED',3:'BAD_ABI',4:'BAD_MODEL',5:'BAD_INPUT',6:'NONFINITE',7:'BUDGET'}

def layout(fields,size):
    return np.dtype({'names':[x[0] for x in fields], 'formats':[x[1] for x in fields],
                     'offsets':[x[2] for x in fields], 'itemsize':size})

IK_INPUT=layout([('position',('<f4',3),0),('axis',('<f4',3),12),('id','<u4',24),('flags','<u4',28)],32)
IK_OUTPUT=layout([('q',('<f4',5),0),('position_error','<f4',20),('tilt_error','<f4',24),
    ('status','<u4',28),('iterations','<u4',32),('evaluations','<u4',36),('id','<u4',40),
    ('generation','<u4',44),('context_id','<u4',48),('flags','<u4',52)],64)
FK_INPUT=layout([('q',('<f8',5),0),('id','<u4',40),('segment_id','<u4',44),('kind','<u4',48)],64)
FK_OUTPUT=layout([('tip',('<f4',3),0),('axis',('<f4',3),12),('id','<u4',24),('status','<u4',28)],32)
HEADER_NAMES=('abi','status','job_id','generation','context_id','mode','requested','done_count',
              'first_error','total_iterations','total_evaluations')
HEADER=layout([(name,'<u4',i*4) for i,name in enumerate(HEADER_NAMES)],64)
CONTEXT=layout([
    ('abi','<u4',0),('model_id','<u4',4),('context_id','<u4',8),('flags','<u4',12),
    ('weights',('<f4',6),16),('scales',('<f4',6),40),('tool',('<f4',3),64),
    ('tool_axis',('<f4',3),76),('limits',('<f4',10),88),('seed',('<f4',5),128),
    ('mu','<f4',148),('max_step','<f4',152),('position_tol','<f4',156),('tilt_tol','<f4',160),
    ('stagnation_change','<f4',164),('max_iterations','<u4',168),('line_search_trials','<u4',172),
    ('stagnation_window','<u4',176),('solve_mode','<u4',180),('iterations_per_target','<u4',184),
    ('iterations_per_attempt','<u4',188),('total_iteration_budget','<u4',192)],512)

def context(model,q,config,mode='wls',total_budget=None):
    arrays,floats,integers=target_inputs(model,[0.,0.,0.],[0.,0.,1.],q,config,mode)
    budget=integers[0] if total_budget is None else total_budget
    if type(budget) is not int or not 1<=budget<=0xffffffff:
        raise ValueError('invalid batch iteration budget')
    result=np.zeros(1,dtype=CONTEXT)
    result['abi']=MAGIC;result['model_id']=MODEL_ID
    for key,value in zip(('seed','weights','scales','tool','tool_axis','limits'),[arrays[0]]+arrays[3:]):
        result[key]=value
    for key,value in zip(('mu','max_step','position_tol','tilt_tol','stagnation_change'),floats):
        result[key]=float(value)*(.999 if key in ('position_tol','tilt_tol') else 1.)
    for key,value in zip(('max_iterations','line_search_trials','stagnation_window','solve_mode'),integers):
        result[key]=value
    result['iterations_per_target']=integers[0]
    result['iterations_per_attempt']=integers[0]
    result['total_iteration_budget']=budget
    identity=hashlib.sha256(result.tobytes()).hexdigest()
    result['context_id']=int(identity[:8],16) or 1
    return result,identity

def validate_registers(registers,require_identity=False):
    if not isinstance(registers,dict):raise ValueError('planner register map required')
    if require_identity or 'abi' in registers or 'top' in registers:
        if registers.get('abi')!=ABI or registers.get('top')!=TOP:raise ValueError('planner ABI identity mismatch')
    occupied={0,4,8,12}
    for field,count in FIELDS.items():
        offset=registers.get(field)
        if type(offset) is not int or offset<16 or offset%4:raise ValueError('invalid register '+field)
        addresses=set(range(offset,offset+4*count,4))
        if occupied & addresses:raise ValueError('register overlap '+field)
        occupied.update(addresses)
    if max(occupied)>=65536:raise ValueError('planner register map exceeds aperture')
    return max(occupied)+4

def validate_ip(description,required):
    if description.get('type')!='xilinx.com:hls:'+TOP+':1.0':raise ValueError('planner HWH identity mismatch')
    if type(description.get('addr_range')) is not int or description['addr_range']<required:
        raise ValueError('planner control aperture too small')

def validate_hwh_registers(module,registers):
    """Require full widths, including Vivado's two 32-bit pointer registers."""
    found={}
    for reg in module.iter('REGISTER'):
        name=reg.get('NAME')
        props={p.get('NAME'):p.get('VALUE') for p in reg.findall('PROPERTY')}
        if 'ADDRESS_OFFSET' not in props:continue
        if name in found:raise ValueError('duplicate HWH register '+str(name))
        found[name]=(int(props['ADDRESS_OFFSET'],0),int(props['SIZE'],0) if 'SIZE' in props else None)
    normalized={}
    for field,count in FIELDS.items():
        names={name for name in found if name==field or name.startswith(field+'_')}
        if count==2 and names=={field+'_1',field+'_2'}:
            expected=[(field+'_1',registers[field],32),(field+'_2',registers[field]+4,32)]
        elif names=={field}:
            expected=[(field,registers[field],32*count)]
        else:raise ValueError('HWH register representation mismatch '+field)
        for name,offset,width in expected:
            if found[name][0]!=offset:raise ValueError('HWH register mismatch '+name)
            if found[name][1]!=width:raise ValueError('HWH register width mismatch '+name)
        normalized[field]=[dict(name=name,offset=offset,width=width) for name,offset,width in expected]
    return normalized

def validate_overlay_files(bitfile,ip_name=TOP+'_0'):
    bitfile=Path(bitfile).resolve()
    files={suffix:bitfile.with_suffix(suffix) for suffix in ('.bit','.hwh','.registers.json')}
    if any(not p.is_file() or not p.stat().st_size for p in files.values()):
        raise ValueError('planner requires matching bit/hwh/registers files')
    registers=json.loads(files['.registers.json'].read_text(encoding='utf-8'))
    required=validate_registers(registers,True)
    tree=ET.parse(files['.hwh']).getroot()
    modules=[m for m in tree.iter('MODULE') if m.get('INSTANCE')==ip_name]
    if len(modules)!=1 or modules[0].get('VLNV')!='xilinx.com:hls:'+TOP+':1.0':
        raise ValueError('planner HWH IP identity mismatch')
    validate_hwh_registers(modules[0],registers)
    ranges=[m for m in tree.iter('MEMRANGE') if m.get('INSTANCE')==ip_name]
    if not any(int(m.get('HIGHVALUE'),0)-int(m.get('BASEVALUE'),0)+1>=required for m in ranges):
        raise ValueError('planner address window missing')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files.values()}
    seal=bitfile.with_suffix('.artifacts.json')
    if seal.is_file():
        doc=json.loads(seal.read_text(encoding='utf-8'))
        if doc.get('abi')!=ABI or doc.get('files')!=hashes:raise ValueError('planner artifact seal mismatch')
    return registers,hashes

def validate_completion(header,rows,inputs,ctx,mode,job_id,generation):
    h={k:int(header[k][0]) for k in HEADER_NAMES}
    expected=dict(abi=MAGIC,job_id=job_id,generation=generation,context_id=int(ctx['context_id'][0]),
                  mode=mode,requested=len(inputs))
    if any(h[k]!=v for k,v in expected.items()):raise FloatingPointError('stale/invalid planner completion identity')
    if h['status'] not in BATCH_STATUS or not 0<=h['done_count']<=len(inputs):
        raise FloatingPointError('invalid planner completion count/status')
    n=h['done_count'];status=h['status']
    if status==0 and (n!=len(inputs) or h['first_error']!=0xffffffff):
        raise FloatingPointError('incomplete planner success')
    if status==1 and (not n or h['first_error']!=n-1):raise FloatingPointError('invalid planner failure prefix')
    if status==2 and h['first_error']!=n:raise FloatingPointError('invalid planner cancellation prefix')
    if status==7 and (n>=len(inputs) or h['first_error']!=n):raise FloatingPointError('invalid planner budget prefix')
    if status in (3,4,5,6) and (n or h['first_error']!=0xffffffff or h['total_iterations'] or h['total_evaluations']):
        raise FloatingPointError('invalid planner preflight failure')
    rows=rows[:n].copy()
    if not np.array_equal(rows['id'],inputs['id'][:n]):raise FloatingPointError('planner result order mismatch')
    if mode==IK_CHAIN:
        if np.any(rows['generation']!=generation) or np.any(rows['context_id']!=expected['context_id']):
            raise FloatingPointError('planner row identity mismatch')
        if (np.any(rows['status']>5) or not np.isfinite(rows['q']).all()
            or not np.isfinite(rows['position_error']).all() or not np.isfinite(rows['tilt_error']).all()
            or np.any(rows['position_error']<0) or np.any(rows['tilt_error']<0)
            or np.any(rows['flags']!=0)):
            raise FloatingPointError('invalid planner IK row')
        if status in (0,2,7) and np.any(rows['status']!=0):raise FloatingPointError('planner failed row in successful prefix')
        if status==1 and (np.any(rows['status'][:-1]!=0) or not rows['status'][-1]):
            raise FloatingPointError('invalid planner solver failure prefix')
        if int(rows['iterations'].astype(np.uint64).sum())!=h['total_iterations']:
            raise FloatingPointError('planner iteration total mismatch')
        if int(rows['evaluations'].astype(np.uint64).sum())!=h['total_evaluations']:
            raise FloatingPointError('planner evaluation total mismatch')
        maximum=int(ctx['max_iterations'][0]);trials=int(ctx['line_search_trials'][0])
        if (np.any(rows['iterations']>maximum) or np.any(rows['evaluations']>1+maximum*trials)
            or h['total_iterations']>int(ctx['total_iteration_budget'][0])):
            raise FloatingPointError('planner computation budget mismatch')
    else:
        if h['total_iterations'] or h['total_evaluations']>n:
            raise FloatingPointError('invalid FK computation counters')
        if status in (0,2) and h['total_evaluations']!=n:
            raise FloatingPointError('incomplete FK computation counters')
        if np.any(rows['status']>2) or not np.isfinite(rows['tip']).all() or not np.isfinite(rows['axis']).all():
            raise FloatingPointError('invalid planner FK row')
        if status in (0,2) and np.any(rows['status']):raise FloatingPointError('planner failed FK success')
        if status==7:raise FloatingPointError('FK cannot exhaust IK iteration budget')
        if status==1 and (np.any(rows['status'][:-1]!=0) or not rows['status'][-1]):
            raise FloatingPointError('invalid planner FK failure prefix')
    return h,rows
