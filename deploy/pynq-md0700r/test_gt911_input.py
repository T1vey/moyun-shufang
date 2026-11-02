import unittest
from gt911_input import TouchState

def packet(sequence,pressed,x=100,y=200):
    return (sequence<<22)|(int(pressed)<<21)|(1<<20)|(x<<10)|y

class InputTests(unittest.TestCase):
    def test_two_distinct_gestures_and_drag(self):
        state=TouchState()
        self.assertEqual(state.step(packet(1,True),1),[('move',100,200),('down',)])
        self.assertEqual(state.step(packet(2,True,130,250),1.1),[('move',130,250)])
        self.assertEqual(state.step(packet(3,False,130,250),1.2),[('up',)])
        self.assertEqual(state.step(packet(4,True,700,400),1.3),[('move',700,400),('down',)])
        self.assertEqual(state.step(packet(5,False,700,400),1.4),[('up',)])
        self.assertEqual((state.presses,state.releases),(2,2))

    def test_stale_packet_releases_once(self):
        state=TouchState()
        p=packet(1,True)
        state.step(p,1)
        self.assertEqual(state.step(p,1.1),[])
        self.assertEqual(state.step(p,1.4),[('up',)])
        self.assertEqual(state.step(p,2),[])

    def test_invalid_and_sequence_wrap(self):
        state=TouchState()
        self.assertEqual(state.step(0,0),[])
        self.assertEqual(state.step(packet(1023,True,1,700),1),[])
        state.step(packet(1023,True),1)
        self.assertEqual(state.step(packet(0,False),1.1),[('up',)])

if __name__=='__main__': unittest.main()
