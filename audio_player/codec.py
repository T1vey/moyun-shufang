"""WM8960 playback setup (datasheet rev 4.4).

MCLK = 12.5 MHz from the PL (FCLK0 / 8).  The codec PLL makes SYSCLK = 12.288 MHz
(f2 = 4 x 2 x 12.288 = 98.304 MHz, SYSCLKDIV = 2), DAC 48 kHz, and the codec is the I2S
master with BCLK = SYSCLK / 8 = 1.536 MHz (16-bit words).  Output: DAC -> output mixers
-> headphone (PHONE jack) and class D speaker (the board's 8 ohm speaker is on SPK_R).
"""
MCLK_HZ = 12_500_000
SYSCLK_HZ = 12_288_000

R_ADDCTL2 = 0x18  # R24 LRCM: keep ADCLRC active during DAC-only playback
R_HP_L, R_HP_R, R_CLK1, R_DACCTL1, R_IFACE1, R_CLK2 = 0x02, 0x03, 0x04, 0x05, 0x07, 0x08
R_DAC_L, R_DAC_R, R_RESET, R_PWR1, R_PWR2, R_LMIX, R_RMIX = 0x0A, 0x0B, 0x0F, 0x19, 0x1A, 0x22, 0x25
R_SPK_L, R_SPK_R, R_PWR3, R_CLASSD1, R_PLL_N, R_PLL_K1, R_PLL_K2, R_PLL_K3 = (
    0x28, 0x29, 0x2F, 0x31, 0x34, 0x35, 0x36, 0x37)

SPK_MAX = 0x79      # 0 dB output PGA ceiling; actual power depends on supply/load
HP_MAX = 0x79


def pll(mclk_hz=MCLK_HZ):
    """(N, K) for f2 = 8 x SYSCLK; 5 < N < 13 required, prescaler off."""
    r = 8 * SYSCLK_HZ / mclk_hz
    n = int(r)
    if not 5 < n < 13:
        raise ValueError('WM8960 PLL ratio out of range')
    return n, int((1 << 24) * (r - n))


def volume_code(percent, top):
    """0..100 % -> output PGA code; 0 mutes (0x2F and below are mute)."""
    percent = max(0, min(100, int(percent)))
    if percent == 0:
        return 0x00
    return 0x30 + round((top - 0x30) * percent / 100)


def output_volume(speaker_pct, phone_pct):
    sp, hp = volume_code(speaker_pct, SPK_MAX), volume_code(phone_pct, HP_MAX)
    # The update bit (bit 8) on the second register of each pair applies both at once.
    return [(R_SPK_L, sp), (R_SPK_R, 0x100 | sp), (R_HP_L, hp), (R_HP_R, 0x100 | hp)]


def init_sequence(speaker_pct=60, phone_pct=60):
    """[(register, value) or ('wait', seconds)] in order."""
    n, k = pll()
    return [
        (R_RESET, 0x000), ('wait', 0.05),
        (R_PWR1, 0x0C0),                          # VMID 50k divider, VREF
        ('wait', 0.1),
        (R_PLL_N, 0x020 | n),                     # fractional mode, no prescale
        (R_PLL_K1, (k >> 16) & 0xFF), (R_PLL_K2, (k >> 8) & 0xFF), (R_PLL_K3, k & 0xFF),
        (R_PWR2, 0x001),                          # PLL on first
        ('wait', 0.02),
        (R_CLK1, 0x005),                          # SYSCLK = PLL / 2, DAC 48 kHz
        (R_CLK2, 0x1C7),                          # class D clock SYSCLK/16, BCLK = SYSCLK/8
        (R_IFACE1, 0x042),                        # master, 16-bit, I2S
        (R_ADDCTL2, 0x004),                       # L20 is ADCLRC; LRCM enables it with DACs on (DS p56)
        (R_PWR2, 0x1F9),                          # DACL DACR LOUT1 ROUT1 SPKL SPKR PLL
        (R_PWR3, 0x00C),                          # left/right output mixers
        (R_LMIX, 0x150), (R_RMIX, 0x150),         # DAC -> output mixers
        (R_DAC_L, 0x0FF), (R_DAC_R, 0x1FF),       # DAC 0 dB
        *output_volume(speaker_pct, phone_pct),
        (R_CLASSD1, 0x0F7),                       # both class D speaker channels on
        (R_DACCTL1, 0x000),                       # DAC unmute
    ]
