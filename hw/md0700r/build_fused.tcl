if {[llength $argv]!=1} {error "Argument: fused_project.xpr"}
open_project [lindex $argv 0]
set output [get_property DIRECTORY [current_project]]
set project_name [get_property NAME [current_project]]
file mkdir "$output/export"
# Name artifacts from the real BD identity, never from a user-supplied filename.
open_bd_design [get_files system.bd]
set planner [get_bd_cells -quiet -filter {VLNV == xilinx.com:hls:tcb_planner_accel:1.0}]
set target [get_bd_cells -quiet -filter {VLNV == xilinx.com:hls:z20_ik_target:1.0}]
if {[llength $planner] == 1 && [llength $target] == 0} {
    set accelerator_mode planner
    set artifact_stem tcb705_planner
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
close_bd_design [current_bd_design]
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
open_run synth_1
set pixel_pin [get_pins system_i/clk_wiz_0/inst/CLK_CORE_DRP_I/clk_inst/mmcm_adv_inst/CLKOUT0]
set pixel_clock [get_clocks -of_objects $pixel_pin]
if {[llength $pixel_clock]!=1 || [llength [get_clocks clk_fpga_0]]!=1} {error "Missing display/PS clocks"}
if {[get_property PERIOD $pixel_clock]>19.532} {error "Pixel clock timing is slower than 1024x600 requirement"}
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
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
write_hw_platform -fixed -include_bit -force -file "$output/export/tcb705_md0700r.xsa"
file copy -force "$output/${project_name}.runs/impl_1/system_wrapper.bit" "$output/export/${artifact_stem}.bit"
file copy -force "$output/${project_name}.gen/sources_1/bd/system/hw_handoff/system.hwh" "$output/export/${artifact_stem}.hwh"
set identity [open "$output/export/accelerator_mode.txt" w]
puts $identity $accelerator_mode
close $identity
set verified [open "$output/export/build_verified.json" w]
puts $verified "{\"setup_slack_ns\": [get_property SLACK $setup], \"hold_slack_ns\": [get_property SLACK $hold], \"drc_errors\": [llength $drc_errors]}"
close $verified
puts "FUSED_BUILD_COMPLETE_NO_BOARD_PROGRAMMING"
close_project
