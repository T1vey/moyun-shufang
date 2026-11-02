"""PYNQ userspace display bridge for the verified MD0700R r4 bitstream.

The platform loader owns FPGA loading. This process only attaches after its
sealed boot receipt and backend identity pass. No display DTBO is required.
Register definitions: supplied Xilinx Frame Buffer/VTC and Digilent PWM sources.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
import urllib.request
import numpy as np
from pynq import Overlay, MMIO, allocate

running=True
def stop(*unused):
    global running
    running=False

def panel_pixels(xvfb_pixels):
    # XWD uses little-endian B,G,R,X bytes. The complete installed LCD
    # pipeline needs R,G,B byte order at its DMA input: passing B,G,R
    # directly exchanges red and blue on the physical MD0700R panel.
    # Keep the sealed framebuffer format register unchanged (29).
    return xvfb_pixels[:, :, 2::-1]

def pixel_copier():
    """Pack XWD BGRA directly into the existing RGB DMA buffer (no allocation)."""
    try:
        import cv2
        # One display worker must leave CPU time for touch, WebKit and planning.
        cv2.setNumThreads(1)
        def copy(src,dst):cv2.cvtColor(src,cv2.COLOR_BGRA2RGB,dst=dst)
        return copy,'opencv'
    except ImportError:
        def copy(src,dst):
            for channel in range(3):dst[:,:,channel]=src[:,:,2-channel]
        return copy,'numpy_channels'

def frame_delay(started,now,refresh_hz):
    # Rendering consumes the frame budget. Never queue catch-up frames.
    return max(0.,1./refresh_hz-(now-started))

class LCD:
    def __init__(self):
        self.buffer=None
        self.pwm=None
        self.reset=None

    def start(self,identity):
        self.identity=identity
        contract=identity['contract'];ips=contract['ips'];window=contract['register_window_bytes']
        ov=Overlay(identity['bitfile'],download=False)
        clock=MMIO(ips['clock']['base'],window)
        assert clock.read(4)&1,'Pixel clock unlocked'
        gpio=MMIO(ips['lcd_id']['base'],window)
        gpio.write(4,7)
        time.sleep(.01)
        assert gpio.read(0)&7==2,'Unexpected LCD ID'
        gpio.write(4,0)
        self.pwm=MMIO(ips['pwm']['base'],window)
        self.pwm.write(0,0)
        self.reset=MMIO(ips['reset_touch']['base'],window)
        reset_value=self.reset.read(0)
        self.reset.write(0,reset_value&~1)
        time.sleep(.1)
        self.reset.write(0,reset_value|1)
        time.sleep(.1)
        self.frame=MMIO(ips['framebuffer']['base'],window)
        self.vtc=MMIO(ips['vtc']['base'],window)
        self.pwm=MMIO(ips['pwm']['base'],window)
        self.pwm.write(0,0)
        memories=[v for v in ov.mem_dict.values() if v.get('base_address')==0]
        assert len(memories)==1,ov.mem_dict
        target=ov.device.get_memory(memories[0])
        self.buffer=allocate(shape=(600,1024,3),dtype=np.uint8,target=target)
        assert self.buffer.physical_address+self.buffer.nbytes<=0x40000000
        self.buffer[:]=0
        self.buffer.flush()
        self.vtc.write(0,0x80000000)
        time.sleep(.01)
        for offset,value in [(0x60,1024|(600<<16)),(0x68,0),(0x6c,0x30),
                             (0x70,1344),(0x74,635|(635<<16)),
                             (0x78,1184|(1204<<16)),(0x7c,1024|(1024<<16)),
                             (0x80,612|(615<<16)),(0x84,1184|(1184<<16))]:
            self.vtc.write(offset,value)
        self.vtc.write(0,0x03f7ef07)
        self.frame.write(4,0);self.frame.write(8,0)
        for offset,value in [(0x10,1024),(0x18,600),(0x20,3072),(0x28,29),
                             (0x30,self.buffer.physical_address),(0x34,0)]:
            self.frame.write(offset,value)
        self.frame.write(0,0x81)
        if not self.verify_frames():
            raise RuntimeError('LCD stream did not complete frames after initialization')
        self.pwm.write(8,500000);self.pwm.write(0x40,250000);self.pwm.write(0,1)

    def verify_frames(self):
        # ISR latches actual ap_done even while AP_CTRL hides it in auto-restart.
        # GIE remains zero: this does not send an interrupt to the CPU.
        completed=0
        self.frame.write(8,1)
        try:
            if self.frame.read(12)&1:self.frame.write(12,1)
            for _ in range(10):
                time.sleep(.04)
                if self.frame.read(12)&1:
                    completed+=1
                    self.frame.write(12,1)
                if completed>=2:return True
            return False
        finally:self.frame.write(8,0)

    def close(self):
        if self.pwm is not None:
            try:self.pwm.write(0,0)
            except Exception:pass  # Still drain DMA if backlight MMIO failed.
        if getattr(self,'frame',None) is not None:
            deadline=time.monotonic()+2;reported=False
            while True:
                try:
                    self.frame.write(0,0)
                    if self.frame.read(0)&4:break
                except Exception:pass  # A failed MMIO read is not proof of idle.
                if not reported and time.monotonic()>=deadline:
                    print('LCD frame drain timed out; retaining buffer until DMA is idle',flush=True)
                    reported=True
                time.sleep(.1 if reported else .01)
        if self.reset is not None:
            self.reset.write(0,self.reset.read(0)&~1)
            time.sleep(.1)
        # Never release a frame buffer while the bus master can still read it.
        # The service has no stop timeout: a hardware fault needs maintenance.
        if self.buffer is not None:
            self.buffer.freebuffer();self.buffer=None

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--platform-manifest',type=Path)
    p.add_argument('--gui-user',default='xilinx')
    p.add_argument('--data-dir',type=Path,default=Path('/home/xilinx/so101_data_work107'))
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--refresh-hz',type=float,default=30.,help='Software display update rate, 10..60 Hz')
    p.add_argument('--classic-gui',action='store_true',help='Use the original Tk settings console')
    p.add_argument('--user-ui-port',type=int,help='Display an independently running local web UI; retain existing PL health checks')
    a=p.parse_args()
    if not 10<=a.refresh_hz<=60:p.error('Display refresh must be 10..60 Hz')
    if not 1024<=a.port<=65535:p.error('Invalid backend port')
    if a.user_ui_port is not None and not 1024<=a.user_ui_port<=65535:p.error('Invalid UI port')
    sys.path.insert(0,str(a.runtime.resolve()))
    from md0700r_runtime import resolve_display,validate_health
    identity=resolve_display(a.runtime,a.platform_manifest)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+100
    while running:
        try:
            with opener.open('http://127.0.0.1:'+str(a.port)+'/api/status',timeout=5) as response:state=json.load(response)
            validate_health(state,identity)
            break
        except (OSError,ValueError,AssertionError,KeyError):
            if time.monotonic()>deadline:raise
            time.sleep(1)
    if not running:return
    folder=Path('/run/so101-lcd')
    folder.mkdir(exist_ok=True)
    children=[];lcd=None
    try:
        xlog=(folder/'xvfb.log').open('w')
        xvfb=subprocess.Popen(['Xvfb',':9','-screen','0','1024x600x24','-nolisten','tcp','-ac','-fbdir',str(folder)],stdout=xlog,stderr=subprocess.STDOUT)
        children.append(xvfb)
        path=folder/'Xvfb_screen0'
        for _ in range(100):
            if path.exists() and path.stat().st_size>1024*600*4:break
            if xvfb.poll() is not None:raise RuntimeError('Xvfb failed; see '+str(folder/'xvfb.log'))
            time.sleep(.1)
        raw=path.open('rb')
        header=struct.unpack('>25I',raw.read(100))
        assert header[1]==7 and header[4:6]==(1024,600) and header[11]==32,header
        assert header[7]==0 and header[14:17]==(0xff0000,0xff00,0xff),header
        offset=header[0]+header[19]*12
        pixels=np.memmap(path,dtype=np.uint8,mode='r',offset=offset,shape=(600,header[12]))
        view=pixels[:,:4096].reshape(600,1024,4)
        glog=(folder/'gui.log').open('w')
        gui_entry='run_touch_gui.py' if a.classic_gui or os.environ.get('SO101_GUI_MODE')=='classic' else 'run_user_gui.py'
        gui_command=([ '/usr/bin/python3','-B',str(a.runtime/'scripts/user_gui_kiosk.py'),
            '--port',str(a.user_ui_port)] if a.user_ui_port else
            [str(a.runtime/'.venv/bin/python'),'-B',str(a.runtime/'scripts'/gui_entry),
             '--windowed','--data-dir',str(a.data_dir),'--port',str(a.port)])
        gui=subprocess.Popen(['runuser','-u',a.gui_user,'--','env','DISPLAY=:9']+gui_command,
            cwd=a.runtime,stdout=glog,stderr=subprocess.STDOUT)
        children.append(gui)
        # Publish ownership before starting DMA, so partial initialization also
        # reaches close() through the outer finally block.
        lcd=LCD();lcd.start(identity)
        copy_pixels,copy_backend=pixel_copier()
        started=time.monotonic();saved=False;count=0;published=None
        last_frame=None;window_count=0;window_started=started;copy_total=0.;max_interval=0.
        print('MD0700R_GUI_DISPLAY_RUNNING',flush=True)
        while running and (not a.seconds or time.monotonic()-started<a.seconds):
            frame_started=time.monotonic()
            if last_frame is not None:max_interval=max(max_interval,frame_started-last_frame)
            last_frame=frame_started
            if any(child.poll() is not None for child in children):raise RuntimeError('Desktop process exited; inspect /run/so101-lcd/*.log')
            copy_pixels(view,lcd.buffer)
            lcd.buffer.flush()
            count+=1;window_count+=1;copy_total+=time.monotonic()-frame_started
            now=time.monotonic()
            if published is None or now-published>=2:
                body=dict(status='RUNNING',width=1024,height=600,frames=count,
                          hardware_frames_verified=True,bit_sha256=identity['bit_sha256'],
                          manifest_sha256=identity['manifest_sha256'],build_id=identity['build_id'],
                          refresh_hz=a.refresh_hz,copy_backend=copy_backend,
                          observed_fps=round(window_count/max(now-window_started,.001),2) if published is not None else None,
                          copy_flush_mean_ms=round(copy_total/window_count*1000,2),
                          max_frame_interval_ms=round(max_interval*1000,2),updated_unix=time.time())
                temporary=folder/'status.tmp';temporary.write_text(json.dumps(body)+'\n')
                temporary.replace(folder/'status.json');published=now
                window_count=0;window_started=now;copy_total=0.;max_interval=0.
            if not saved and time.monotonic()-started>15:
                from PIL import Image
                Image.fromarray(np.array(view[:,:,2::-1])).save(str(folder/'gui-screen.png'))
                saved=True
            time.sleep(frame_delay(frame_started,time.monotonic(),a.refresh_hz))
    finally:
        if lcd is not None:lcd.close()
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                # The user desktop supervisor also closes WebKit's renderer
                # and the upload service; let it reap those children first.
                try:child.wait(timeout=12 if child is gui else 5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        (folder/'status.json').unlink(missing_ok=True)

if __name__=='__main__':main()
