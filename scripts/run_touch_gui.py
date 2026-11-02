"""Launch the on-board MD0700R console without SSH or implicit motion."""
import argparse
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=Path('/home/xilinx/so101_data_work107'))
    p.add_argument('--secrets-file',type=Path,default=Path('/home/xilinx/.config/so101/secrets.local.json'))
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--windowed',action='store_true')
    p.add_argument('--offline',action='store_true')
    p.add_argument('--return-user-gui',action='store_true',help='Show the return button when supervised by the user interface')
    a=p.parse_args()
    if not 1024<=a.port<=65535:p.error('Invalid backend port')
    command=[sys.executable,'-B',str(ROOT/'scripts/arm_studio.py'),'--board-local',
             '--no-tunnel','--target-drawing','--host','127.0.0.1','--data-dir',str(a.data_dir),
             '--cloud-image-dir',str(a.data_dir/'cloud_images'),'--port',str(a.port)]
    if a.secrets_file.is_file():command+=['--secrets-file',str(a.secrets_file)]
    if a.windowed:command+=['--windowed']
    if a.offline:command+=['--offline']
    if a.return_user_gui:command+=['--return-user-gui']
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ[key]='1'
    os.execv(sys.executable,command)

if __name__=='__main__':main()
