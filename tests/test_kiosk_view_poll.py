"""A stalled local HTTP response must not stall the GTK event thread."""
import io
import threading
import time
import unittest
from scripts.user_gui_kiosk import ViewPoller

class PollerTests(unittest.TestCase):
    def test_slow_or_failed_http_keeps_last_mode_without_blocking_reader(self):
        entered=threading.Event();release=threading.Event();second=threading.Event()
        class Opener:
            count=0
            def open(self,*args,**kwargs):
                self.count+=1
                if self.count==1:
                    entered.set();release.wait(2)
                    return io.StringIO('{"view":"settings"}')
                second.set();raise OSError('local API temporarily unavailable')
        poller=ViewPoller(Opener(),'http://127.0.0.1/api/view',.01)
        try:
            poller.start();self.assertTrue(entered.wait(1))
            begin=time.monotonic()
            for _ in range(1000):self.assertIsNone(poller.mode)
            self.assertLess(time.monotonic()-begin,.1)
            release.set();self.assertTrue(second.wait(1))
            self.assertEqual(poller.mode,'settings')
        finally:release.set();poller.close();poller.worker.join(2)

if __name__=='__main__':unittest.main()
