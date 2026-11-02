"""Deploy the 墨韵书坊 书画 GUI theme to the TCB705 board (static files only, no motion).

    python deploy/tcb705/ink_gui_20261025/deploy_ink_gui.py            # check, back up, upload
    python deploy/tcb705/ink_gui_20261025/deploy_ink_gui.py --check    # only compare hashes
    python deploy/tcb705/ink_gui_20261025/deploy_ink_gui.py --restore  # put the backup back

Shared files are replaced only when the board copy still equals base/ (the version the
theme was built on); otherwise the script stops so nothing another change made is lost.
The display server reads static files per request: reload the screen page afterwards.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "xilinx@192.168.2.99"
STATIC = "/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm/user_gui/static"
BACKUP = "/home/xilinx/styles_check/ink_gui_backup_20261025.tar"
SHARED = ["desktop.html", "desktop.js", "calligraphy.js", "text-writing.js", "handwriting.js",
          "mobile.html", "handwriting.html", "vision.html", "tcb-debug.html"]
OWNED = ["ink-theme.css", "ink-pages.css", "fonts/brush.ttf", "fonts/wenkai.ttf",
         "fonts/OFL_LXGWWenKai.txt", "fonts/OFL_MaShanZheng.txt"]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST]


def remote(command, data=None):
    return subprocess.run(SSH + [command], input=data, capture_output=True, check=True).stdout.decode()


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def main():
    if "--restore" in sys.argv:
        print(remote(f"cd {STATIC} && tar -xvf {BACKUP} && rm -f ink-theme.css ink-pages.css && rm -rf fonts"))
        return
    board = {}
    for line in remote(f"cd {STATIC} && md5sum {' '.join(SHARED)}").splitlines():
        digest, name = line.split()
        board[name.lstrip("*")] = digest
    blocked = [n for n in SHARED if board.get(n) != md5(HERE / "base" / n)]
    for name in SHARED:
        state = "already new" if board.get(name) == md5(HERE / "new" / name) else (
            "differs from base" if name in blocked else "base, will update")
        print(f"{name:20s} {state}")
    blocked = [n for n in blocked if board.get(n) != md5(HERE / "new" / n)]
    if blocked:
        sys.exit("Board copies changed since the theme was built; merge by hand: " + ", ".join(blocked))
    if "--check" in sys.argv:
        return
    remote(f"mkdir -p /home/xilinx/styles_check && cd {STATIC} && "
           f"[ -f {BACKUP} ] || tar -cf {BACKUP} {' '.join(SHARED)}")
    stage = "/tmp/ink_gui_stage"
    remote(f"rm -rf {stage} && mkdir -p {stage}/fonts")
    for name in SHARED + OWNED:
        remote(f"cat > {stage}/{name}", (HERE / "new" / name).read_bytes())
    check = "\n".join(f"{md5(HERE / 'new' / n)}  {n}" for n in SHARED + OWNED) + "\n"
    remote(f"cd {stage} && md5sum -c --quiet -", check.encode())
    remote(f"mkdir -p {STATIC}/fonts && cd {stage} && for f in {' '.join(SHARED + OWNED)}; do "
           f"cp \"$f\" \"{STATIC}/$f.new\" && mv -f \"{STATIC}/$f.new\" \"{STATIC}/$f\"; done && rm -rf {stage}")
    print(remote(f"cd {STATIC} && md5sum {' '.join(SHARED + OWNED)}"))
    print("Deployed. Backup:", BACKUP, "— reload the screen page (or reboot) to see the new look.")


if __name__ == "__main__":
    main()
