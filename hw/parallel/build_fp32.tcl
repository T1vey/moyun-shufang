if {[llength $argv]!=1} {error "Argument: fused_project.xpr"}
open_project [lindex $argv 0]
set output [get_property DIRECTORY [current_project]]
set project_name [get_property NAME [current_project]]
file mkdir "$output/export"
# Name artifacts from the real BD identity, never from a user-supplied filename.
open_bd_design [get_files system.bd]
set planner [get_bd_cells -quiet -filter {VLNV == xilinx.com:hls:tcb_planner_parallel:1.0}]
set target [get_bd_cells -quiet -filter {VLNV == xilinx.com:hls:z20_ik_target:1.0}]
if {[llength $planner] == 1 && [llength $target] == 0} {
    set accelerator_mode planner_fp32
    set artifact_stem tcb705_planner_fp32
    set reset [get_bd_cells rst_tcb_planner]
    if {[get_property CONFIG.C_AUX_RESET_HIGH $reset]!=1 || [get_property CONFIG.C_EXT_RESET_HIGH $reset]!=0} {error "Seven-axis reset polarity is not valid"}
    set aux [get_bd_pins $reset/aux_reset_in]
    set zero [get_bd_pins tcb_const_zero/dout]
    if {[get_bd_nets -of_objects $aux] ne [get_bd_nets -of_objects $zero]} {error "Seven-axis auxiliary reset must be inactive"}
} elseif {[llength $target] == 1 && [llength $planner] == 0} {
    set accelerator_mode target
    set artifact_stem drawing_target
} else {error "Exactly one supported accelerator must be present in the BD"}
if {[file exists "$output/accelerator_mode.txt"]} {
    set identity [open "$output/accelerator_mode.txt" r]
    set declared_mode [string trim [read $identity]]
    close $identity
    if {$declared_mode ne $accelerator_mode} {error "Project accelerator identity mismatch"}
}
set fp32_clock [get_property CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ [get_bd_cells processing_system7_0]]
if {abs($fp32_clock-100.0)>0.001} {error "FP32 FCLK1 must be exactly 100 MHz"}
if {[get_property CONFIG.PCW_USE_S_AXI_HP3 [get_bd_cells processing_system7_0]] != 1} {error "FP32 output HP3 is disabled"}
close_bd_design [current_bd_design]
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%" || [get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "Synthesis failed"}
open_run synth_1
set ik_clock [get_clocks -of_objects [get_pins system_i/tcb_planner_parallel_0/inst/ap_clk]]
if {[llength $ik_clock]!=1 || abs([get_property PERIOD $ik_clock]-10.0)>0.001} {error "FP32 synthesized clock is not 100 MHz"}
set audio_clock_pin [get_pins -quiet system_i/audio_out_0/inst/s_axi_aclk]
if {[llength $audio_clock_pin]} {
    set audio_clock [get_clocks -of_objects $audio_clock_pin]
    if {[llength $audio_clock]!=1 || abs([get_property PERIOD $audio_clock]-10.0)>0.001} {error "Audio requires FCLK0 = 100 MHz"}
}
set pixel_pin [get_pins system_i/clk_wiz_0/inst/CLK_CORE_DRP_I/clk_inst/mmcm_adv_inst/CLKOUT0]
set pixel_clock [get_clocks -of_objects $pixel_pin]
if {[llength $pixel_clock]!=1 || [llength [get_clocks clk_fpga_0]]!=1} {error "Missing display/PS clocks"}
if {[get_property PERIOD $pixel_clock]>19.532} {error "Pixel clock timing is slower than 1024x600 requirement"}
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%" || [get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "Implementation failed"}
open_run impl_1
if {[llength [get_ports -quiet ge_pl_rgmii_rxc]]} {
    set rx_clocks [get_clocks -of_objects [get_ports ge_pl_rgmii_rxc]]
    if {[llength $rx_clocks]!=1 || [get_property PERIOD $rx_clocks]!=8} {
        error "GE_PL external RX clock is missing or not constrained at 125 MHz"
    }
    report_clocks -file "$output/export/clocks.rpt"
}
if {[llength [get_cells -hier -filter {REF_NAME == gt911_pl_bridge}]] || [llength [get_clocks -quiet gt911_i2c_driver]]} {
    foreach name {i2c_touch_sda_io {gpio_touch_tri_io[1]}} {
        set pad [get_ports $name]
        if {[llength $pad]!=1} {error "GT911 pad missing: $name"}
        set refs [get_property REF_NAME [get_cells -of_objects [get_pins -leaf -of_objects [get_nets -of_objects $pad]]]]
        if {[lsearch -exact $refs OBUFT]<0} {error "GT911 tri-state buffer missing: $name"}
        if {$name eq "i2c_touch_sda_io" && [lsearch -exact $refs IBUF]<0} {error "GT911 SDA input buffer missing"}
    }
    if {[get_property PERIOD [get_clocks gt911_i2c_driver]]!=2000} {error "GT911 clock period invalid"}
}
if {[llength [get_ports -quiet aud_sda]]} {
    # A module-reference OOC run can turn an inferred internal tri-state into
    # ordinary logic. Checking only pin locations or DRC Error misses that bug.
    set audio_pad [get_ports aud_sda]
    set audio_refs [get_property REF_NAME [get_cells -of_objects [get_pins -leaf -of_objects [get_nets -of_objects $audio_pad]]]]
    set has_iobuf [expr {[lsearch -exact $audio_refs IOBUF]>=0}]
    set has_split [expr {[lsearch -exact $audio_refs IBUF]>=0 && [lsearch -exact $audio_refs OBUFT]>=0}]
    if {!$has_iobuf && !$has_split} {error "Audio SDA real input and tri-state output buffers are missing: $audio_refs"}
    report_io -file "$output/export/io.rpt"
    set buf_report [open "$output/export/audio_iobuf_verified.txt" w]
    puts $buf_report "aud_sda F17 real pad buffers: $audio_refs"
    close $buf_report
}
write_checkpoint -force "$output/export/tcb705_parallel_fp32_routed.dcp"
report_timing_summary -file "$output/export/timing_summary.rpt" -warn_on_violation
report_utilization -file "$output/export/utilization.rpt"
report_utilization -hierarchical -file "$output/export/utilization_hierarchical.rpt"
report_drc -file "$output/export/drc.rpt"
report_cdc -details -file "$output/export/cdc.rpt"
report_bus_skew -file "$output/export/bus_skew.rpt" -warn_on_violation
check_timing -file "$output/export/check_timing.rpt"
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Timing paths missing"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing did not close"}
set drc_errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $drc_errors]} {error "Implementation contains DRC errors"}
write_hw_platform -fixed -include_bit -force -file "$output/export/tcb705_parallel_fp32.xsa"
file copy -force "$output/${project_name}.runs/impl_1/system_wrapper.bit" "$output/export/${artifact_stem}.bit"
file copy -force "$output/${project_name}.gen/sources_1/bd/system/hw_handoff/system.hwh" "$output/export/${artifact_stem}.hwh"
set identity [open "$output/export/accelerator_mode.txt" w]
puts $identity $accelerator_mode
close $identity
set verified [open "$output/export/build_verified.json" w]
puts $verified "{\"setup_slack_ns\": [get_property SLACK $setup], \"hold_slack_ns\": [get_property SLACK $hold], \"drc_errors\": [llength $drc_errors]}"
close $verified
puts "FP32_FULL_BUILD_COMPLETE_NO_BOARD_PROGRAMMING"
close_project
