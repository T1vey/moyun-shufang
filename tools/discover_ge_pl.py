"""Read-only L2 discovery on GE_PL; no IP assignment or robot commands."""
import argparse
import ipaddress
import json
from pathlib import Path
import select
import socket
import struct
import time


def discover(iface, subnets, seconds):
    mac=bytes.fromhex(Path('/sys/class/net',iface,'address').read_text().strip().replace(':',''))
    seen={};observed=set();ipv4=set()
    with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)) as sock:
        sock.bind((iface,0));sock.setblocking(False)
        def receive():
            for _ in range(1000):
                try:raw=sock.recv(8192)
                except BlockingIOError:return
                if len(raw)<34 or raw[6:12]==mac:continue
                if raw[12:14]==b'\x08\x00':
                    ipv4.add((socket.inet_ntoa(raw[26:30]),socket.inet_ntoa(raw[30:34])))
                if len(raw)<42 or raw[12:14]!=b'\x08\x06':continue
                hw,proto,hl,pl,op=struct.unpack('!HHBBH',raw[14:22])
                if (hw,proto,hl,pl)!=(1,0x800,6,4):continue
                smac=':'.join('%02x'%v for v in raw[22:28])
                sip=socket.inet_ntoa(raw[28:32]);tip=socket.inet_ntoa(raw[38:42])
                observed.add((sip,smac,op,tip))
                if op==2:seen[sip]=smac
        for subnet in subnets:
            net=ipaddress.ip_network(subnet)
            if net.version!=4 or net.num_addresses>256:raise ValueError('Use an IPv4 /24 or smaller')
            for dst in net.hosts():
                # RFC 5227 probe: source 0.0.0.0 does not claim any new address.
                raw=b'\xff'*6+mac+b'\x08\x06'+struct.pack('!HHBBH',1,0x800,6,4,1)+mac+b'\x00'*4+b'\x00'*6+socket.inet_aton(str(dst))
                sock.send(raw);time.sleep(.006);receive()
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            select.select([sock],[],[],.2);receive()
    return dict(interface=iface,subnets=subnets,arp_replies=seen,
                arp_observations=[dict(source_ip=a,source_mac=b,operation=c,target_ip=d) for a,b,c,d in sorted(observed)],
                ipv4_observations=[dict(source_ip=a,destination_ip=b) for a,b in sorted(ipv4)])


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--interface',required=True)
    ap.add_argument('--subnet',action='append',default=[]);ap.add_argument('--seconds',type=float,default=10)
    ap.add_argument('--output',type=Path);a=ap.parse_args()
    report=discover(a.interface,a.subnet or ['192.168.4.0/24','192.168.2.0/24'],a.seconds)
    data=json.dumps(report,indent=2);print(data)
    if a.output:a.output.write_text(data+'\n')
