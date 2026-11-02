"""Board deployment transport: SSH scripts and SFTP; no robot motion commands.

Credentials can be overridden with TCB_BOARD_HOST/USER/PASSWORD. The fallback
matches the existing PYNQ helper's factory login. Passwords are sent on stdin,
never put on the remote command line or printed in deployment logs.
"""
import argparse
import os
from pathlib import Path
import shlex
import socket
import sys
import time
import paramiko

def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=('run','upload','download'))
    ap.add_argument('source');ap.add_argument('destination',nargs='?')
    ap.add_argument('--sudo',action='store_true');ap.add_argument('--timeout',type=int,default=900)
    ap.add_argument('--log',type=Path);args=ap.parse_args()
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    host=os.environ.get('TCB_BOARD_HOST','192.168.2.99');user=os.environ.get('TCB_BOARD_USER','xilinx')
    password=os.environ.get('TCB_BOARD_PASSWORD','xilinx')
    ssh=paramiko.SSHClient();ssh.load_system_host_keys();ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    source=os.environ.get('TCB_BOARD_BIND')
    transport=socket.create_connection((host,22),timeout=10,source_address=(source,0)) if source else None
    ssh.connect(host,username=user,password=password,timeout=10,allow_agent=False,look_for_keys=False,sock=transport)
    try:
        if args.action in ('upload','download'):
            if not args.destination:ap.error('destination required')
            with ssh.open_sftp() as sftp:
                if args.action=='upload':sftp.put(args.source,args.destination)
                else:sftp.get(args.source,args.destination)
            print(args.action+': '+args.destination);return 0
        script=Path(args.source).read_text(encoding='utf-8-sig')
        stdin,stdout,stderr=ssh.exec_command('sudo -S -p "" bash -s' if args.sudo else 'bash -s')
        if args.sudo:stdin.write(password+'\n')
        stdin.write(script.replace('\r\n','\n'));stdin.flush();stdin.channel.shutdown_write()
        channel=stdout.channel;started=time.monotonic();chunks=[]
        while True:
            for ready,recv in ((channel.recv_ready,channel.recv),(channel.recv_stderr_ready,channel.recv_stderr)):
                while ready():
                    raw=recv(65536);text=raw.decode('utf-8',errors='replace');chunks.append(text);print(text,end='',flush=True)
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():break
            if time.monotonic()-started>args.timeout:raise TimeoutError('SSH command exceeded time budget; inspect remote process before retrying')
            time.sleep(.1)
        code=channel.recv_exit_status();print('\nREMOTE_EXIT='+str(code))
        if args.log:
            args.log.parent.mkdir(parents=True,exist_ok=True);args.log.write_text(''.join(chunks)+'\nREMOTE_EXIT='+str(code)+'\n',encoding='utf-8')
        return code
    finally:ssh.close()
if __name__=='__main__':raise SystemExit(main())
