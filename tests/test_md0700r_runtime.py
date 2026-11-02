"""Userspace display startup/teardown gates; no actual device access."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import numpy as np
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def display_module():
    spec=importlib.util.spec_from_file_location('display_test',ROOT/'deploy/pynq-md0700r/md0700r_display.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'pynq':SimpleNamespace(Overlay=Mock(),MMIO=Mock(),allocate=Mock())}):
        spec.loader.exec_module(module)
    return module


class UserspaceDisplaySafetyTests(unittest.TestCase):
    def test_fast_copy_preserves_rgb_and_destination_allocation(self):
        module=display_module();rng=np.random.default_rng(5)
        source=rng.integers(0,256,size=(7,33,4),dtype=np.uint8)
        expected=source[:,:,2::-1].copy();dst=np.zeros(expected.shape,dtype=np.uint8)
        ptr=dst.ctypes.data
        copy,backend=module.pixel_copier();copy(source,dst)
        np.testing.assert_array_equal(dst,expected);self.assertEqual(dst.ctypes.data,ptr)
        with patch.dict(sys.modules,{'cv2':None}):copy,backend=module.pixel_copier()
        self.assertEqual(backend,'numpy_channels');dst[:]=0;copy(source,dst)
        np.testing.assert_array_equal(dst,expected)

    def test_pacing_counts_copy_time_and_never_catches_up(self):
        module=display_module()
        self.assertAlmostEqual(module.frame_delay(1,1.007,30),1/30-.007)
        self.assertEqual(module.frame_delay(1,1.06,30),0)

    def test_panel_primary_colors_and_amber_do_not_exchange_red_blue(self):
        module=display_module()
        # XWD little-endian B,G,R,X; include nonzero padding to catch leakage.
        xwd=np.array([[[0,0,255,99],[0,255,0,99],[255,0,0,99],
                       [255,255,255,99],[69,173,243,99]]],dtype=np.uint8)
        expected=np.array([[[255,0,0],[0,255,0],[0,0,255],
                            [255,255,255],[243,173,69]]],dtype=np.uint8)
        np.testing.assert_array_equal(module.panel_pixels(xwd),expected)

    def test_close_keeps_buffer_and_reset_assertion_after_dma_drain(self):
        module=display_module();events=[];reads=0
        class Frame:
            def write(self,*args):events.append(('frame_write',args))
            def read(self,offset):
                nonlocal reads
                reads+=1
                idle=reads>=4
                events.append(('idle',idle))
                return 4 if idle else 0
        lcd=module.LCD();lcd.frame=Frame()
        lcd.pwm=SimpleNamespace(write=lambda *args:events.append(('backlight_off',args)))
        lcd.reset=SimpleNamespace(read=lambda offset:1,
            write=lambda *args:events.append(('reset',args)))
        lcd.buffer=SimpleNamespace(freebuffer=lambda:events.append(('free',)))
        with patch.object(module.time,'monotonic',side_effect=[0,3]),patch.object(module.time,'sleep'):
            lcd.close()
        idle=next(i for i,value in enumerate(events) if value==('idle',True))
        reset=next(i for i,value in enumerate(events) if value[0]=='reset')
        free=next(i for i,value in enumerate(events) if value[0]=='free')
        self.assertLess(idle,reset);self.assertLess(reset,free);self.assertIsNone(lcd.buffer)

    def test_failed_mmio_does_not_release_live_dma_buffer(self):
        module=display_module();events=[]
        lcd=module.LCD()
        def read(offset):
            events.append('read')
            if len(events)<3:raise OSError('temporary MMIO failure')
            return 4
        lcd.frame=SimpleNamespace(write=Mock(),read=read)
        lcd.pwm=SimpleNamespace(write=Mock(side_effect=OSError('PWM failure')))
        lcd.buffer=SimpleNamespace(freebuffer=lambda:events.append('free'))
        with patch.object(module.time,'sleep'):
            lcd.close()
        self.assertEqual(events,['read','read','read','free'])

    def test_partial_init_without_dma_is_safe_to_close(self):
        module=display_module();module.LCD().close()

    def test_board_scripts_parse_using_python38_grammar(self):
        for relative in ('md0700r_runtime.py','md0700r_contract.py','platform_runtime.py',
                         'scripts/load_platform.py','deploy/pynq-md0700r/md0700r_display.py',
                         'deploy/pynq-md0700r/gt911_input.py'):
            with self.subTest(relative=relative):
                ast.parse((ROOT/relative).read_text(encoding='utf-8'),feature_version=(3,8))

    def test_hardware_owner_services_do_not_force_kill_pending_dma(self):
        for relative in ('deploy/standalone/so101-platform.service',
                         'deploy/pynq-md0700r/so101-md0700r.service'):
            self.assertIn('TimeoutStopSec=infinity',(ROOT/relative).read_text())
        display=(ROOT/'deploy/pynq-md0700r/so101-md0700r.service').read_text()
        self.assertIn('BindsTo=so101-workbench.service so101-platform.service',display)


if __name__=='__main__':unittest.main()
