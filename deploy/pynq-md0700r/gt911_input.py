"""Read the PL GT911 packet register and deliver local X11 pointer events."""
import argparse
import ctypes as C
import ctypes.util
import json
import mmap
import os
from pathlib import Path
import signal
import struct
import sys
import time


class TouchState:
    def __init__(self):
        self.sequence=None
        self.pressed=False
        self.last_update=0.0
        self.position=(0,0)
        self.packets=0
        self.presses=0
        self.releases=0

    def step(self,packet,now):
        events=[]
        sequence=packet>>22
        valid=bool(packet & (1<<20))
        x=(packet>>10)&1023
        y=packet&1023
        if valid and sequence!=self.sequence and x<1024 and y<600:
            self.sequence=sequence
            self.last_update=now
            self.position=(x,y)
            self.packets+=1
            pressed=bool(packet & (1<<21))
            if pressed:
                events.append(('move',x,y))
            if pressed!=self.pressed:
                events.append(('down' if pressed else 'up',))
                self.presses+=int(pressed)
                self.releases+=int(not pressed)
                self.pressed=pressed
        # Release a held pointer if the touch engine stops reporting.
        if self.pressed and now-self.last_update>0.35:
            events.append(('up',))
            self.pressed=False
            self.releases+=1
        return events


class XPointer:
    def __init__(self,name):
        self.x=C.CDLL(ctypes.util.find_library('X11'))
        self.t=C.CDLL(ctypes.util.find_library('Xtst'))
        self.x.XOpenDisplay.argtypes=[C.c_char_p]
        self.x.XOpenDisplay.restype=C.c_void_p
        self.x.XCloseDisplay.argtypes=[C.c_void_p]
        self.x.XFlush.argtypes=[C.c_void_p]
        self.t.XTestFakeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong]
        self.t.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
        self.d=self.x.XOpenDisplay(name.encode())
        if not self.d: raise RuntimeError('Cannot connect to local display '+name)

    def send(self,events):
        for event in events:
            if event[0]=='move': self.t.XTestFakeMotionEvent(self.d,-1,event[1],event[2],0)
            else: self.t.XTestFakeButtonEvent(self.d,1,int(event[0]=='down'),0)
        if events: self.x.XFlush(self.d)

    def close(self):
        self.send([('up',)])
        self.x.XCloseDisplay(self.d)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--display',default=':9')
    parser.add_argument('--status',type=Path,default=Path('/run/so101-lcd/touch.json'))
    parser.add_argument('--bit-sha256')
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--platform-manifest',type=Path)
    args=parser.parse_args()
    identity=None;address=0x41220000;packet_offset=8
    if args.platform_manifest:
        if not args.runtime:parser.error('--platform-manifest requires --runtime')
        sys.path.insert(0,str(args.runtime.resolve()))
        from md0700r_runtime import resolve_display,display_ready
        identity=resolve_display(args.runtime,args.platform_manifest)
        address=identity['contract']['ips']['reset_touch']['base']
        packet_offset=identity['contract']['touch_packet_offset']
        if args.bit_sha256 and args.bit_sha256!=identity['bit_sha256']:
            parser.error('--bit-sha256 differs from the sealed platform')
    elif not args.bit_sha256:parser.error('--platform-manifest or --bit-sha256 is required')
    running=True
    def stop(*unused):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    deadline=time.monotonic()+130
    while running:
        try:
            display=json.loads(Path('/run/so101-lcd/status.json').read_text())
            if (display_ready(display,identity) if identity is not None
                    else display['status']=='RUNNING' and display['bit_sha256']==args.bit_sha256):break
        except (OSError,ValueError,KeyError): pass
        if time.monotonic()>deadline: raise RuntimeError('Matching display hardware is not ready')
        time.sleep(.5)
    if not running:return
    state=TouchState()
    pointer=XPointer(args.display)
    fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
    registers=mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=address)
    saved=0.0
    try:
        print('GT911_INPUT_READY',flush=True)
        while running:
            now=time.monotonic()
            packet=struct.unpack_from('<I',registers,packet_offset)[0]
            pointer.send(state.step(packet,now))
            if now-saved>0.5:
                value=dict(status='RUNNING',packet=hex(packet),packets=state.packets,
                           presses=state.presses,releases=state.releases,pressed=state.pressed,
                           x=state.position[0],y=state.position[1],sequence=state.sequence)
                temp=args.status.with_suffix('.tmp')
                temp.write_text(json.dumps(value)+'\n')
                temp.replace(args.status)
                saved=now
            time.sleep(.01)
    finally:
        pointer.close()
        registers.close()
        os.close(fd)
        args.status.unlink(missing_ok=True)


if __name__=='__main__': main()
