"""One-time import of the user-supplied model and ARM32 SDK; never fetch secrets."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
MATERIALS=ROOT.parent
def main():
    urdf=MATERIALS/'02_天链官方开源包/tl_robot_ros2-master'
    dst=ROOT/'robots/tcb705/model_source';dst.mkdir(parents=True,exist_ok=True)
    shutil.copy2(urdf/'src/tl_description/urdf/tcb705.urdf',dst/'tcb705.urdf')
    shutil.copy2(urdf/'LICENSE',dst/'LICENSE')
    sdk=MATERIALS/'05_华成XSDK资料_2026-10-16/xsdk-update-main/SDK/V2.4.1(require host version at least 1.9.82 )'
    vendor=ROOT/'vendor/huacheng';(vendor/'include').mkdir(parents=True,exist_ok=True);(vendor/'armhf').mkdir(exist_ok=True)
    for file in sdk.glob('*.h'):shutil.copy2(file,vendor/'include'/file.name)
    shutil.copy2(MATERIALS/'libxoip.so',vendor/'armhf/libxoip.so')
    files=[dst/'tcb705.urdf',dst/'LICENSE']+list((vendor/'include').glob('*.h'))+[vendor/'armhf/libxoip.so']
    manifest=dict(source_project=r'D:\zhiliao\work107\SO101_FPGA_ArmSystem-105\SO101_FPGA_ArmSystem',
        sdk_version='V2.4.1',host_minimum='1.9.82',sdk_redistribution='Vendor binary; original license/authorization applies.',
        imported={str(f.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in files})
    (ROOT/'TCB705_SOURCES.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':main()
