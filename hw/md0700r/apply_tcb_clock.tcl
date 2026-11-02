# Give only the seven-axis core/HP1 an independent PS FCLK1 (1000/13 MHz).
# LCD, GT911, their resets and GP0 stay at the verified original frequencies.
if {[llength $argv]!=1} {error "Argument: tcb705_md0700r.xpr"}
open_project [lindex $argv 0]
open_bd_design [get_files */system.bd]
set ps [get_bd_cells processing_system7_0]
if {[llength [get_bd_cells -quiet rst_tcb_planner]]} {error "Seven-axis clock domain already configured"}
set_property -dict [list CONFIG.PCW_FPGA_FCLK1_ENABLE {1} CONFIG.PCW_EN_CLK1_PORT {1} CONFIG.PCW_EN_RST1_PORT {1} CONFIG.PCW_FCLK1_PERIPHERAL_CLKSRC {IO PLL} CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {76.923077}] $ps
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_tcb_planner]
set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0} CONFIG.C_AUX_RESET_HIGH {1}] $reset
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 tcb_const_one]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $one
set zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 tcb_const_zero]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] $zero
connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $reset/slowest_sync_clk]
connect_bd_net [get_bd_pins $ps/FCLK_RESET1_N] [get_bd_pins $reset/ext_reset_in]
connect_bd_net [get_bd_pins $one/dout] [get_bd_pins $reset/dcm_locked]
connect_bd_net [get_bd_pins $zero/dout] [get_bd_pins $reset/aux_reset_in] [get_bd_pins $reset/mb_debug_sys_rst]
foreach name {tcb_planner_accel_0/ap_clk ps7_0_axi_periph/M06_ACLK processing_system7_0/S_AXI_HP1_ACLK planner_ddr/ACLK planner_ddr/S00_ACLK planner_ddr/M00_ACLK} {
    set pin [get_bd_pins $name]
    disconnect_bd_net [get_bd_nets -of_objects $pin] $pin
    connect_bd_net [get_bd_pins $ps/FCLK_CLK1] $pin
}
foreach name {tcb_planner_accel_0/ap_rst_n ps7_0_axi_periph/M06_ARESETN planner_ddr/ARESETN planner_ddr/S00_ARESETN planner_ddr/M00_ARESETN} {
    set pin [get_bd_pins $name]
    disconnect_bd_net [get_bd_nets -of_objects $pin] $pin
    connect_bd_net [get_bd_pins $reset/peripheral_aresetn] $pin
}
validate_bd_design
set rate [get_property CONFIG.FREQ_HZ [get_bd_pins $ps/FCLK_CLK1]]
if {$rate<75000000 || $rate>80000000} {error "Unexpected planner FCLK1 rate: $rate"}
puts "TCB_PLANNER_CLOCK_HZ=$rate"
save_bd_design
generate_target all [get_files */system.bd]
set wrappers [get_files -quiet *system_wrapper.v]
if {[llength $wrappers]} {remove_files $wrappers}
add_files [make_wrapper -files [get_files */system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
reset_run synth_1
close_project
