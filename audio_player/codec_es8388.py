"""ES8388 DAC playback for the Navigator Z20 V3.9 base board.

Register tuples are raw *8-bit address, 8-bit data*, sent to I2C address 0x10;
they must not pass through the WM8960 7+9-bit register encoder.

The existing PL provides 12.5 MHz MCLK.  ES8388 has no programmable sample-rate
PLL: master mode with /256 produces exactly 48,828.125 frames/s.  The player must
resample 48 kHz recordings to SAMPLE_RATE_HZ to preserve pitch and duration.
BCLK is MCLK/4 (64 clocks/frame), carrying 16-bit I2S words in 32-bit slots.

Sources in the ATK Z20资料盘(A盘):
* 7_芯片数据手册/19_音频编解码芯片/es8388.pdf, rev 5.0, pp. 7-16, 23-29.
* 4_Source_Code/1_FPGA_Design/ZYNQ_7020_FPGA/37_audio_loopback/rtl/
  i2c_reg_cfg.v and audio_config.v (power/reference initialization reference).
* 3_开发板原理图和硬件相关文件/领航者ZYNQ底板原理图_V3.9.pdf, sheet 2:
  PHONE = LOUT1/ROUT1 through C35/C37; MD8002A SPK_IN = LOUT2/ROUT2
  through C39/C95.  This profile changes the example's slave mode to master
  mode and disables its analog-input mixing and stereo-enhancement settings.
"""

NAME = "ES8388"
I2C_ADDRESS = 0x10
MCLK_HZ = 12_500_000
MCLK_FS_RATIO = 256
BCLK_HZ = MCLK_HZ / 4
SAMPLE_RATE_HZ = MCLK_HZ / MCLK_FS_RATIO
SAMPLE_RATE = SAMPLE_RATE_HZ

R_CONTROL1, R_CONTROL2, R_CHIPPOWER, R_ADCPOWER, R_DACPOWER = range(5)
R_MASTERMODE = 8
R_ADCRATE = 13
R_DACFORMAT, R_DACRATE, R_DACCONTROL = 23, 24, 25
R_DAC_L, R_DAC_R = 26, 27
R_DAC_CLICKFREE, R_DAC_EFFECTS = 28, 29
R_LMIX, R_RMIX, R_LRCK = 39, 42, 43
R_HP_L, R_HP_R, R_SPK_L, R_SPK_R = 46, 47, 48, 49

OUTPUT_0DB = 30                 # 1.5 dB/step: 0 = -45 dB, 30 = 0 dB.
DAC_ATTENUATION = 10            # Preserve the ATK example's -5 dB digital gain.
DAC_MUTED = 0x26                # Default 0x22 plus DACMute (bit 2).
DAC_UNMUTED = 0x22              # Keep soft ramp and reserved default bits.
PHONE_ENABLE = 0x30             # R4: LOUT1 (bit 5), ROUT1 (bit 4).
SPEAKER_ENABLE = 0x0C           # R4: LOUT2 (bit 3), ROUT2 (bit 2).


def _percent(value):
    return max(0, min(100, int(value)))


def volume_code(percent):
    """Map 0..100% to -45..0 dB; code zero alone is *not* a mute."""
    return round(OUTPUT_0DB * _percent(percent) / 100)


def output_volume(speaker_pct, phone_pct):
    """Set both routes; 0% disables that route's output buffers completely.

    Keep the DACs powered even when both routes are off so LRCK continues and
    the PL frame counter remains usable.  Global DAC mute protects gain/route
    changes; it stays set if both outputs are disabled.  All PGA gains are
    capped at 0 dB, with an additional -5 dB digital attenuation from init.
    """
    speaker_pct, phone_pct = _percent(speaker_pct), _percent(phone_pct)
    sp, hp = volume_code(speaker_pct), volume_code(phone_pct)
    power = (SPEAKER_ENABLE if speaker_pct else 0) | (PHONE_ENABLE if phone_pct else 0)
    return [
        (R_DACCONTROL, DAC_MUTED),
        (R_SPK_L, sp), (R_SPK_R, sp),
        (R_HP_L, hp), (R_HP_R, hp),
        (R_DACPOWER, power),
        (R_DACCONTROL, DAC_UNMUTED if power else DAC_MUTED),
    ]


def init_sequence(speaker_pct=0, phone_pct=0):
    """Initialize clocked DACs; default startup is muted with all outputs off.

    The device layer first calls init_sequence(0, 0), verifies the actual frame
    rate, and only then calls output_volume() with the requested volumes.
    The arguments also permit explicit initial volumes after initialization.
    """
    return [
        (R_CONTROL1, 0x80), ("wait", 0.01),       # Control-port reset.
        (R_CONTROL1, 0x00),
        (R_DACCONTROL, DAC_MUTED),
        (R_CONTROL2, 0x58),                     # Analog power down during setup.
        (R_CHIPPOWER, 0xF3),                    # Hold digital paths/state machines reset.
        (R_ADCPOWER, 0xFF),                     # Playback only; analog ADC/input paths off.
        (R_DACPOWER, 0xC0),                     # DACs and every output buffer off.
        (R_MASTERMODE, 0x80),                   # Master, no MCLK/2, automatic BCLK.
        (R_ADCRATE, 0x02),                      # /256, same ratio as the DAC.
        (R_DACFORMAT, 0x18),                    # 16-bit, normal polarity, I2S.
        (R_DACRATE, 0x02),                      # Single speed; 12.5 MHz / 256.
        (R_LRCK, 0x80),                         # Shared LRCK pin uses DAC clock.
        (R_CONTROL1, 0x46),                     # LRCM + reference + ATK 500k VMID.
        (R_CONTROL2, 0x50),                     # ATK analog/reference power setup.
        ("wait", 0.1),
        (R_CHIPPOWER, 0x00),                    # Release DAC clock and digital reset.
        (R_DACPOWER, 0x00),                     # DACs on, outputs still off.
        (R_LMIX, 0xB8), (R_RMIX, 0xB8),         # DAC only; no mic/line-input mixing.
        (R_DAC_CLICKFREE, 0x08),                # Click-free power up/down enabled.
        (R_DAC_EFFECTS, 0x00),                  # No stereo enhancement or forced zero.
        (R_DAC_L, DAC_ATTENUATION), (R_DAC_R, DAC_ATTENUATION),
        *output_volume(speaker_pct, phone_pct),
    ]
