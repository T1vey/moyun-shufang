"""Load the MD0700R + IK platform once per Linux boot; never moves servos."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_runtime import (READY, BOOT_ID, PLANNER_ABI, TCB_ABI, TCB_FP32_ABI, digest, validate_manifest,
                              validate_attached, accelerator_identity, display_backend)


def planner_fk_self_test(core,model,qs,config):
    """Check actual shadow telemetry, not only the returned PS reference values."""
    import math
    import numpy as np
    before=int(core.metrics().get('fk_rows_checked',0))
    tips,axes=core.fk_rows(model,qs,config)
    poses=model.pose_many(qs)
    np.testing.assert_allclose(tips,poses[:,:3,3],atol=2e-6,rtol=0)
    np.testing.assert_allclose(axes,poses[:,:3,:3]@model.tool_axis,atol=2e-5,rtol=0)
    metrics=core.metrics()
    errors=(metrics.get('fk_max_position_difference_m'),metrics.get('fk_max_axis_difference'))
    if (core.faulted or metrics.get('fk_mode')!='shadow_only'
        or metrics.get('fk_rows_checked',0)-before!=len(qs)
        or any(not isinstance(v,(float,int)) or not math.isfinite(v) or v<0 for v in errors)
        or errors[0]>2e-6 or errors[1]>2e-5):
        raise RuntimeError('Platform batch FK self-test failed')


def prepare_display_receipt(cfg, directory, timeout):
    """DRM needs a connector; userspace services start only after the receipt."""
    if display_backend(cfg)=='pynq-mmio':
        return
    deadline=time.monotonic()+timeout
    while not list(Path('/sys/class/drm').glob('card*-*')):
        if time.monotonic()>deadline:
            raise RuntimeError('No DRM display connector; platform not marked ready')
        time.sleep(.2)
    connector=sorted(Path('/sys/class/drm').glob('card*-*'))[0]
    card=connector.name.split('-',1)[0]
    xorg=('Section "Device"\n Identifier "SO101 LCD"\n Driver "modesetting"\n'
          ' Option "kmsdev" "/dev/dri/'+card+'"\n Option "AccelMethod" "none"\nEndSection\n')
    (directory/'xorg.conf').write_text(xorg)


@contextmanager
def downloaded_backend(abi,bit,dtbo,base,size,registers):
    """Own the physical IP before any download, including legacy maintenance."""
    from planner_accel_lease import acquire_planner_lease
    from pynq import Overlay,MMIO
    if abi in (TCB_ABI,TCB_FP32_ABI):
        from tcb705.planning_batches import PLChain
        from tcb705 import accel_contract
        from tcb705.accel_runtime import ps_ddr_allocator
        from planner_accel_backend import DDRTransport
    elif abi==PLANNER_ABI:
        from planner_accel_backend import PynqPlannerAccel as Backend
    else:
        from ik_target_backend import PynqIKTarget as Backend
    with acquire_planner_lease(base) as lease:
        overlay_args=dict(download=False)
        if dtbo is not None:overlay_args['dtbo']=str(dtbo)
        overlay=Overlay(str(bit),**overlay_args)
        overlay.download()
        kwargs=dict(mmio=MMIO(base,size),registers=registers)
        if abi in (PLANNER_ABI,TCB_ABI,TCB_FP32_ABI):kwargs['lease']=lease
        core=PLChain(DDRTransport(**kwargs,protocol=accel_contract,timeout_s=30.,allocator=ps_ddr_allocator(overlay))) if abi in (TCB_ABI,TCB_FP32_ABI) else Backend(**kwargs)
        try:
            yield core
        finally:
            if abi in (PLANNER_ABI,TCB_ABI,TCB_FP32_ABI):
                failing=sys.exc_info()[0] is not None
                try:core.transport.close()
                except RuntimeError:
                    # In-flight transport retains itself/buffers/lease until
                    # hardware drains. Preserve the initiating failure.
                    if not failing or not core.transport.inflight:raise


def load(manifest, ready=READY, timeout=30, backend_port=8765):
    import fcntl
    if os.geteuid()!=0:
        raise PermissionError('Platform loading requires root')
    Path('/run/lock').mkdir(exist_ok=True)
    with open('/run/lock/so101-platform.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        cfg,bit,dtbo,registers,hashes,base,size=validate_manifest(manifest,platform.release())
        abi,ip=accelerator_identity(cfg)
        receipt=Path(ready)
        if receipt.exists():
            validate_attached(bit,ip,hashes,manifest,ready,kernel_release=platform.release())
            print('PLATFORM_ALREADY_READY');return
        if list(Path('/sys/bus/platform/devices/e000c000.ethernet/net').glob('*')):
            raise RuntimeError('GE_PL is attached. Reboot before full FPGA reconfiguration.')
        if list(Path('/sys/class/drm').glob('card*-*')):
            raise RuntimeError('A display driver is already bound. Reboot into the selected platform.')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',backend_port))==0:
                raise RuntimeError('Stop workbench before platform maintenance')
        for name in ('status.json','touch.json'):
            status=Path('/run/so101-lcd')/name
            if status.exists():
                raise RuntimeError('Stop the userspace display and touch services before platform maintenance')
        with downloaded_backend(abi,bit,dtbo,base,size,registers) as core:
            if abi in (TCB_ABI,TCB_FP32_ABI):
                from tcb705.accel_selftest import self_test
                from tcb705.accel_runtime import verify_planner_clock
                print('TCB705_PHYSICAL_CLOCK_HZ',verify_planner_clock(cfg['accelerator_clock_hz'],abi),flush=True)
                print('TCB705_AXI_PROBE_BEGIN',flush=True)
                control=core.transport.mmio.read(0)
                if not control&4:raise RuntimeError('Seven-axis AXI responds but accelerator is not idle')
                print('TCB705_AXI_CONTROL',hex(control),flush=True)
                self_test(core)
            else:
                legacy_self_test(core,abi)
            if cfg.get('lineart') is not None:
                lineart_self_test(cfg,bit)
            if cfg.get('vision') is not None:
                vision_self_test(cfg,bit)
            if cfg.get('audio') is not None:
                # Identity/FIFO only; no codec playback or sound during boot.
                from audio_player.device import AudioPL
                from pynq import MMIO
                audio=AudioPL(MMIO(cfg['audio']['base'],cfg['audio']['size']))
                audio.set_ctrl(enable=False,clear=True,mute=True)
                if audio.depth!=cfg['audio']['fifo_samples']:raise RuntimeError('Audio FIFO size mismatch')
                print('AUDIO_BOOT_IDENTITY_PASS',flush=True)
            body=dict(schema='so101-platform-ready-v1',boot_id=Path(BOOT_ID).read_text().strip(),
                      build_id=cfg['build_id'],manifest_sha256=digest(manifest),artifact_hashes=hashes,
                      ip_name=ip,base=base,size=size,self_test='PASS')
            if abi in (PLANNER_ABI,TCB_ABI,TCB_FP32_ABI):body['accelerator_abi']=abi
            receipt.parent.mkdir(parents=True,exist_ok=True)
            prepare_display_receipt(cfg,receipt.parent,timeout)
            temporary=receipt.with_suffix('.tmp')
            temporary.write_text(json.dumps(body,indent=2)+'\n',encoding='utf-8')
            temporary.chmod(0o600);temporary.replace(receipt)
            print('PLATFORM_READY',cfg['build_id'])


def lineart_self_test(cfg,bit):
    """Test the optional image core before publishing the shared boot receipt."""
    import numpy as np
    from pynq import MMIO,Overlay
    from lineart_backend import LineartPL
    from planner_accel_lease import acquire_planner_lease
    from tcb705.accel_runtime import ps_ddr_allocator
    from stroke_paths import _thin_cpu
    entry=cfg['lineart'];registers=json.loads((bit.parent/entry['registers']).read_text())
    overlay=Overlay(str(bit),download=False);allocate=ps_ddr_allocator(overlay)
    rng=np.random.default_rng(20261020)
    masks=[np.ones((1,1),bool),rng.random((17,65))>.6,np.ones((41,47),bool)]
    for i,mask in enumerate(masks):
        lease=acquire_planner_lease(entry['base'])
        try:device=LineartPL(MMIO(entry['base'],entry['size']),registers,allocate,lease)
        except BaseException:lease.close();raise
        actual,metrics=device.thin(mask)
        np.testing.assert_array_equal(actual,_thin_cpu(mask))
        print('LINEART_BOOT_SELFTEST_PASS',i,metrics,flush=True)


def vision_self_test(cfg,bit):
    """Run all three recogniser modes on small known inputs against the bit-exact model."""
    import numpy as np
    from pynq import MMIO,Overlay
    from brush_vision import contract as c, model as m
    from brush_vision.hardware import VisionPL, validate_manifest_section
    from planner_accel_lease import acquire_planner_lease
    from tcb705.accel_runtime import ps_ddr_allocator
    entry,registers=validate_manifest_section(cfg,bit.parent,bit)
    overlay=Overlay(str(bit),download=False)
    with acquire_planner_lease(entry['base']):
        pl=VisionPL(MMIO(entry['base'],entry['size']),registers,ps_ddr_allocator(overlay))
        try:
            if pl.identity()!=c.RECOG_ID:raise RuntimeError('vision identity mismatch')
            rng=np.random.default_rng(20261024)
            gray=np.full((m.H,m.W),200,np.uint8);gray[100:300,200:260]=30;gray[180:220,120:480]=40
            gray=(gray.astype(int)+rng.integers(-6,7,gray.shape)).clip(0,255).astype(np.uint8)
            roi=(40,600,40,440)
            want,stats=m.preprocess(gray,roi)
            got,words,hw_stats,_=pl.preprocess(m.gray_to_yuyv(gray),roi)
            np.testing.assert_array_equal(got,want)
            if hw_stats['threshold']!=stats['threshold']:raise RuntimeError('vision threshold mismatch')
            hq=m.homography_fixed(np.array([[3.0,0.2,100],[0.1,3.0,60],[0.0002,0.0001,1.0]]))
            rect,rect_words,_,_,_=pl.rectify(words,hq,48)
            np.testing.assert_array_equal(rect,m.rectify(want,hq,48))
            feats=rng.integers(0,40,(8,m.FEATURES)).astype(np.uint8);bitmaps=rng.integers(0,256,(8,512)).astype(np.uint8)
            pl.load_templates(c.pack_templates(feats,bitmaps),8)
            res,_=pl.recognise(rect_words,48,[(0,0,48,48)])
            ref=c.parse_result(c.result_words(m.recognise_box(rect,48,(0,0,48,48),feats,bitmaps)))
            if res[0]['top5']!=ref['top5'] or not np.array_equal(res[0]['features'],ref['features']):
                raise RuntimeError('vision recognise mismatch')
            print('VISION_BOOT_SELFTEST_PASS',hw_stats,flush=True)
        finally:
            for b in list((pl.buffers or {}).values())+[t[0] for t in pl.tpls.values()]:b.freebuffer()


def legacy_self_test(core,abi):
    from scripts.generate_target_vectors import cases
    # Known-vector checks include a nontrivial target, but no serial I/O.
    import itertools
    import numpy as np
    for model,pos,axis,seed,contract,mode,want,golden in itertools.islice(cases(),3):
        result=core.solve_target(model,pos,axis,seed,contract,mode=mode)
        if result.status!='OK' or core.faulted:
            raise RuntimeError('Platform IK self-test failed')
        np.testing.assert_allclose(result.q_solution,golden,atol=.003,rtol=0)
    if abi == PLANNER_ABI:
        # Exercise mode 2 as well as IK before publishing the boot receipt.
        qs=np.asarray([seed,result.q_solution],dtype=np.float64)
        planner_fk_self_test(core,model,qs,contract)



def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--check',action='store_true',help='Validate artifacts only; no hardware I/O')
    p.add_argument('--backend-port',type=int,default=8765)
    a=p.parse_args()
    if not 1024<=a.backend_port<=65535:p.error('Invalid backend port')
    if a.check:
        cfg,*_=validate_manifest(a.manifest,platform.release())
        print('PLATFORM_FILES_PASS',cfg['build_id'])
    else:load(a.manifest,backend_port=a.backend_port)

if __name__=='__main__':main()
