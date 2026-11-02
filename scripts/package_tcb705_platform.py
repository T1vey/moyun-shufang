"""Seal a timing-closed seven-axis + LCD + GT911 platform (never programs it)."""
import argparse,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.accel_contract import ABI_FP32,validate_overlay_files,clock_hz
from platform_runtime import digest,validate_manifest
from md0700r_contract import validate_hwh
from scripts.export_tcb_register_map import extract

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--export',type=Path,required=True);ap.add_argument('--header',type=Path,required=True)
    ap.add_argument('--output',type=Path,default=ROOT/'overlay/tcb705');ap.add_argument('--build-id',required=True)
    ap.add_argument('--ge-pl-dtbo',type=Path);ap.add_argument('--lineart-header',type=Path);ap.add_argument('--vision-header',type=Path);ap.add_argument('--audio',action='store_true');a=ap.parse_args()
    # build_fused.tcl writes the stamp only after timing/DRC checks and export.
    if not (a.export/'build_verified.json').is_file():raise ValueError('Missing verified Vivado export stamp')
    report=json.loads((a.export/'build_verified.json').read_text())
    if report['setup_slack_ns']<0 or report['hold_slack_ns']<0 or report['drc_errors']:raise ValueError('Vivado timing/DRC failed')
    if a.audio and not (a.export/'audio_iobuf_verified.txt').is_file():
        raise ValueError('Audio SDA input/tri-state pad buffers have not been verified after routing')
    registers=extract(a.header);abi=registers['abi'];top=registers['top']
    stem='tcb705_planner_fp32' if abi==ABI_FP32 else 'tcb705_planner'
    # Select the artifact family from the generated HLS identity before copying.
    # FP32 and legacy exports deliberately use different names.
    for suffix in ('.bit','.hwh'):
        if not (a.export/(stem+suffix)).is_file():raise ValueError('Missing accelerator artifact: '+stem+suffix)
    a.output.mkdir(parents=True,exist_ok=False)
    for suffix in ('.bit','.hwh'):shutil.copy2(a.export/(stem+suffix),a.output/(stem+suffix))
    (a.output/(stem+'.registers.json')).write_text(json.dumps(registers,indent=2))
    bit=a.output/(stem+'.bit');_,hashes=validate_overlay_files(bit)
    (a.output/(stem+'.artifacts.json')).write_text(json.dumps(dict(abi=abi,files=hashes),indent=2))
    if a.ge_pl_dtbo:
        shutil.copy2(a.ge_pl_dtbo,a.output/'ge_pl.dtbo')
    lineart=None
    if a.lineart_header:
        from scripts.export_lineart_register_map import extract as extract_lineart
        from lineart_contract import validate_hwh as validate_lineart
        name='tcb_lineart.registers.json'
        (a.output/name).write_text(json.dumps(extract_lineart(a.lineart_header),indent=2))
        lineart={**validate_lineart(bit.with_suffix('.hwh')),'registers':name}
    vision=None
    if a.vision_header:
        from brush_vision.hardware import extract_registers,validate_hwh as validate_vision,REGISTERS_NAME
        (a.output/REGISTERS_NAME).write_text(json.dumps(extract_registers(a.vision_header),indent=2))
        vision={**validate_vision(bit.with_suffix('.hwh')),'registers':REGISTERS_NAME}
    cfg=dict(schema='so101-platform-v1',build_id=a.build_id,display='md0700r-1024x600',display_backend='pynq-mmio',
        kernel_release=None,dtbo=None,bitfile=bit.name,ip_name=top+'_0',accelerator_abi=abi,
        accelerator_clock_hz=clock_hz(bit.with_suffix('.hwh')),
        touch_backend='gt911-pl-gpio',display_contract=validate_hwh(bit.with_suffix('.hwh')),
        files={p.name:digest(p) for p in a.output.iterdir() if p.is_file()},board_acceptance='SEE_BOARD_REPORT_AND_BOOT_RECEIPT')
    if a.ge_pl_dtbo:
        from tcb705.ge_pl_contract import validate_hwh as validate_ge_pl
        cfg['ge_pl']=validate_ge_pl(bit.with_suffix('.hwh'))
    if lineart:cfg['lineart']=lineart
    if vision:cfg['vision']=vision
    if a.audio:
        from audio_player.hardware import validate_hwh as validate_audio
        cfg['audio']=validate_audio(bit.with_suffix('.hwh'))
    path=a.output/'platform.json';path.write_text(json.dumps(cfg,indent=2));validate_manifest(path)
    print('TCB705_PLATFORM_SEALED',path)
if __name__=='__main__':main()
