# ATK Navigator_7020 vendor master XDC: LCD touch I2C and dedicated reset/IRQ.
set_property -dict {PACKAGE_PIN R19 IOSTANDARD LVCMOS33} [get_ports i2c_touch_scl_io]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports i2c_touch_sda_io]
set_property -dict {PACKAGE_PIN M19 IOSTANDARD LVCMOS33} [get_ports {gpio_touch_tri_io[0]}]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVCMOS33} [get_ports {gpio_touch_tri_io[1]}]
