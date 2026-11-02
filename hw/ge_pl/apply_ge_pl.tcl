# ATK Navigator Z20 GE_PL: GEM1/EMIO -> AMD GMII2RGMII -> YT8531 (addr 4).
# Run after GT911 and planner clock modifications, before synthesis.
if {[llength $argv]!=1} {error "Argument: tcb705_md0700r.xpr"}
set here [file dirname [file normalize [info script]]]
open_project [lindex $argv 0]
open_bd_design [get_files */system.bd]
set ps [get_bd_cells processing_system7_0]
if {[llength [get_bd_cells -quiet ge_pl_bridge]]} {error "GE_PL already configured"}
set_property -dict [list CONFIG.PCW_ENET1_PERIPHERAL_ENABLE 1 \
 CONFIG.PCW_ENET1_ENET1_IO EMIO CONFIG.PCW_ENET1_GRP_MDIO_ENABLE 1 \
 CONFIG.PCW_ENET1_GRP_MDIO_IO EMIO CONFIG.PCW_FPGA_FCLK2_ENABLE 1 \
 CONFIG.PCW_EN_CLK2_PORT 1 CONFIG.PCW_EN_RST2_PORT 1 \
 CONFIG.PCW_FCLK2_PERIPHERAL_CLKSRC {IO PLL} CONFIG.PCW_FPGA2_PERIPHERAL_FREQMHZ 200] $ps
set bridge [create_bd_cell -type ip -vlnv xilinx.com:ip:gmii_to_rgmii:4.1 ge_pl_bridge]
# The board PHY strap supplies TX skew. Do not add another 2 ns in the FPGA.
set_property -dict [list CONFIG.C_PHYADDR 8 CONFIG.SupportLevel Include_Shared_Logic_in_Core \
 CONFIG.C_EXTERNAL_CLOCK false CONFIG.C_USE_IDELAY_CTRL true CONFIG.RGMII_TXC_SKEW 0] $bridge
connect_bd_intf_net [get_bd_intf_pins $ps/GMII_ETHERNET_1] [get_bd_intf_pins $bridge/GMII]
connect_bd_intf_net [get_bd_intf_pins $ps/MDIO_ETHERNET_1] [get_bd_intf_pins $bridge/MDIO_GEM]
make_bd_intf_pins_external [get_bd_intf_pins $bridge/MDIO_PHY]
set_property name ge_pl_mdio [get_bd_intf_ports MDIO_PHY_0]
make_bd_intf_pins_external [get_bd_intf_pins $bridge/RGMII]
set_property name ge_pl_rgmii [get_bd_intf_ports RGMII_0]
connect_bd_net [get_bd_pins $ps/FCLK_CLK2] [get_bd_pins $bridge/clkin]
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ge_pl]
set_property -dict [list CONFIG.C_EXT_RESET_HIGH 0 CONFIG.C_AUX_RESET_HIGH 1] $rst
connect_bd_net [get_bd_pins $ps/FCLK_CLK2] [get_bd_pins $rst/slowest_sync_clk]
connect_bd_net [get_bd_pins $ps/FCLK_RESET2_N] [get_bd_pins $rst/ext_reset_in]
# tx_reset also resets the bridge's internal MMCM. Waiting for that MMCM's
# locked output here would create a permanent reset/lock circular dependency.
# FCLK2 comes from the already running PS IO PLL; the IP handles its own lock.
connect_bd_net [get_bd_pins tcb_const_one/dout] [get_bd_pins $rst/dcm_locked]
connect_bd_net [get_bd_pins tcb_const_zero/dout] [get_bd_pins $rst/aux_reset_in] [get_bd_pins $rst/mb_debug_sys_rst] [get_bd_pins $ps/ENET1_EXT_INTIN]
connect_bd_net [get_bd_pins $rst/peripheral_reset] [get_bd_pins $bridge/tx_reset] [get_bd_pins $bridge/rx_reset]
# GT911 is implemented by touch_pl; PS EMIO GPIO 0/1 are no longer connected.
# Use GPIO 54 (EMIO 0) for the external PHY reset, driven by Linux.
set slice [create_bd_cell -type ip -vlnv xilinx.com:ip:xlslice:1.0 ge_pl_reset_slice]
set_property -dict [list CONFIG.DIN_WIDTH 2 CONFIG.DIN_FROM 0 CONFIG.DIN_TO 0 CONFIG.DOUT_WIDTH 1] $slice
connect_bd_net [get_bd_pins $ps/GPIO_O] [get_bd_pins $slice/Din]
create_bd_port -dir O ge_pl_phy_reset_n
connect_bd_net [get_bd_pins $slice/Dout] [get_bd_ports ge_pl_phy_reset_n]
add_files -fileset constrs_1 "$here/pins.xdc"
add_files -fileset constrs_1 "$here/timing.xdc"
set_property PROCESSING_ORDER EARLY [get_files "$here/timing.xdc"]
validate_bd_design
save_bd_design
generate_target all [get_files */system.bd]
set wrappers [get_files -quiet *system_wrapper.v]
if {[llength $wrappers]} {remove_files $wrappers}
add_files [make_wrapper -files [get_files */system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_bd_tcl -force "[get_property DIRECTORY [current_project]]/recreate_ge_pl_bd.tcl"
puts "GE_PL_CONFIGURED_PHY4_BRIDGE8_GPIO54_FCLK2_200MHZ"
close_project
