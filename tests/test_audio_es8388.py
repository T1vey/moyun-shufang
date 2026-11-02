"""ES8388 profile contracts: clocks, physical output routing and true mute.

Pure configuration tests; no imports of PYNQ and no hardware or robot access.
"""
import unittest

from audio_player import codec_es8388 as codec


def writes(sequence):
    return [(reg, value) for reg, value in sequence if reg != "wait"]


class ES8388ProfileTests(unittest.TestCase):
    def test_native_rate_is_not_mislabeled_as_48k(self):
        self.assertEqual(codec.I2C_ADDRESS, 0x10)
        self.assertEqual(codec.MCLK_HZ, 12_500_000)
        self.assertEqual(codec.SAMPLE_RATE_HZ, 48_828.125)
        self.assertEqual(codec.BCLK_HZ / codec.SAMPLE_RATE_HZ, 64)
        self.assertNotEqual(codec.SAMPLE_RATE_HZ, 48_000)

    def test_profile_selects_master_16bit_i2s_and_dac_lrck(self):
        regs = dict(writes(codec.init_sequence()))
        self.assertEqual(regs[codec.R_MASTERMODE], 0x80)
        self.assertEqual(regs[codec.R_DACFORMAT], 0x18)
        self.assertEqual(regs[codec.R_DACRATE] & 0x1F, 2)  # Datasheet /256 selector.
        self.assertEqual(regs[codec.R_ADCRATE] & 0x1F, 2)
        self.assertEqual(regs[codec.R_LRCK], 0x80)  # Shared LRCK uses DAC, not ADC.
        self.assertTrue(regs[codec.R_CONTROL1] & 0x40)
        self.assertEqual(regs[codec.R_CHIPPOWER], 0)
        self.assertEqual(regs[codec.R_ADCPOWER], 0xFF)

    def test_default_initialization_never_enables_an_analog_output(self):
        sequence = writes(codec.init_sequence())
        for reg, value in sequence:
            if reg == codec.R_DACPOWER:
                self.assertEqual(value & 0x3C, 0)
            if reg == codec.R_DACCONTROL:
                self.assertTrue(value & 4)
        regs = dict(sequence)
        self.assertEqual(regs[codec.R_DACPOWER] & 0xC0, 0)  # DAC clocks stay alive.
        self.assertEqual(regs[codec.R_DACCONTROL], codec.DAC_MUTED)

    def test_speaker_and_phone_use_the_physical_v39_routes(self):
        # Schematic: MD8002A uses output pair 2; PHONE uses output pair 1.
        speaker = dict(codec.output_volume(100, 0))
        self.assertEqual(speaker[4], 0x0C)
        self.assertEqual((speaker[48], speaker[49]), (30, 30))
        self.assertEqual((speaker[46], speaker[47]), (0, 0))
        phone = dict(codec.output_volume(0, 100))
        self.assertEqual(phone[4], 0x30)
        self.assertEqual((phone[46], phone[47]), (30, 30))
        self.assertEqual((phone[48], phone[49]), (0, 0))
        both = dict(codec.output_volume(60, 60))
        self.assertEqual(both[4], 0x3C)

    def test_zero_percent_is_power_gated_not_just_minus45db(self):
        for sp, hp in [(0, 0), (0, 80), (75, 0), (-10, 0)]:
            with self.subTest(sp=sp, hp=hp):
                regs = dict(codec.output_volume(sp, hp))
                if sp <= 0:
                    self.assertEqual(regs[4] & 0x0C, 0)
                if hp <= 0:
                    self.assertEqual(regs[4] & 0x30, 0)
                self.assertEqual(bool(regs[25] & 4), sp <= 0 and hp <= 0)
                self.assertEqual(regs[4] & 0xC0, 0)  # Do not turn off frame clocks.

    def test_gain_is_monotonic_and_never_exceeds_zero_db(self):
        values = [codec.volume_code(p) for p in range(101)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0)
        self.assertEqual(values[-1], 30)
        self.assertEqual(codec.volume_code(-100), 0)
        self.assertEqual(codec.volume_code(1000), 30)
        for percent in range(-1, 102):
            regs = dict(codec.output_volume(percent, percent))
            for reg in (46, 47, 48, 49):
                analog_db = -45 + 1.5 * regs[reg]
                self.assertLessEqual(analog_db, 0)
                self.assertLessEqual(analog_db - 0.5 * codec.DAC_ATTENUATION, 0)

    def test_output_enable_follows_clock_format_and_gain_setup(self):
        sequence = writes(codec.init_sequence(60, 40))
        first_output = next(i for i, (r, v) in enumerate(sequence)
                            if r == codec.R_DACPOWER and v & 0x3C)
        before = dict(sequence[:first_output])
        for reg in (codec.R_MASTERMODE, codec.R_DACFORMAT, codec.R_DACRATE,
                    codec.R_LRCK, codec.R_LMIX, codec.R_RMIX, codec.R_DAC_L,
                    codec.R_DAC_R, codec.R_HP_L, codec.R_HP_R,
                    codec.R_SPK_L, codec.R_SPK_R):
            self.assertIn(reg, before)
        self.assertTrue(before[codec.R_DACCONTROL] & 4)
        self.assertEqual(sequence[-1], (codec.R_DACCONTROL, codec.DAC_UNMUTED))

    def test_volume_changes_are_muted_until_routes_and_gains_are_written(self):
        for sp, hp in [(0, 0), (60, 0), (0, 60), (100, 100)]:
            sequence = codec.output_volume(sp, hp)
            self.assertEqual(sequence[0], (codec.R_DACCONTROL, codec.DAC_MUTED))
            self.assertEqual(sequence[-2][0], codec.R_DACPOWER)
            self.assertEqual(sequence[-1][0], codec.R_DACCONTROL)

    def test_playback_does_not_mix_microphone_or_enable_sound_effects(self):
        regs = dict(writes(codec.init_sequence()))
        for reg in (codec.R_LMIX, codec.R_RMIX):
            self.assertTrue(regs[reg] & 0x80)   # DAC connection.
            self.assertFalse(regs[reg] & 0x40)  # Analog-input connection off.
        self.assertEqual(regs[codec.R_DAC_EFFECTS], 0)

    def test_all_commands_are_raw_byte_registers_not_wm8960_words(self):
        for sequence in (codec.init_sequence(), codec.init_sequence(100, 100),
                         codec.output_volume(100, 100)):
            for reg, value in sequence:
                if reg == "wait":
                    self.assertGreater(value, 0)
                    self.assertLessEqual(value, 0.5)
                else:
                    self.assertGreaterEqual(reg, 0)
                    self.assertLessEqual(reg, 52)
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 255)


if __name__ == "__main__":
    unittest.main()
