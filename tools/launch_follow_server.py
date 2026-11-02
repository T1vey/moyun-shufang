#!/usr/bin/env python3
"""Launch hand_follow_server.py on PYNQ in background and check status."""
import paramiko, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.2.99', username='xilinx', password='xilinx')

# Kill old
chan = ssh.get_transport().open_session()
chan.exec_command("sudo pkill -f hand_follow_server 2>/dev/null; sleep 1; echo killed")
time.sleep(2)
try: print("Kill:", chan.recv(1024).decode().strip())
except: pass

# Start new
chan2 = ssh.get_transport().open_session()
chan2.exec_command(
    "setsid bash -c 'sudo -E /usr/local/share/pynq-venv/bin/python3 "
    "/home/xilinx/hand_follow_server.py </dev/null "
    ">/home/xilinx/hand_follow.log 2>&1' & echo LAUNCHED"
)
time.sleep(2)
try: print("Launch:", chan2.recv(1024).decode().strip())
except: pass

# Wait for init
time.sleep(8)

# Check log
chan3 = ssh.get_transport().open_session()
chan3.exec_command("cat /home/xilinx/hand_follow.log 2>/dev/null")
time.sleep(2)
log = chan3.recv(8192).decode('utf-8', errors='replace').strip()
print("\n=== Server Log ===")
print(log)

# Check if running
chan4 = ssh.get_transport().open_session()
chan4.exec_command("ps aux | grep hand_follow_server | grep -v grep | wc -l")
time.sleep(2)
count = chan4.recv(1024).decode().strip()
print(f"\nProcess count: {count}")

# Check port
chan5 = ssh.get_transport().open_session()
chan5.exec_command("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8770/status")
time.sleep(2)
code = chan5.recv(1024).decode().strip()
print(f"HTTP status: {code}")

ssh.close()
