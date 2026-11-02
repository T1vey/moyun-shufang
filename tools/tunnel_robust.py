#!/usr/bin/env python3
"""Robust SSH tunnel: local 8765 -> PYNQ 127.0.0.1:8765 via paramiko."""
import paramiko
import socket
import select
import threading
import sys
import time

BOARD_IP = "192.168.2.99"
USERNAME = "xilinx"
PASSWORD = "xilinx"
LOCAL_PORT = 8765
REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 8765

def handle_client(client, transport):
    try:
        chan = transport.open_channel(
            'direct-tcpip',
            (REMOTE_HOST, REMOTE_PORT),
            client.getpeername())
    except Exception as e:
        print(f"Channel open failed: {e}", flush=True)
        if not isinstance(e, paramiko.ChannelException):
            transport.close()
        client.close()
        return
    if chan is None:
        client.close()
        return
    try:
        while True:
            r, w, x = select.select([client, chan], [], [], 60)
            if not r:
                break
            if client in r:
                data = client.recv(8192)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(8192)
                if not data:
                    break
                client.sendall(data)
    except Exception as e:
        pass
    finally:
        chan.close()
        client.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', LOCAL_PORT))
    server.listen(5)
    server.settimeout(1)
    print(f"Listening on 127.0.0.1:{LOCAL_PORT} — open http://127.0.0.1:{LOCAL_PORT}/", flush=True)
    ssh, transport = None, None
    while True:
        try:
            if transport is None or not transport.is_active():
                if ssh is not None:
                    ssh.close()
                ssh = paramiko.SSHClient()
                ssh.load_system_host_keys()
                ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
                print(f"Connecting to {BOARD_IP}...", flush=True)
                try:
                    ssh.connect(BOARD_IP, username=USERNAME, password=PASSWORD,
                                timeout=8, banner_timeout=8, auth_timeout=8,
                                allow_agent=False, look_for_keys=False)
                    transport = ssh.get_transport()
                    transport.set_keepalive(10)
                    print("SSH tunnel connected", flush=True)
                except (OSError, paramiko.SSHException) as e:
                    print("SSH reconnect pending: " + type(e).__name__, flush=True)
                    ssh.close()
                    transport = None
                    time.sleep(3)
                    continue
            client, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(client, transport), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Accept error: {e}", flush=True)

if __name__ == '__main__':
    main()
