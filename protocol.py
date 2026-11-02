"""Read-only STS bring-up protocol. No register-write or motion operations.

Python 3.8+; see docs/SOURCES.md for register/protocol references.
"""
import time
import math

# Explicit STS read allowlist. Unknown register writes are never accepted here.
READ_FIELDS = {
    'position': (56, 2), 'mode': (33, 1), 'torque': (40, 1), 'model': (3, 2),
    'firmware': (0, 2), 'acceleration': (41, 1), 'goal_speed': (46, 2),
    'position_speed': (56, 4), 'health': (60, 4), 'current': (69, 2),
    'pid': (21, 3), 'dead_zone': (26, 2), 'velocity_unit': (82, 1),
    'maximum_acceleration': (85, 1), 'acceleration_multiplier': (86, 1),
    'phase': (18, 1), 'maximum_speed': (84, 1),
}


def _signed(raw, bit=15):
    return -(raw & ((1 << bit)-1)) if raw & (1 << bit) else raw


class ProbeError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def request(servo_id, operation):
    if type(servo_id) is not int or not 1 <= servo_id <= 253:
        raise ValueError("ID must be an integer in 1..253; no broadcast")
    if operation == "ping":
        body = bytes([servo_id, 2, 1])
    elif operation in READ_FIELDS:
        address, size = READ_FIELDS[operation]
        body = bytes([servo_id, 4, 2, address, size])
    else:
        raise ValueError("Only ping and position are implemented")
    return b"\xff\xff" + body + bytes([(~sum(body)) & 255])


def exchange(port, servo_id, operation, timeout=0.15, deadline=None):
    packet = request(servo_id, operation)
    expected_params = 0 if operation == "ping" else READ_FIELDS[operation][1]
    if not math.isfinite(float(timeout)) or timeout <= 0 or (deadline is not None and not math.isfinite(float(deadline))):
        raise ValueError('Invalid transaction budget')
    started = time.monotonic()
    deadline = started+timeout if deadline is None else min(float(deadline), started+timeout)
    if deadline <= started:
        raise ProbeError('TIMEOUT', 'Transaction budget expired before request')
    port.reset_input_buffer()  # Discard buffered replies from earlier requests.
    if port.write(packet) != len(packet):
        raise ProbeError("SHORT_WRITE", "Incomplete request transmission")

    def read_exact(count):
        result = bytearray()
        while len(result) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("TIMEOUT", "Response deadline expired")
            port.timeout = min(0.025, remaining)
            block = port.read(count - len(result))
            if block:
                result.extend(block)
            else:
                time.sleep(min(0.001, remaining))
        return bytes(result)

    # Fail on leading noise/echo rather than guessing which frame was intended.
    header = read_exact(4)
    if header[:2] != b"\xff\xff":
        raise ProbeError("HEADER", "Unexpected header/noise; check adapter echo and wiring")
    if header[2] != servo_id:
        raise ProbeError("ID_MISMATCH", "Reply ID differs from requested ID")
    if header[3] != expected_params + 2:
        raise ProbeError("LENGTH", "Unexpected status packet length")
    body = read_exact(header[3])
    if ((~sum(header[2:] + body[:-1])) & 255) != body[-1]:
        raise ProbeError("CHECKSUM", "Invalid status packet checksum")
    # FTServo's STS/SMS SDK defines 0x01/02/04/08/20 as faults;
    # 0x10 is not one of those fault bits. Some 3.15 firmware replies carry
    # it while still providing a valid encoder word. Preserve the data and
    # raw flag instead of converting every joint's feedback into a timeout.
    # Header, length, ID and checksum have already been validated above.
    if body[0] & ~0x10:
        raise ProbeError("SERVO_ERROR", "Servo status error 0x%02x" % body[0])
    if operation == "ping":
        return None
    if operation in ("mode", "torque", "acceleration", "velocity_unit", "maximum_acceleration", "acceleration_multiplier", "phase", "maximum_speed"):
        return body[1]
    if operation == 'firmware':
        return dict(major=body[1], minor=body[2])
    if operation == 'pid':
        return dict(p=body[1], d=body[2], i=body[3])
    if operation == 'dead_zone':
        return dict(cw=body[1], ccw=body[2])
    if operation == 'health':
        result=dict(load_raw=body[1] | body[2] << 8,
                    voltage_raw=body[3], temperature_c=body[4])
        if body[0]:result['status_byte']=body[0]
        return result
    raw = body[1] | (body[2] << 8)
    if operation in ("model", 'goal_speed'):
        return raw
    if operation == 'position_speed':
        result=dict(position_count=_signed(raw), speed_raw=body[3] | body[4] << 8,
                    speed_raw_signed=_signed(body[3] | body[4] << 8))
        if body[0]:result['status_byte']=body[0]
        return result
    if operation == 'current':
        return dict(current_raw=raw)
    # Preserve the wire word; STS signed magnitude uses bit 15. No angle mapping.
    signed = -(raw & 0x7FFF) if raw & 0x8000 else raw
    result={"raw_word": raw, "position_count": signed}
    if body[0]:result['status_byte']=body[0]
    return result


def exchange_deadline(port, servo_id, operation, deadline):
    return exchange(port, servo_id, operation, deadline=deadline)


def servo_snapshot(port, ids, timeout=.04):
    """Read current parameters once. Never infer defaults from failed reads."""
    result = {}
    for sid in ids:
        row = {}
        for operation in ('model', 'firmware', 'mode', 'acceleration', 'goal_speed',
                          'pid', 'dead_zone', 'velocity_unit', 'maximum_acceleration',
                          'acceleration_multiplier', 'phase', 'maximum_speed'):
            try:
                row[operation] = exchange(port, sid, operation, timeout)
            except (ProbeError, OSError) as exc:
                row[operation] = dict(available=False, error=str(exc)[:120])
        result[sid] = row
    return result


def probe(port, ids, timeout=0.15):
    rows = []
    for servo_id in ids:
        row = {"id": servo_id, "ping_ok": False, "read_ok": False,
               "raw_word": None, "position_count": None, "error": None}
        started = time.monotonic()
        try:
            exchange(port, servo_id, "ping", timeout)
            row["ping_ok"] = True
            row.update(exchange(port, servo_id, "position", timeout))
            row["read_ok"] = True
        except ProbeError as exc:
            row["error"] = {"code": exc.code, "detail": str(exc)}
        except (OSError, ValueError) as exc:
            row["error"] = {"code": "IO_ERROR", "detail": str(exc)}
        row["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
        rows.append(row)
    return rows


class DemoPort:
    """Byte-level fake transport used by the UI and protocol fault tests."""
    def __init__(self, scenario="normal"):
        if scenario not in ("normal", "missing", "checksum", "servo_error"):
            raise ValueError("Unknown demo scenario")
        self.scenario = scenario
        self.timeout = 0.02
        self.buffer = bytearray()
        self.writes = []
        self.positions = {i: 2048 + i * 17 for i in range(1, 254)}
        self.torques = {i: 1 for i in range(1, 254)}
        self.accelerations = {i: 50 for i in range(1, 254)}
        self.speeds = {i: 100 for i in range(1, 254)}

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, packet):
        self.writes.append(bytes(packet))
        servo_id = packet[2]
        if packet[4] == 0x83:
            if servo_id != 254 or ((~sum(packet[2:-1])) & 255) != packet[-1]:
                raise AssertionError("Bad mock write")
            address, size = packet[5:7]
            for offset in range(7, len(packet)-1, size+1):
                sid = packet[offset]
                data = packet[offset+1:offset+1+size]
                if address == 42 and size == 6:
                    self.positions[sid] = data[0] | data[1] << 8
                    self.speeds[sid] = data[4] | data[5] << 8
                elif address == 41 and size == 7:
                    self.accelerations[sid] = data[0]
                    self.positions[sid] = data[1] | data[2] << 8
                    self.speeds[sid] = data[5] | data[6] << 8
                elif address == 40 and size == 1:
                    self.torques[sid] = data[0]
                else:
                    raise AssertionError("Unsupported mock write")
            return len(packet)
        operation = 'ping' if packet[4] == 1 else next((name for name, field in READ_FIELDS.items()
            if field == (packet[5], packet[6])), None)
        if packet != request(servo_id, operation):
            raise AssertionError("Demo transport refuses non-read-only packets")
        if self.scenario == "missing" and servo_id == 3:
            return len(packet)
        value = self.positions[servo_id] if operation == "position" else 777
        params = [] if operation == "ping" else [value & 255, value >> 8]
        if operation in ("mode", "torque"):
            params = [0 if operation == "mode" else self.torques[servo_id]]
        elif operation == 'position_speed':
            p = self.positions[servo_id]; params = [p & 255, p >> 8, 0, 0]
        elif operation == 'acceleration':
            params = [self.accelerations[servo_id]]
        elif operation == 'goal_speed':
            value = self.speeds[servo_id]; params = [value & 255, value >> 8]
        elif operation == 'firmware':
            params = [2, 54]
        elif operation == 'pid':
            params = [32, 0, 0]
        elif operation == 'dead_zone':
            params = [1, 1]
        elif operation == 'health':
            params = [0, 0, 74, 25]
        elif operation == 'current':
            params = [0, 0]
        elif operation in ('velocity_unit', 'acceleration_multiplier'):
            params = [1]
        elif operation == 'maximum_acceleration':
            params = [254]
        elif operation == 'phase':
            params = [12]
        elif operation == 'maximum_speed':
            params = [65]
        error = 4 if self.scenario == "servo_error" and servo_id == 3 else 0
        body = bytes([servo_id, len(params) + 2, error] + params)
        checksum = (~sum(body)) & 255
        if self.scenario == "checksum" and servo_id == 3:
            checksum ^= 1
        self.buffer.extend(b"\xff\xff" + body + bytes([checksum]))
        return len(packet)

    def read(self, count):
        # Fragment replies deliberately, as USB reads need not return a frame.
        count = min(count, 2)
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def close(self):
        pass
