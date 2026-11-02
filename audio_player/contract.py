"""Register map of audio_out_0 (hw/audio/rtl/audio_out.v); no hardware access here."""
ABI = 'tcb705-audio-v1'
IP_NAME = 'audio_out_0'
BASE = 0x40060000
SIZE = 0x10000
IDENTITY = 0x41554431          # 'AUD1'
VERSION = 0x20261027
SAMPLE_RATE = 48000

ID, VER, CTRL, STATUS, I2C, UNDERRUN, FRAMES, DEPTH, OVERFLOW = (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20)
FIFO_WINDOW = 0x1000           # 0x1000..0x1FFF: each u32 write pushes low then high sample
FIFO_WINDOW_WORDS = 0x400

CTRL_ENABLE, CTRL_CLEAR, CTRL_MCLK, CTRL_MUTE = 1, 2, 4, 8
STATUS_I2C_BUSY, STATUS_I2C_NACK, STATUS_BCLK = 1 << 16, 1 << 17, 1 << 18
I2C_DONE, CAPS = 0x24, 0x28
CAP_BUS_DIAG, CAP_ADDRESS_PROBE = 1, 2
STATUS_SDA, STATUS_BUS_STUCK = 1 << 19, 1 << 20
I2C_PROBE = 1 << 24
WM8960_ADDR = 0x1A


def level(status):
    return status & 0x7FFF


def i2c_word(reg, value):
    """WM8960 7-bit register address + 9-bit data in two bytes."""
    if not 0 <= reg < 0x38 or not 0 <= value < 0x200:
        raise ValueError('WM8960 register/value out of range')
    byte0 = (reg << 1) | (value >> 8)
    return WM8960_ADDR | (byte0 << 8) | ((value & 0xFF) << 16)
