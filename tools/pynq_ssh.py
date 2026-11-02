"""SSH helper for PYNQ board - xilinx/xilinx"""
import paramiko
import sys
import io
import os
import warnings
warnings.filterwarnings("ignore")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

HOST = "192.168.2.99"
USER = "xilinx"
PWD = "xilinx"

def run_ssh(cmd):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PWD, timeout=10,
                       allow_agent=False, look_for_keys=False)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        exit_code = stdout.channel.recv_exit_status()
        if out:
            print(out, end='')
        if err:
            print(f"[stderr] {err}", end='', file=sys.stderr)
        print(f"[exit code: {exit_code}]")
        return exit_code
    except Exception as e:
        print(f"SSH error: {e}", file=sys.stderr)
        return -1
    finally:
        client.close()

def upload_file(local_path, remote_path):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PWD, timeout=10,
                       allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        print(f"✅ Uploaded: {local_path} -> {remote_path}")
        return True
    except Exception as e:
        print(f"❌ Upload error: {e}", file=sys.stderr)
        return False
    finally:
        client.close()

def upload_directory(local_dir, remote_dir):
    """递归上传整个目录到远程"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PWD, timeout=10,
                       allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()

        # 确保远程根目录存在
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            run_ssh(f"mkdir -p {remote_dir}")
            sftp = client.open_sftp()

        uploaded = 0
        for root, dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir).replace("\\", "/")
            remote_root = remote_dir if rel == "." else f"{remote_dir}/{rel}"

            # 创建子目录
            for d in dirs:
                rd = f"{remote_root}/{d}"
                try:
                    sftp.mkdir(rd)
                except Exception:
                    pass

            # 上传文件
            for f in files:
                local_path = os.path.join(root, f)
                remote_path = f"{remote_root}/{f}"
                try:
                    sftp.put(local_path, remote_path)
                    uploaded += 1
                    print(f"  ✅ {remote_path}")
                except Exception as e:
                    print(f"  ❌ {remote_path}: {e}")

        sftp.close()
        print(f"✅ Uploaded {uploaded} files: {local_dir} -> {remote_dir}")
        return True
    except Exception as e:
        print(f"❌ Upload dir error: {e}", file=sys.stderr)
        return False
    finally:
        client.close()

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "upload":
        upload_file(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "upload_dir":
        upload_directory(sys.argv[2], sys.argv[3])
    else:
        cmd = sys.argv[1] if len(sys.argv) > 1 else "hostname"
        run_ssh(cmd)
