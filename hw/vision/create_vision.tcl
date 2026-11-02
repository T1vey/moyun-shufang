# Build the vision platform from the verified V2C GE_PL BD (never mutates it):
# seven-axis planner + MD0700R + GT911 + GE_PL + tcb_brush_recog_0 (HLS, HP2).
# The lineart core is not included (LUT budget); stroke thinning falls back to the CPU.
# The camera is a USB/UVC device on the PS; frames reach the PL through DDR.
# args: project_root packaged_vision_ip output_directory
if {[llength $argv]!=3} {error "project_root vision_ip_repo fresh_output"}
lassign $argv root vision_ip output
set root [file normalize $root]
set output [file normalize $output]
if {[file exists "$output/tcb705_vision.xpr"]} {error "Refusing to overwrite existing vision project"}
create_project tcb705_vision $output -part xc7z020clg400-2
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list "$root/hw/vendor/md0700r/ip_repo" "$root/hw/ip/tcb7_v2c" $vision_ip] [current_project]
update_ip_catalog
add_files -norecurse [glob "$root/hw/md0700r/gt911_pl/rtl/*.v"]
update_compile_order -fileset sources_1
source "$root/hw/lineart/baseline/recreate_ge_pl_bd.tcl"
open_bd_design [get_files */system.bd]
set ps [get_bd_cells processing_system7_0]
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP2 1 CONFIG.PCW_S_AXI_HP2_DATA_WIDTH 64] $ps
set control [get_bd_cells ps7_0_axi_periph]
set index [get_property CONFIG.NUM_MI $control]
set_property CONFIG.NUM_MI [expr {$index+1}] $control
set rec_port [format M%02d $index]
set rec [create_bd_cell -type ip -vlnv xilinx.com:hls:tcb_brush_recog:1.0 tcb_brush_recog_0]
set mem [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 vision_ddr]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 1] $mem
connect_bd_intf_net [get_bd_intf_pins $control/${rec_port}_AXI] [get_bd_intf_pins $rec/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins $rec/m_axi_gmem] [get_bd_intf_pins $mem/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $mem/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP2]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $rec/ap_clk] \
 [get_bd_pins $control/${rec_port}_ACLK] [get_bd_pins $ps/S_AXI_HP2_ACLK] \
 [get_bd_pins $mem/ACLK] [get_bd_pins $mem/S00_ACLK] [get_bd_pins $mem/M00_ACLK]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins $rec/ap_rst_n] \
 [get_bd_pins $control/${rec_port}_ARESETN] \
 [get_bd_pins $mem/ARESETN] [get_bd_pins $mem/S00_ARESETN] [get_bd_pins $mem/M00_ARESETN]
assign_bd_address
foreach {cell offset range} [list tcb_brush_recog_0 0x40040000 64K] {
    set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces $ps/Data] -filter "NAME =~ *${cell}*"]
    if {[llength $seg]!=1} {error "ambiguous $cell control address"}
    set_property offset $offset $seg
    set_property range $range $seg
}
validate_bd_design
save_bd_design
write_bd_tcl -force "$output/recreate_vision_bd.tcl"
foreach xdc [list "$root/hw/lineart/baseline/lcd_pins.xdc" "$root/hw/md0700r/touch_pins.xdc" \
 "$root/hw/md0700r/display_timing.xdc" "$root/hw/md0700r/gt911_pl/touch_clock.xdc" \
 "$root/hw/ge_pl/pins.xdc" "$root/hw/ge_pl/timing.xdc"] {
    add_files -fileset constrs_1 $xdc
}
set_property PROCESSING_ORDER EARLY [get_files "$root/hw/ge_pl/timing.xdc"]
generate_target all [get_files */system.bd]
add_files -norecurse [make_wrapper -files [get_files */system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
set fp [open "$output/accelerator_mode.txt" w];puts $fp planner;close $fp
close_project
puts "VISION_PROJECT_READY $output/tcb705_vision.xpr"
