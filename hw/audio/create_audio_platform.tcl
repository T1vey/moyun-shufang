# Build the audio platform from the deployed vision BD (hw/vision/baseline/recreate_vision_bd.tcl,
# never mutated): planner + MD0700R + GT911 + GE_PL + tcb_brush_recog_0 + audio_out_0.
# audio_out_0 (RTL module, 270 LUT OOC) drives the onboard WM8960 at 0x40060000 / 64 KiB,
# entirely in the FCLK0 domain (MCLK = FCLK0/8; the codec is the I2S master).
# args: project_root output_directory
error "Legacy audio platform uses the old 76.92 MHz planner. Use scripts/build_audio_fp32.ps1 for the 100 MHz FP32 platform."
if {[llength $argv]!=2} {error "project_root fresh_output"}
lassign $argv root output
set root [file normalize $root]
set output [file normalize $output]
if {[file exists "$output/tcb705_audio.xpr"]} {error "Refusing to overwrite existing audio project"}
create_project tcb705_audio $output -part xc7z020clg400-2
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list "$root/hw/vendor/md0700r/ip_repo" "$root/hw/ip/tcb7_v2c" "$root/hw/ip/vision"] [current_project]
update_ip_catalog
add_files -norecurse [glob "$root/hw/md0700r/gt911_pl/rtl/*.v"]
add_files -norecurse "$root/hw/audio/rtl/audio_out.v"
update_compile_order -fileset sources_1
source "$root/hw/vision/baseline/recreate_vision_bd.tcl"
open_bd_design [get_files */system.bd]
set ps [get_bd_cells processing_system7_0]
set control [get_bd_cells ps7_0_axi_periph]
set index [get_property CONFIG.NUM_MI $control]
set_property CONFIG.NUM_MI [expr {$index+1}] $control
set port [format M%02d $index]
set aud [create_bd_cell -type module -reference audio_out audio_out_0]
connect_bd_intf_net [get_bd_intf_pins $control/${port}_AXI] [get_bd_intf_pins $aud/s_axi]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $aud/s_axi_aclk] [get_bd_pins $control/${port}_ACLK]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins $aud/s_axi_aresetn] [get_bd_pins $control/${port}_ARESETN]
foreach {name dir} {aud_mclk O aud_bclk I aud_daclrc I aud_dacdat O aud_scl O aud_sda IO} {
    connect_bd_net [create_bd_port -dir $dir $name] [get_bd_pins $aud/$name]
}
assign_bd_address
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces $ps/Data] -filter {NAME =~ *audio_out_0*}]
if {[llength $seg]!=1} {error "ambiguous audio control address"}
set_property offset 0x40060000 $seg
set_property range 64K $seg
validate_bd_design
save_bd_design
write_bd_tcl -force "$output/recreate_audio_bd.tcl"
foreach xdc [list "$root/hw/lineart/baseline/lcd_pins.xdc" "$root/hw/md0700r/touch_pins.xdc" \
 "$root/hw/md0700r/display_timing.xdc" "$root/hw/md0700r/gt911_pl/touch_clock.xdc" \
 "$root/hw/ge_pl/pins.xdc" "$root/hw/ge_pl/timing.xdc" "$root/hw/audio/audio_pins.xdc"] {
    add_files -fileset constrs_1 $xdc
}
set_property PROCESSING_ORDER EARLY [get_files "$root/hw/ge_pl/timing.xdc"]
generate_target all [get_files */system.bd]
add_files -norecurse [make_wrapper -files [get_files */system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
set fp [open "$output/accelerator_mode.txt" w];puts $fp planner;close $fp
close_project
puts "AUDIO_PROJECT_READY $output/tcb705_audio.xpr"
