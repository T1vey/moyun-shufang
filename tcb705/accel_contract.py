"""Seven-axis port of the 1013 DDR ABI. Never accepts the five-axis IP identity."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from planner_accel_contract import layout, FIELDS, POINTERS
from planner_accel_contract import validate_registers as structural_register_check

ABI='tcb705-planner-accel-v1';TOP='tcb_planner_accel';MAGIC=0x54430701;MODEL_ID=0x37475231
ABI_FP32='tcb705-planner-fp32-v2';TOP_FP32='tcb_planner_parallel'
IDENTITIES={ABI:TOP,ABI_FP32:TOP_FP32}
CAP_FP32=1;CAP_RESIDUAL_NOT_EVALUATED=2;FP32_CAPABILITIES=3
IK_CHAIN=1;FK_ROWS=2;MAX_IK=64;MAX_FK=1024
CONTEXT=layout([('abi','<u4',0),('model_id','<u4',4),('context_id','<u4',8),('flags','<u4',12),
    ('model',('<f8',(7,21)),16),('tool',('<f8',(4,4)),1192),('options',('<f8',7),1320),
    ('seed',('<f8',7),1376),('rotation',('<f8',(3,3)),1432)],2048)
IK_INPUT=layout([('position',('<f8',3),0),('id','<u4',24),('flags','<u4',28)],32)
IK_OUTPUT=layout([('q',('<f8',7),0),('stats',('<f8',3),56),('status','<u4',80),
    ('id','<u4',84),('generation','<u4',88),('context_id','<u4',92)],128)
FK_INPUT=layout([('q',('<f8',7),0),('id','<u4',56),('flags','<u4',60)],64)
FK_OUTPUT=layout([('pose',('<f8',(4,4)),0),('id','<u4',128),('status','<u4',132)],192)
NAMES=('abi','status','job_id','generation','context_id','mode','requested','done_count','first_error','total_iterations','total_evaluations','capabilities')
HEADER=layout([(n,'<u4',4*i) for i,n in enumerate(NAMES)],64)
BUFFER_SIZES=(('config_words',2048),('input_words',65536),('output_words',196608),('result_words',64),('cancel_words',64))

def validate_registers(registers,require_identity=False):
    if require_identity or 'abi' in registers or 'top' in registers:
        if registers.get('abi') not in IDENTITIES or registers.get('top')!=IDENTITIES[registers['abi']]:raise ValueError('seven-axis accelerator identity mismatch')
        if registers['abi']==ABI_FP32 and registers.get('supported_modes')!=[IK_CHAIN]:raise ValueError('FP32 kernel requires explicit IK-only mode metadata')
    return structural_register_check({k:registers.get(k) for k in FIELDS})

def capabilities_for_top(top):
    if top not in IDENTITIES.values():raise ValueError('seven-axis accelerator top mismatch')
    return FP32_CAPABILITIES if top==TOP_FP32 else 0

def expected_capabilities(registers):
    validate_registers(registers)
    return capabilities_for_top(registers.get('top',TOP))

def clock_hz(hwh,top=None):
    tree=ET.parse(str(hwh));names=[(top+'_0')] if top else [x+'_0' for x in IDENTITIES.values()]
    modules=[m for m in tree.iter('MODULE') if m.get('INSTANCE') in names]
    if len(modules)!=1:raise ValueError('seven-axis clock module missing')
    pins=[p for p in modules[0].findall('./PORTS/PORT') if p.get('NAME')=='ap_clk']
    if len(pins)!=1:raise ValueError('seven-axis clock pin missing')
    rate=int(pins[0].get('CLKFREQUENCY','0'))
    ps=[m for m in tree.iter('MODULE') if m.get('INSTANCE')=='processing_system7_0']
    sources=[p.get('VALUE') for m in ps for p in m.findall('./PARAMETERS/PARAMETER') if p.get('NAME')=='PCW_FCLK1_PERIPHERAL_CLKSRC']
    if sources!=['IO PLL']:raise ValueError('seven-axis HWH requires IO PLL for FCLK1')
    clocks=[p for m in ps for p in m.findall('./PORTS/PORT') if p.get('NAME')=='FCLK_CLK1']
    fp32=modules[0].get('INSTANCE')==TOP_FP32+'_0'
    valid_rate=rate==100000000 if fp32 else 75000000<=rate<=80000000
    if len(clocks)!=1 or clocks[0].get('SIGNAME')!=pins[0].get('SIGNAME') or not valid_rate:
        raise ValueError('seven-axis core requires its verified independent FCLK1')
    return rate

def validate_reset_domain(tree,top=TOP):
    """Reject an AXI island held in reset before any physical MMIO access."""
    modules={m.get('INSTANCE'):m for m in tree.iter('MODULE')}
    def pin(module,name):
        items=[p.get('SIGNAME') for p in modules[module].findall('./PORTS/PORT') if p.get('NAME')==name]
        if len(items)!=1 or not items[0]:raise ValueError('seven-axis reset signal missing: '+module+'/'+name)
        return items[0]
    def parameter(module,name):
        items=[p.get('VALUE') for p in modules[module].findall('./PARAMETERS/PARAMETER') if p.get('NAME')==name]
        if len(items)!=1:raise ValueError('seven-axis reset parameter missing: '+name)
        return int(items[0],0)
    try:
        reset='rst_tcb_planner';ps='processing_system7_0'
        if parameter(reset,'C_EXT_RESET_HIGH')!=0 or parameter(reset,'C_AUX_RESET_HIGH')!=1:
            raise ValueError('seven-axis reset polarity would hold AXI in reset')
        if parameter('tcb_const_zero','CONST_VAL')!=0 or parameter('tcb_const_one','CONST_VAL')!=1:
            raise ValueError('seven-axis reset constants invalid')
        pairs=[((reset,'aux_reset_in'),('tcb_const_zero','dout')),
               ((reset,'mb_debug_sys_rst'),('tcb_const_zero','dout')),
               ((reset,'dcm_locked'),('tcb_const_one','dout')),
               ((reset,'ext_reset_in'),(ps,'FCLK_RESET1_N')),
               ((reset,'slowest_sync_clk'),(ps,'FCLK_CLK1')),
               ((top+'_0','ap_rst_n'),(reset,'peripheral_aresetn')),
               (('ps7_0_axi_periph','M06_ARESETN'),(reset,'peripheral_aresetn')),
               (('planner_ddr','ARESETN'),(reset,'peripheral_aresetn'))]
        if top==TOP_FP32:
            pairs.extend([(('planner_output_ddr','ARESETN'),(reset,'peripheral_aresetn')),
                          (('planner_output_ddr','ACLK'),(ps,'FCLK_CLK1')),
                          (('planner_ddr','ACLK'),(ps,'FCLK_CLK1'))])
        if any(pin(*a)!=pin(*b) for a,b in pairs):raise ValueError('seven-axis reset domain wiring mismatch')
    except KeyError as exc:raise ValueError('seven-axis reset module missing: '+str(exc)) from exc

def validate_overlay_files(bitfile,ip_name=None):
    from planner_accel_contract import validate_hwh_registers
    bit=Path(bitfile).resolve();files=[bit,bit.with_suffix('.hwh'),bit.with_suffix('.registers.json')]
    if any(not p.is_file() or not p.stat().st_size for p in files):raise ValueError('seven-axis platform requires bit/hwh/registers')
    registers=json.loads(files[2].read_text());required=validate_registers(registers,True)
    top=registers['top'];abi=registers['abi'];expected_name=top+'_0'
    if ip_name is None:ip_name=expected_name
    if ip_name!=expected_name:raise ValueError('seven-axis HWH instance mismatch')
    tree=ET.parse(str(files[1]));modules=[m for m in tree.iter('MODULE') if m.get('INSTANCE')==ip_name]
    if len(modules)!=1 or modules[0].get('VLNV')!='xilinx.com:hls:'+top+':1.0':raise ValueError('seven-axis HWH identity mismatch')
    validate_hwh_registers(modules[0],registers)
    clock_hz(files[1],top)
    validate_reset_domain(tree,top)
    ranges=[m for m in tree.iter('MEMRANGE') if m.get('INSTANCE')==ip_name]
    if not any(int(m.get('HIGHVALUE'),0)-int(m.get('BASEVALUE'),0)+1>=required for m in ranges):raise ValueError('missing control aperture')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    seal=bit.with_suffix('.artifacts.json')
    if seal.exists():
        doc=json.loads(seal.read_text())
        if doc.get('abi')!=abi or doc.get('files')!=hashes:raise ValueError('seven-axis seal mismatch')
    return registers,hashes

def context(model,seed,rotation):
    c=np.zeros(1,dtype=CONTEXT);c['abi']=MAGIC;c['model_id']=MODEL_ID
    c['model']=model.data;c['tool']=model.tool;c['seed']=seed;c['rotation']=rotation
    o=model.config['ik']
    c['options']=[o['position_tolerance_m'],o['orientation_tolerance_rad'],o['max_iterations'],o['step_limit_rad'],.1,o['damping'],o['reference_weight']]
    if o['max_iterations']>1000:raise ValueError('FPGA IK budget supports at most 1000 iterations')
    c['context_id']=int(hashlib.sha256(c.tobytes()).hexdigest()[:8],16) or 1
    return c

def validate_completion(header,rows,inputs,ctx,mode,job_id,generation,expected_capabilities=None):
    h={k:int(header[k][0]) for k in NAMES}
    caps=h['capabilities']
    if caps not in (0,FP32_CAPABILITIES) or (expected_capabilities is not None and caps!=expected_capabilities):
        raise FloatingPointError('seven-axis completion capability mismatch')
    if np.any(header[:1].view(np.uint8).reshape(-1)[48:64]):raise FloatingPointError('nonzero reserved completion fields')
    expected=dict(abi=MAGIC,job_id=job_id,generation=generation,context_id=int(ctx['context_id'][0]),mode=mode,requested=len(inputs))
    if any(h[k]!=v for k,v in expected.items()):raise FloatingPointError('seven-axis completion identity mismatch')
    n=h['done_count'];status=h['status']
    if not 0<=n<=len(inputs) or status not in range(6):raise FloatingPointError('invalid completion prefix')
    if status==0 and (n!=len(inputs) or h['first_error']!=0xffffffff):raise FloatingPointError('incomplete success')
    if status==1 and (n==0 or h['first_error']!=n-1):raise FloatingPointError('invalid partial prefix')
    if status==2 and h['first_error']!=n:raise FloatingPointError('invalid cancellation')
    if status>=3 and (n or h['first_error']!=0xffffffff or h['total_iterations']):raise FloatingPointError('invalid rejected batch')
    rows=rows[:n].copy()
    if not np.array_equal(rows['id'],inputs['id'][:n]):raise FloatingPointError('row order mismatch')
    if np.any(rows['status']>1):raise FloatingPointError('row status invalid')
    if status in (0,2) and np.any(rows['status']):raise FloatingPointError('failed success prefix')
    if status==1 and (np.any(rows['status'][:-1]) or rows['status'][-1]!=1):raise FloatingPointError('failed prefix invalid')
    if mode==IK_CHAIN:
        if not np.isfinite(rows['q']).all():raise FloatingPointError('nonfinite IK result')
        if caps==FP32_CAPABILITIES:
            success=rows['status']==0;stats=rows['stats']
            residual_bits=stats.view('<u8')[:,:2]
            if (np.any(residual_bits[success]!=np.uint64(0x7ff8000000000000))
                or not np.isfinite(stats[~success]).all() or np.any(stats[~success]<0)
                or not np.isfinite(stats[:,2]).all() or np.any(stats[:,2]!=0)):
                raise FloatingPointError('invalid unevaluated FP32 residuals')
        elif not np.isfinite(rows['stats']).all() or np.any(rows['stats']<0):raise FloatingPointError('nonfinite IK result')
        if np.any(rows['generation']!=generation) or np.any(rows['context_id']!=expected['context_id']):raise FloatingPointError('stale IK result')
        its=rows['stats'][:,2]
        if np.any(its!=np.floor(its)) or np.any(its>ctx['options'][0,2]) or int(its.sum())!=h['total_iterations']:raise FloatingPointError('invalid IK iteration count')
    elif mode==FK_ROWS:
        if not np.isfinite(rows['pose']).all() or h['total_iterations']:raise FloatingPointError('invalid FK result')
    else:raise FloatingPointError('invalid mode')
    if h['total_evaluations']:raise FloatingPointError('reserved evaluation field')
    return h,rows
