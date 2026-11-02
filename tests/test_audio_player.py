"""Offline audio regressions: no PYNQ mapping, no controller or robot motion."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from audio_player import contract as c, codec
from audio_player.device import AudioPL, open_device
from audio_player.player import Player
from audio_player.service import AudioService


def wait(predicate, timeout=2):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('background operation timed out')


class FakeMMIO:
    def __init__(self):
        self.regs={c.ID:c.IDENTITY,c.VER:c.VERSION,c.DEPTH:16384,c.FRAMES:0xfffffff0,c.CAPS:3,c.I2C_DONE:0}
        self.array=np.zeros(c.SIZE//4,np.uint32)
        self.writes=[];self.busy=False;self.nack=False;self.sda=True;self.ack_addresses={0x1a};self.complete=True
    def read(self, addr):
        if addr==c.STATUS:
            return self.regs.get(addr,0) | (c.STATUS_I2C_BUSY if self.busy else 0) | (c.STATUS_I2C_NACK if self.nack else 0) | (c.STATUS_SDA if self.sda else 0)
        return self.regs.get(addr,0)
    def write(self, addr, val):
        self.writes.append((addr,val))
        if addr==c.I2C and self.complete:
            self.regs[c.I2C_DONE]=(self.regs[c.I2C_DONE]+1)&0xffffffff
            self.nack=(val&0x7f) not in self.ack_addresses
        if addr==c.CTRL and val&c.CTRL_CLEAR:self.regs[c.STATUS]=0


class DeviceTests(unittest.TestCase):
    def test_encoded_i2c_word_and_limits(self):
        self.assertEqual(c.i2c_word(0x1a,0x1f9),0xf9351a)
        for args in [(-1,0),(0x38,0),(0,-1),(0,512)]:
            with self.assertRaises(ValueError):c.i2c_word(*args)
    def test_pll_frequency_and_gain(self):
        n,k=codec.pll();self.assertEqual(n,7)
        hz=codec.MCLK_HZ*(n+k/2**24)/8
        self.assertAlmostEqual(hz,12288000,delta=1)
        for v in range(101):
            for reg,value in codec.output_volume(v,v):
                self.assertLessEqual(value&0x7f,0x79)
        regs=dict(x for x in codec.init_sequence() if x[0]!='wait')
        packed_k=(regs[codec.R_PLL_K1]<<16)|(regs[codec.R_PLL_K2]<<8)|regs[codec.R_PLL_K3]
        self.assertEqual(packed_k,k)  # top two K bits must survive actual register packing
        self.assertAlmostEqual(codec.MCLK_HZ*(n+packed_k/2**24)/8,12288000,delta=1)
        self.assertEqual(regs[codec.R_IFACE1],0x42)
        self.assertEqual(regs[codec.R_CLK2]&15,7)
        self.assertEqual(regs[codec.R_ADDCTL2],4)  # board L20 is ADCLRC, not DACLRC
    def test_bad_identity_refuses_writes(self):
        m=FakeMMIO();m.regs[c.ID]=0
        with self.assertRaises(RuntimeError):AudioPL(m)
        self.assertEqual(m.writes,[])
    def test_missing_platform_never_imports_pynq_or_maps_axi(self):
        with patch('audio_player.hardware.attached_audio',side_effect=ValueError('no audio')):
            with self.assertRaisesRegex(ValueError,'no audio'):open_device()
    def test_worker_attach_installs_event_loop_before_pynq_clock_mapping(self):
        import asyncio
        from types import SimpleNamespace
        result={}
        def verify(*args):result['loop']=asyncio.get_event_loop()
        def worker():
            with patch('audio_player.hardware.attached_audio',return_value={'base':c.BASE,'size':c.SIZE}), \
                 patch('tcb705.accel_runtime.attached_identity',return_value=({'accelerator_clock_hz':100000000,'accelerator_abi':'tcb705-planner-fp32-v2'},None,None,None,None)), \
                 patch('tcb705.accel_runtime.verify_planner_clock',side_effect=verify), \
                 patch.dict('sys.modules',{'pynq':SimpleNamespace(MMIO=lambda *args:FakeMMIO())}):
                try:result['device']=open_device()
                except Exception as exc:result['error']=str(exc)
        t=threading.Thread(target=worker);t.start();t.join(2)
        self.assertFalse(t.is_alive());self.assertNotIn('error',result)
        self.assertFalse(result['loop'].is_closed());self.assertEqual(result['device'].depth,16384)

    def test_i2c_nack_busy_timeout(self):
        m=FakeMMIO();d=AudioPL(m);m.ack_addresses=set()
        with self.assertRaisesRegex(RuntimeError,'acknowledge'):d.write_reg(2,0)
        m.ack_addresses={0x1a};m.nack=False;m.busy=True
        with self.assertRaises(TimeoutError):d.write_reg(2,0,timeout=.001)
    def test_old_fpga_refused_before_any_write(self):
        m=FakeMMIO();m.regs[c.CAPS]=0
        with self.assertRaisesRegex(RuntimeError,'IOBUF'):AudioPL(m)
        self.assertEqual(m.writes,[])
    def test_sda_low_is_not_misreported_as_ack(self):
        m=FakeMMIO();d=AudioPL(m);m.sda=False
        with self.assertRaisesRegex(RuntimeError,'held low'):d.write_reg(2,0)
        self.assertEqual(m.writes,[])
    def test_codec_probe_is_address_only_and_selects_es8388(self):
        m=FakeMMIO();d=AudioPL(m);m.ack_addresses={0x10}
        d.probe_codec()
        self.assertEqual(d.codec_probe,{'0x22':False,'0x10':True,'0x11':False,'0x1a':False})
        self.assertTrue(all(a==c.I2C and word&c.I2C_PROBE for a,word in m.writes))
        self.assertEqual(d.codec_name,'ES8388');self.assertEqual(d.sample_rate,48828.125)
        d.write_reg(0x19,0x26);self.assertEqual(m.writes[-1],(c.I2C,0x261910))
    def test_ambiguous_codec_addresses_are_rejected(self):
        m=FakeMMIO();d=AudioPL(m);m.ack_addresses={0x10,0x1a}
        with self.assertRaisesRegex(RuntimeError,'Multiple audio'):d.probe_codec()
    def test_negative_control_ack_rejected(self):
        m=FakeMMIO();d=AudioPL(m);m.ack_addresses={0x22,0x1a}
        with self.assertRaisesRegex(RuntimeError,'negative-control'):d.probe_codec()
    def test_command_must_complete_even_when_busy_never_seen(self):
        m=FakeMMIO();d=AudioPL(m);m.complete=False
        with self.assertRaisesRegex(TimeoutError,'did not complete'):d.write_reg(2,0,timeout=.001)
    def test_transaction_counter_wrap(self):
        m=FakeMMIO();m.regs[c.I2C_DONE]=0xffffffff;d=AudioPL(m);d.write_reg(2,0)
        self.assertEqual(m.regs[c.I2C_DONE],0)

    def test_signed_sample_packing_and_free_space(self):
        m=FakeMMIO();d=AudioPL(m)
        self.assertEqual(d.push(np.array([-32768,32767,-1,0,7],np.int16)),4)
        self.assertEqual(int(m.array[c.FIFO_WINDOW//4]),0x7fff8000)
        self.assertEqual(int(m.array[c.FIFO_WINDOW//4+1]),0x0000ffff)
        m.regs[c.STATUS]=16383;self.assertEqual(d.push(np.ones(4,np.int16)),0)
    def test_frame_counter_wrap(self):
        m=FakeMMIO();now=[0.0]
        def sleep(s):
            now[0]+=s;m.regs[c.FRAMES]=(m.regs[c.FRAMES]+int(s*48000))&0xffffffff
        d=AudioPL(m,sleep=sleep,clock=lambda:now[0]);d.init_codec(0,0)
        self.assertEqual(d.init_frame_hz,48000)
    def test_wrong_physical_frame_rate_is_rejected(self):
        m=FakeMMIO();now=[0.0]
        def sleep(s):
            now[0]+=s;m.regs[c.FRAMES]=(m.regs[c.FRAMES]+int(s*43422))&0xffffffff
        with self.assertRaisesRegex(RuntimeError,'frame rate'):
            AudioPL(m,sleep=sleep,clock=lambda:now[0]).init_codec(0,0)
    def _codec_clock(self, m, rate, startup_gap_s=0.0, read_delay_s=0.0):
        """Fake time: LRCK starts startup_gap_s after the first sleep; FRAMES reads may be slow."""
        now=[0.0];gap=[startup_gap_s];read=m.read
        def sleep(s):
            now[0]+=s;run=max(0.0,s-gap[0]);gap[0]=max(0.0,gap[0]-s)
            m.regs[c.FRAMES]=(m.regs[c.FRAMES]+int(run*rate))&0xffffffff
        def slow_read(addr):
            if addr==c.FRAMES:now[0]+=read_delay_s
            return read(addr)
        m.read=slow_read
        return dict(sleep=sleep,clock=lambda:now[0])
    def test_codec_startup_gap_is_not_a_rate_error(self):
        # Board 2026-10-27: 50 ms right after init read 35-40 kHz, long windows 48.8 kHz.
        m=FakeMMIO();m.ack_addresses={0x10}
        d=AudioPL(m,**self._codec_clock(m,48828.125,startup_gap_s=0.2));d.init_codec(0,0)
        self.assertAlmostEqual(d.init_frame_hz,48828.125,delta=10)
        self.assertEqual(len(d.frame_windows),3)
    def test_wrong_es8388_rate_still_rejected_after_settling(self):
        m=FakeMMIO();m.ack_addresses={0x10}
        with self.assertRaisesRegex(RuntimeError,'frame rate'):
            AudioPL(m,**self._codec_clock(m,34769.2)).init_codec(0,0)
    def test_slow_counter_reads_are_bounded_not_failed(self):
        m=FakeMMIO();m.ack_addresses={0x10}
        d=AudioPL(m,**self._codec_clock(m,48828.125,read_delay_s=0.02));d.init_codec(0,0)
        self.assertTrue(all(w['low_hz']<=48828.125<=w['high_hz']*1.005 for w in d.frame_windows))
    def test_clear_timeout_detected(self):
        m=FakeMMIO();d=AudioPL(m)
        m.write=lambda *a:None;m.regs[c.STATUS]=12
        with self.assertRaises(TimeoutError):d.set_ctrl(clear=True)


class FakeDevice:
    depth=16384
    def __init__(self):
        self.enabled=False;self.samples=[];self.played=[];self.last=time.monotonic();self.calls=[]
    def init_codec(self,**kw):self.calls.append(('init',kw))
    def set_volume(self,*args):self.calls.append(('volume',args))
    def level(self):
        now=time.monotonic();n=min(len(self.samples),int((now-self.last)*48000)) if self.enabled else 0
        if n:self.played.extend(self.samples[:n]);del self.samples[:n]
        self.last=now
        return len(self.samples)
    def set_ctrl(self,enable=None,clear=False,mute=None):
        self.level()
        if enable is not None:self.enabled=enable
        if clear:self.samples=[]
        self.calls.append(('ctrl',enable,clear))
    def push(self,samples):
        n=min(len(samples),self.depth-self.level())&~1
        self.samples.extend(np.asarray(samples[:n],np.int16).tolist())
        self.calls.append(('push',n));return n


class PlayerTests(unittest.TestCase):
    def test_odd_length_finishes_and_prefills_before_enable(self):
        d=FakeDevice();p=Player(d)
        p.play({'id':'test','timeline':[]},np.arange(5,dtype=np.int16))
        wait(lambda:p.finished);p.stop()
        self.assertEqual(d.played,[0,1,2,3,4,0])
        self.assertLess(next(i for i,x in enumerate(d.calls) if x[0]=='push'),
                        next(i for i,x in enumerate(d.calls) if x[:2]==('ctrl',True)))
    def test_pause_disables_fifo_resume_and_stop(self):
        d=FakeDevice();p=Player(d)
        p.play({'id':'test','timeline':[dict(start=0,end=2,text='句')]},np.arange(96000,dtype=np.int16))
        wait(lambda:len(d.played)>200);p.pause();pos=p.position_s()
        self.assertFalse(d.enabled);time.sleep(.08)
        self.assertEqual(p.position_s(),pos);self.assertTrue(p.status()['paused'])
        p.resume();wait(lambda:p.position_s()>pos);p.stop()
        self.assertFalse(d.enabled);self.assertFalse(p.status()['playing'])
    def test_new_play_waits_for_old_worker_exit(self):
        d=FakeDevice();p=Player(d)
        p.play({'id':'old'},np.zeros(96000,np.int16));old=p.thread
        p.play({'id':'new'},np.ones(100,np.int16))
        self.assertFalse(old.is_alive());wait(lambda:p.finished);p.stop()
    def test_empty_recording_does_not_hang(self):
        p=Player(FakeDevice());p.play({'id':'empty'},np.array([],np.int16));wait(lambda:p.finished);p.stop()


class FakeCatalog:
    def __init__(self):self.items={'poem_p01':{'id':'poem_p01','title':'静夜思','timeline':[]}}
    def public(self):return list(self.items.values())
    def load(self,key):return self.items[key],np.zeros(96000,np.int16)


class ServiceTests(unittest.TestCase):
    def test_missing_hardware_is_optional(self):
        s=AudioService(FakeCatalog(),lambda:(_ for _ in ()).throw(ValueError('not installed')))
        wait(lambda:not s.status()['initializing']);self.assertFalse(s.status()['available']);s.close()
    def test_failed_initialization_keeps_catalog_and_retry_recovers(self):
        calls=[]
        def factory():
            calls.append(1)
            if len(calls)==1:raise RuntimeError('clock not ready')
            return FakeDevice()
        s=AudioService(FakeCatalog(),factory)
        try:
            wait(lambda:not s.thread.is_alive())
            self.assertFalse(s.status()['available']);self.assertEqual(len(s.listing()['items']),1)
            s.submit('retry');wait(lambda:s.status()['available'])
            s.submit('play',{'id':'poem_p01'});wait(lambda:s.status()['playing'])
            self.assertEqual(len(calls),2)
        finally:s.close()

    def test_stop_during_slow_file_load_never_starts_playback(self):
        entered=threading.Event();release=threading.Event();cat=FakeCatalog();original=cat.load
        def slow(key):entered.set();release.wait(1);return original(key)
        cat.load=slow;device=FakeDevice();s=AudioService(cat,lambda:device)
        try:
            wait(lambda:s.status()['available']);s.submit('play',{'id':'poem_p01'})
            self.assertTrue(entered.wait(1));t=time.monotonic();s.submit('stop')
            self.assertLess(time.monotonic()-t,.05);release.set();time.sleep(.12)
            self.assertFalse(any(x[:2]==('ctrl',True) for x in device.calls))
        finally:release.set();s.close()
    def test_follow_does_not_stop_manual_playback(self):
        s=AudioService(FakeCatalog(),FakeDevice)
        try:
            wait(lambda:s.status()['available']);s.submit('play',{'id':'poem_p01'})
            wait(lambda:s.status()['playing']);s.follow('stop',owner='old-robot-job');time.sleep(.1)
            self.assertTrue(s.status()['playing'])
            with self.assertRaises(ValueError):s.submit('volume',{'volume':101})
            with self.assertRaises(ValueError):s.submit('play',{'id':'../../etc/passwd'})
        finally:s.close()


if __name__=='__main__':unittest.main()
