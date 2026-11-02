# OV7725 on the Navigator Z20 camera header (pinout from the ATK 43_ov7725_udp_pc example).
set_property -dict {PACKAGE_PIN W14 IOSTANDARD LVCMOS33} [get_ports cam_pclk]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports cam_rst_n]
set_property -dict {PACKAGE_PIN V15 IOSTANDARD LVCMOS33} [get_ports cam_sgm_ctrl]
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {cam_data[0]}]
set_property -dict {PACKAGE_PIN U13 IOSTANDARD LVCMOS33} [get_ports {cam_data[1]}]
set_property -dict {PACKAGE_PIN V13 IOSTANDARD LVCMOS33} [get_ports {cam_data[2]}]
set_property -dict {PACKAGE_PIN U15 IOSTANDARD LVCMOS33} [get_ports {cam_data[3]}]
set_property -dict {PACKAGE_PIN U14 IOSTANDARD LVCMOS33} [get_ports {cam_data[4]}]
set_property -dict {PACKAGE_PIN W13 IOSTANDARD LVCMOS33} [get_ports {cam_data[5]}]
set_property -dict {PACKAGE_PIN V12 IOSTANDARD LVCMOS33} [get_ports {cam_data[6]}]
set_property -dict {PACKAGE_PIN Y14 IOSTANDARD LVCMOS33} [get_ports {cam_data[7]}]
set_property -dict {PACKAGE_PIN U12 IOSTANDARD LVCMOS33} [get_ports cam_vsync]
set_property -dict {PACKAGE_PIN T12 IOSTANDARD LVCMOS33} [get_ports cam_href]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports cam_scl]
set_property -dict {PACKAGE_PIN T11 IOSTANDARD LVCMOS33 PULLUP TRUE} [get_ports cam_sda]

# PCLK (~24 MHz, module crystal) enters on a non clock-capable pin, as in the vendor design.
create_clock -period 40.000 -name cam_pclk [get_ports cam_pclk]
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets cam_pclk_IBUF]
# All PCLK <-> FCLK0 crossings are 2-FF synchronisers, a toggle handshake or dual-clock BRAM.
set_clock_groups -asynchronous -group [get_clocks cam_pclk] -group [get_clocks clk_fpga_0]
# DVP inputs are captured in IOB flip-flops at half the PCLK period margin; SCCB is ~100 kHz.
set_false_path -from [get_ports {cam_data[*] cam_href cam_vsync}]
set_false_path -to [get_ports {cam_scl cam_sda cam_rst_n cam_sgm_ctrl}]
set_false_path -from [get_ports cam_sda]
