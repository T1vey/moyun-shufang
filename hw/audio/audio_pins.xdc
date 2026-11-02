# Onboard WM8960 (Navigator Z20 base board; pins from the ATK 37_audio_loopback example).
set_property -dict {PACKAGE_PIN E19 IOSTANDARD LVCMOS33} [get_ports aud_mclk]
set_property -dict {PACKAGE_PIN M18 IOSTANDARD LVCMOS33} [get_ports aud_bclk]
# L20 is the WM8960 ADCLRC pin (legacy RTL port name). Codec R24.LRCM keeps it active for DAC-only playback.
set_property -dict {PACKAGE_PIN L20 IOSTANDARD LVCMOS33} [get_ports aud_daclrc]
set_property -dict {PACKAGE_PIN G17 IOSTANDARD LVCMOS33} [get_ports aud_dacdat]
set_property -dict {PACKAGE_PIN E18 IOSTANDARD LVCMOS33} [get_ports aud_scl]
set_property -dict {PACKAGE_PIN F17 IOSTANDARD LVCMOS33 PULLUP TRUE} [get_ports aud_sda]
# The codec is the I2S master: BCLK (1.536 MHz) and DACLRC are 2-FF sampled by FCLK0 and
# DACDAT changes >300 ns before the codec samples it; the I2C bus runs at 100 kHz.
set_false_path -from [get_ports {aud_bclk aud_daclrc aud_sda}]
set_false_path -to [get_ports {aud_mclk aud_dacdat aud_scl aud_sda}]
