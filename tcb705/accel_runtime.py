"""Attach to the sealed seven-axis platform using the original 1013 boot receipt."""
import os
from pathlib import Path
from . import accel_contract as c

def platform_manifest():
    configured=os.environ.get('TCB705_PL_MANIFEST','')
    default=Path(__file__).resolve().parents[1]/'overlay/tcb705/platform.json'
    return Path(configured).resolve() if configured else (default if default.exists() else None)

def attached_identity():
    from platform_runtime import validate_manifest,validate_attached
    path=platform_manifest()
    if path is None:raise ValueError('Seven-axis platform is not configured; native CPU batches active')
    cfg,bit,_,registers,hashes,base,size=validate_manifest(path)
    if cfg.get('accelerator_abi') not in c.IDENTITIES or cfg['accelerator_abi']!=registers.get('abi'):raise ValueError('seven-axis ABI mismatch')
    validate_attached(bit,cfg['ip_name'],hashes,path)
    return cfg,registers,hashes,base,size

def platform_health():
    from lineart_backend import capability as lineart_capability
    lineart=lineart_capability()
    try:
        cfg,_,hashes,_,_=attached_identity()
        return dict(faulted=False,abi=cfg['accelerator_abi'],artifact_hashes=hashes,pl_load_policy='attach',build_id=cfg['build_id'],clock_hz=cfg['accelerator_clock_hz'],lineart=lineart)
    except Exception as exc:return dict(faulted=True,abi=c.ABI,reason=str(exc),lineart=lineart)

def ps_ddr_allocator(overlay):
    """Use the sealed HWH's PS DDR explicitly in every fresh PYNQ process."""
    from pynq import allocate
    memories=[m for m in overlay.mem_dict.values() if m.get('base_address')==0]
    if len(memories)!=1:
        raise ValueError('seven-axis planner requires one explicit PS DDR memory')
    memory=overlay.device.get_memory(memories[0])
    def allocator(**kwargs):
        # Keep the metadata/device owner alive for the entire DMA lifetime.
        _owner=overlay
        return allocate(target=memory,**kwargs)
    return allocator

def verify_planner_clock(expected_hz,abi=c.ABI):
    # PYNQ-Z1's default 50 MHz crystal reports clocks 1.5x too high on ATK Z20.
    # Read the actual PLL source/dividers using this board's 33.333333 MHz clock.
    # Constructing this reader only maps SLCR; it never writes PLL or dividers.
    from pynq.ps import _ClocksZynq
    from pynq import MMIO
    if MMIO(0xf8000000,0x1000).read(0x240)&3:
        raise ValueError('PS FCLK0/FCLK1 reset is asserted; do not access PL AXI')
    clocks=_ClocksZynq(ref_clk_mhz=33.333333)
    actual=float(clocks.get_pl_clk(1))*1000000
    if int(clocks.PL_CLK_CTRLS[1].SRCSEL) not in (0,1):
        raise ValueError('planner FCLK1 must use the verified IO PLL source')
    if abs(float(clocks.get_pl_clk(0))-100.)>.1:
        raise ValueError('display/touch FCLK0 must remain at 100 MHz')
    if abi not in c.IDENTITIES:raise ValueError('unknown seven-axis clock identity')
    valid_rate=(abs(actual-100000000)<=100000 and expected_hz==100000000) if abi==c.ABI_FP32 else 75000000<=actual<=80000000
    if not valid_rate or abs(actual-expected_hz)>expected_hz*.001:
        raise ValueError('physical FCLK1 differs from sealed planner clock: '+str(actual))
    return actual

def ensure_event_loop():
    """PYNQ asks asyncio for the thread's event loop while attaching. GUI plans run in a worker
    thread, which has none on Python 3.8: the PL silently fell back to CPU ("There is no current
    event loop in thread 'Thread-16'", seen on the board 2026-10-18)."""
    import asyncio
    global _shared_loop
    try:asyncio.get_event_loop()
    except RuntimeError:
        # One never-running loop shared by all planning threads: a new loop per plan would
        # leak its selector file descriptors in the long-running service.
        if _shared_loop is None or _shared_loop.is_closed():_shared_loop=asyncio.new_event_loop()
        asyncio.set_event_loop(_shared_loop)

_shared_loop=None

def open_accelerator():
    try:
        ensure_event_loop()
        cfg,registers,_,base,size=attached_identity()
        from pynq import MMIO,Overlay
        from planner_accel_backend import DDRTransport
        from planner_accel_lease import acquire_planner_lease
        from .planning_batches import PLChain
        lease=acquire_planner_lease(base)
        try:
            # Receipt and physical lease are checked before constructing PYNQ
            # metadata. This only attaches; it must never reprogram live LCD.
            overlay=Overlay(str(platform_manifest().parent/cfg['bitfile']),download=False)
            verify_planner_clock(cfg['accelerator_clock_hz'],cfg['accelerator_abi'])
            transport=DDRTransport(MMIO(base,size),registers,allocator=ps_ddr_allocator(overlay),
                timeout_s=30.,lease=lease,owns_lease=True,protocol=c)
        except BaseException:
            if not lease.pending:lease.close()
            raise
        return PLChain(transport),None
    except Exception as exc:return None,str(exc)
