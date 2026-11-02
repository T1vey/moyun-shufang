#!/usr/bin/env python3
"""Explicitly restart the managed workbench service over SSH."""
import argparse
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board-ip', required=True)
    p.add_argument('--user', default='xilinx')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9.-]+', a.board_ip) or not re.fullmatch(r'[A-Za-z0-9_-]+', a.user):
        p.error('Invalid host/user')
    subprocess.run(['ssh', '-t', a.user + '@' + a.board_ip,
                    'sudo systemctl restart so101-workbench.service && sudo systemctl --no-pager status so101-workbench.service'], check=True)


if __name__ == '__main__':
    main()
