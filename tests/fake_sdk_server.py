"""Stand-in for build/tcb705/tcb_sdk_server (same line protocol), used by tests/test_tcb705_sdk.py.
Motions "finish" immediately: each MOVE is followed by its EVT DONE line. Nothing touches hardware."""
import sys

seq = 9; connected = False; speed = 0.0


def out(line):
    sys.stdout.write(line + '\n'); sys.stdout.flush()


print('SDK banner on the console: must be ignored by the client', flush=True)
for raw in sys.stdin:
    bits = raw.split()
    if not bits:
        continue
    cmd = bits[0]
    if cmd == 'QUIT':
        out('OK'); break
    if cmd == 'CONNECT':
        connected = True; out('OK V2.4.1 1.9.84-fake'); continue
    if not connected:
        out('ERR not connected'); continue
    if cmd == 'SPEED':
        v = float(bits[1])
        if not 0 <= v <= 100:
            out('ERR speed must be 0..100'); continue
        speed = v; out('OK %.6f' % speed)
    elif cmd == 'GETSPEED':
        out('OK %.6f' % speed)
    elif cmd in ('MOVEJ', 'MOVEL'):
        if len(bits) - 5 not in ((6, 7) if cmd == 'MOVEJ' else (6,)):
            out('ERR bad target'); continue
        seq += 1; out('OK %d' % seq); out('EVT DONE %d 1 1' % seq)
    elif cmd == 'STATE':
        out('OK 0 0 1')
    elif cmd in ('PAUSE', 'STOP'):
        out('OK')
    elif cmd == 'ALARM':
        out('OK 0')
    else:
        out('ERR unknown command')
