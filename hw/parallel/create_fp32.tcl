# Fresh complete platform: FP32 7R IK + LCD + GT911 + GE_PL + vision.
# Original verified project and its exported artifacts are never modified.
# args: project_root packaged_fp32_ip fresh_output_directory
if {[llength $argv] < 3 || [llength $argv] > 4} {error "project_root fp32_ip_repo fresh_output ?audio?"}
lassign $argv root planner_ip output feature
set with_audio [expr {$feature eq "audio"}]
set root [file normalize $root]
set output [file normalize $output]
if {[file exists "$output/tcb705_parallel_fp32.xpr"]} {error "Refusing to overwrite an existing project"}
create_project tcb705_parallel_fp32 $output -part xc7z020clg400-2
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list "$root/hw/vendor/md0700r/ip_repo" \
    "$root/hw/ip/tcb7_v2c" "$root/hw/ip/vision" $planner_ip] [current_project]
update_ip_catalog
add_files -norecurse [glob "$root/hw/md0700r/gt911_pl/rtl/*.v"]
if {$with_audio} {add_files -norecurse "$root/hw/audio/rtl/audio_out.v"}
update_compile_order -fileset sources_1
# Recreate the verified full peripheral platform before replacing only its IK IP.
source "$root/hw/vision/baseline/recreate_vision_bd.tcl"
open_bd_design [get_files */system.bd]
set ps [get_bd_cells processing_system7_0]
delete_bd_objs [get_bd_cells tcb_planner_accel_0]
set core [create_bd_cell -type ip -vlnv xilinx.com:hls:tcb_planner_parallel:1.0 tcb_planner_parallel_0]
set_property -dict [list CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ 100.0 \
    CONFIG.PCW_FCLK1_PERIPHERAL_CLKSRC {IO PLL} \
    CONFIG.PCW_USE_S_AXI_HP3 1 CONFIG.PCW_S_AXI_HP3_DATA_WIDTH 64] $ps
set reads [get_bd_cells planner_ddr]
set_property CONFIG.NUM_SI 2 $reads
set writes [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 planner_output_ddr]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 1] $writes
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M06_AXI] [get_bd_intf_pins $core/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins $core/m_axi_gmem_control] [get_bd_intf_pins $reads/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $core/m_axi_gmem_input] [get_bd_intf_pins $reads/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins $core/m_axi_gmem_output] [get_bd_intf_pins $writes/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $writes/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP3]
connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $core/ap_clk] \
    [get_bd_pins $reads/S01_ACLK] [get_bd_pins $writes/ACLK] \
    [get_bd_pins $writes/S00_ACLK] [get_bd_pins $writes/M00_ACLK] \
    [get_bd_pins $ps/S_AXI_HP3_ACLK]
connect_bd_net [get_bd_pins rst_tcb_planner/peripheral_aresetn] [get_bd_pins $core/ap_rst_n] \
    [get_bd_pins $reads/S01_ARESETN] [get_bd_pins $writes/ARESETN] \
    [get_bd_pins $writes/S00_ARESETN] [get_bd_pins $writes/M00_ARESETN]
assign_bd_address -offset 0x40000000 -range 64K \
    -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $core/s_axi_control/Reg] -force
foreach name {gmem_control gmem_input} {
    assign_bd_address -offset 0 -range 0x40000000 \
        -target_address_space [get_bd_addr_spaces $core/Data_m_axi_$name] \
        [get_bd_addr_segs $ps/S_AXI_HP1/HP1_DDR_LOWOCM] -force
}
assign_bd_address -offset 0 -range 0x40000000 \
    -target_address_space [get_bd_addr_spaces $core/Data_m_axi_gmem_output] \
    [get_bd_addr_segs $ps/S_AXI_HP3/HP3_DDR_LOWOCM] -force
if {$with_audio} {source "$root/hw/audio/add_audio_to_bd.tcl"}
validate_bd_design
save_bd_design
write_bd_tcl -force "$output/recreate_parallel_fp32_bd.tcl"
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
set fp [open "$output/accelerator_mode.txt" w];puts $fp planner_fp32;close $fp
close_project
puts "FP32_PLATFORM_CREATED $output/tcb705_parallel_fp32.xpr"
