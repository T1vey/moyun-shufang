"""Read a manually positioned pen through a PC USB servo adapter, never move."""
import statistics
import time


def read_pose(port_name, machine, baudrate=1000000):
    import serial
    from protocol import exchange
    device = serial.Serial(baudrate=baudrate,timeout=.15,write_timeout=.2)
    device.dtr = False
    device.rts = False
    device.port = port_name
    class ReadOnly:
        @property
        def timeout(self):return device.timeout
        @timeout.setter
        def timeout(self,value):device.timeout=value
        def reset_input_buffer(self):device.reset_input_buffer()
        def read(self,count):return device.read(count)
        def write(self,packet):
            if len(packet)<6 or packet[4] not in (1,2) or packet[2]==254:
                raise ValueError('PC pose reader forbids motor commands')
            return device.write(packet)
    samples=[]
    device.open()
    try:
        channel=ReadOnly()
        for joint in machine['joints']:
            sid=joint['id']
            exchange(channel,sid,'ping')
            if exchange(channel,sid,'model') != 777 or exchange(channel,sid,'mode') != 0:
                raise ValueError('ID %s 舵机型号或位置模式不匹配' % sid)
        for index in range(3):
            samples.append({joint['id']:exchange(channel,joint['id'],'position')['position_count']
                            for joint in machine['joints']})
            if index<2:time.sleep(.05)
    finally:device.close()
    return dict(port=port_name,baudrate=baudrate,samples=samples,
        counts={joint['id']:int(statistics.median(row[joint['id']] for row in samples)) for joint in machine['joints']},
        spread_counts={joint['id']:max(row[joint['id']] for row in samples)-min(row[joint['id']] for row in samples) for joint in machine['joints']},
        scope='read-only user-confirmed pose; no motor writes')
