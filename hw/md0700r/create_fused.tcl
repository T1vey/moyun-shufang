# Vivado 2024.2: vendor Linux LCD pipeline + existing target IK, no programming.
# Arguments: vendor root, packaged IP, fresh output directory, optional target|planner.
if {[llength $argv] < 3 || [llength $argv] > 4} {error "vendor_root ik_ip_repo output_directory ?target|planner?"}
lassign $argv vendor ik_repo output
set accelerator_mode target
if {[llength $argv] == 4} {set accelerator_mode [lindex $argv 3]}
if {$accelerator_mode ni {target planner}} {error "Unsupported accelerator mode"}
set here [file dirname [file normalize [info script]]]
set output [file normalize $output]
if {[file exists "$output/tcb705_md0700r.xpr"]} {error "Use a new build directory; do not overwrite a project"}
create_project tcb705_md0700r $output -part xc7z020clg400-2
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list "$vendor/ip_repo" $ik_repo] [current_project]
update_ip_catalog
import_files -norecurse "$vendor/Navigator_7020.srcs/sources_1/bd/system/system.bd"
open_bd_design [get_files system.bd]
upgrade_ip [get_ips -all]
report_ip_status -file "$output/ip_status.rpt"
# Build timing at the 1024x600 pixel rate, not the vendor 800x480 default.
set_property -dict [list CONFIG.CLKOUT2_USED {false} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {51.2}] [get_bd_cells clk_wiz_0]
# Match reset-gpios=<rest_gpio 0 ... ACTIVE_LOW>; vendor slice default selected bit 2.
set_property -dict [list CONFIG.DIN_FROM {0} CONFIG.DIN_TO {0} CONFIG.DOUT_WIDTH {1}] [get_bd_cells lcd_out/xlslice_0]
set_property CONFIG.C_AUX_RESET_HIGH {0} [get_bd_cells lcd_out/proc_sys_reset_0]
set fb_reset [get_bd_pins lcd_out/v_frmbuf_rd_0/ap_rst_n]
disconnect_bd_net [get_bd_nets -of_objects $fb_reset] $fb_reset
connect_bd_net [get_bd_pins lcd_out/proc_sys_reset_0/peripheral_aresetn] $fb_reset
set ps [get_bd_cells processing_system7_0]
source "$here/../target_ik/ps7_board.tcl"
set_property -dict $so101_ps7_properties $ps
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} CONFIG.PCW_IRQ_F2P_INTR {1} \
    CONFIG.PCW_I2C1_PERIPHERAL_ENABLE {1} CONFIG.PCW_I2C1_I2C1_IO {EMIO} \
    CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE {1} CONFIG.PCW_GPIO_EMIO_GPIO_IO {2} \
    CONFIG.PCW_GPIO_MIO_GPIO_ENABLE {1}] $ps
if {$accelerator_mode eq "planner"} {
    set_property -dict [list CONFIG.PCW_USE_S_AXI_HP1 {1} CONFIG.PCW_S_AXI_HP1_DATA_WIDTH {64}] $ps
}
# Reapplying the arm PS preset recreates HP0 pins; restore vendor video links.
connect_bd_intf_net [get_bd_intf_pins lcd_out/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP0]
connect_bd_net [get_bd_pins clk_wiz_0/lcd_pclk] [get_bd_pins $ps/S_AXI_HP0_ACLK]
assign_bd_address
# EMIO GPIO 0/1 become Linux gpio0 offsets 54/55, dedicated to touch reset/IRQ.
make_bd_intf_pins_external [get_bd_intf_pins $ps/IIC_1]
set_property name i2c_touch [get_bd_intf_ports IIC_1_0]
make_bd_intf_pins_external [get_bd_intf_pins $ps/GPIO_0]
set_property name gpio_touch [get_bd_intf_ports GPIO_0_0]
set bus [get_bd_cells ps7_0_axi_periph]
set_property CONFIG.NUM_MI 7 $bus
if {$accelerator_mode eq "planner"} {
    set core [create_bd_cell -type ip -vlnv xilinx.com:hls:tcb_planner_accel:1.0 tcb_planner_accel_0]
} else {
    set core [create_bd_cell -type ip -vlnv xilinx.com:hls:z20_ik_target:1.0 z20_ik_target_0]
}
connect_bd_intf_net [get_bd_intf_pins $bus/M06_AXI] [get_bd_intf_pins $core/s_axi_control]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $bus/M06_ACLK] [get_bd_pins $core/ap_clk]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] \
    [get_bd_pins $bus/M06_ARESETN] [get_bd_pins $core/ap_rst_n]
if {$accelerator_mode eq "planner"} {
    # HP0 remains attached to the display pixel domain. Both HP ports share DDR.
    set memory_bus [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 planner_ddr]
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $memory_bus
    connect_bd_intf_net [get_bd_intf_pins $core/m_axi_gmem] [get_bd_intf_pins $memory_bus/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins $memory_bus/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP1]
    connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $ps/S_AXI_HP1_ACLK] \
        [get_bd_pins $memory_bus/ACLK] [get_bd_pins $memory_bus/S00_ACLK] [get_bd_pins $memory_bus/M00_ACLK]
    connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] \
        [get_bd_pins $memory_bus/ARESETN] [get_bd_pins $memory_bus/S00_ARESETN] [get_bd_pins $memory_bus/M00_ARESETN]
    assign_bd_address
}
assign_bd_address [get_bd_addr_segs $core/s_axi_control/Reg]
set core_name [file tail $core]
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces $ps/Data] -filter "NAME =~ *${core_name}*"]
if {[llength $seg] != 1} {error "Ambiguous accelerator control address"}
set_property offset 0x40000000 $seg
set_property range 64K $seg
validate_bd_design
save_bd_design
set identity [open "$output/accelerator_mode.txt" w]
puts $identity $accelerator_mode
close $identity
write_bd_tcl -force "$output/recreate_fused_bd.tcl"
generate_target all [get_files system.bd]
set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
# Copy only package pin assignments. Timing is separately reviewed below.
set input [open "$vendor/Navigator_7020.srcs/constrs_1/system.xdc" r]
set pins [open "$output/lcd_pins.xdc" w]
while {[gets $input line]>=0} {
    if {[string match "set_property -dict*PACKAGE_PIN*" $line]} {puts $pins $line}
}
close $input
close $pins
add_files -fileset constrs_1 "$output/lcd_pins.xdc"
add_files -fileset constrs_1 "$here/touch_pins.xdc"
add_files -fileset constrs_1 "$here/display_timing.xdc"
update_compile_order -fileset sources_1
puts "FUSED_PROJECT_READY $output/tcb705_md0700r.xpr"
close_project
