# Standalone internal-timing validation. This does not open a deployed platform,
# generate a system bitstream, establish AXI boundary timing or program hardware.
# Arguments are the already-copied generated RTL directory and fresh output.
if {[llength $argv] != 2} {error "Arguments: isolated_rtl_directory output_directory"}
lassign $argv rtl output
set rtl [file normalize $rtl]
set output [file normalize $output]
if {[regexp {[^\x00-\x7f]} $output]} {error "Output path must contain ASCII characters only"}
if {![file exists "$rtl/tcb_planner_parallel.v"]} {error "Missing synthesized HLS top"}
if {[file dirname $rtl] ne $output} {error "RTL must be copied into output/rtl before validation"}
if {[file exists "$output/project/parallel_ooc.xpr"]} {error "Refusing to overwrite an existing OOC project"}
set verilog [glob -nocomplain "$rtl/*.v"]
set ip_scripts [lsort [glob -nocomplain "$rtl/*_ip.tcl"]]
set data_files [glob -nocomplain "$rtl/*.dat"]
if {![llength $verilog] || ![llength $ip_scripts]} {error "Missing RTL or floating-point-IP generation scripts"}
foreach source $verilog {
    set stream [open $source r]
    set text [read $stream]
    close $stream
    foreach {whole filename} [regexp -all -inline {\$readmem[hb]\s*\(\s*"([^"]+)"} $text] {
        set memory [file normalize "$rtl/$filename"]
        if {![file exists $memory]} {error "Missing memory initialization file: $memory"}
        if {![string equal -length [expr {[string length $rtl]+1}] "$rtl/" "$memory/"]} {
            error "ROM dependency escapes copied RTL: $filename"
        }
    }
}
set_param general.maxThreads 4
create_project parallel_ooc "$output/project" -part xc7z020clg400-2
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
# Generated readmemh paths are relative to the copied RTL directory.
cd $rtl
foreach ip_script $ip_scripts {source $ip_script}
if {![llength [get_ips -quiet]]} {error "No floating-point IPs were created"}
add_files -norecurse $verilog
if {[llength $data_files]} {add_files -norecurse $data_files}
set_property top tcb_planner_parallel [current_fileset]
# Apply the requested clock during synthesis as well as implementation.
set clock_path "$output/core_100mhz.xdc"
set clock_file [open $clock_path w]
puts $clock_file {create_clock -name ap_clk -period 10.000 [get_ports ap_clk]}
puts $clock_file {set_clock_uncertainty 0.300 [get_clocks ap_clk]}
close $clock_file
add_files -fileset constrs_1 -norecurse $clock_path
update_compile_order -fileset sources_1
synth_design -top tcb_planner_parallel -part xc7z020clg400-2 -mode out_of_context
set clocks [get_ports -quiet ap_clk]
if {[llength $clocks] != 1} {error "Expected exactly one ap_clk port"}
if {[llength [get_clocks -quiet ap_clk]] != 1} {error "Synthesis did not retain the 100 MHz clock constraint"}
set black_boxes [get_cells -hierarchical -quiet -filter {IS_BLACKBOX == 1}]
report_utilization -file "$output/util_synth.rpt"
report_utilization -hierarchical -file "$output/util_synth_hierarchical.rpt"
if {[llength $black_boxes]} {
    set stream [open "$output/black_boxes.txt" w]
    puts $stream [join $black_boxes "\n"]
    close $stream
    error "Unresolved black boxes after synthesis: [llength $black_boxes]"
}
write_checkpoint -force "$output/synth.dcp"
opt_design
place_design
phys_opt_design
route_design
set black_boxes [get_cells -hierarchical -quiet -filter {IS_BLACKBOX == 1}]
report_utilization -file "$output/util_routed.rpt"
report_utilization -hierarchical -file "$output/util_routed_hierarchical.rpt"
report_timing_summary -report_unconstrained -file "$output/timing_routed.rpt" -warn_on_violation
report_drc -file "$output/drc.rpt"
check_timing -file "$output/check_timing.rpt"
report_clocks -file "$output/clocks.rpt"
write_checkpoint -force "$output/routed.dcp"
set setup [get_timing_paths -quiet -delay_type max -max_paths 1]
set hold [get_timing_paths -quiet -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "No constrained internal timing paths were reported"}
set setup_slack [get_property SLACK $setup]
set hold_slack [get_property SLACK $hold]
set drc_errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
set pass [expr {$setup_slack >= 0 && $hold_slack >= 0 && ![llength $black_boxes] && ![llength $drc_errors]}]
set status [expr {$pass ? "PASS" : "FAIL"}]
set receipt [open "$output/ooc_result.json" w]
puts $receipt "{\"schema\":\"tcb705-parallel-ooc-result-v1\",\"status\":\"$status\",\"clock_period_ns\":10.0,\"clock_uncertainty_ns\":0.3,\"setup_slack_ns\":$setup_slack,\"hold_slack_ns\":$hold_slack,\"black_boxes\":[llength $black_boxes],\"drc_errors\":[llength $drc_errors],\"boundary_timing_verified\":false,\"full_system_bitstream_built\":false,\"board_programmed\":false}"
close $receipt
close_project
if {!$pass} {error "Standalone core failed timing or DRC; inspect the routed reports"}
puts "OOC_INTERNAL_100MHZ_PASS_NO_SYSTEM_BITSTREAM_NO_BOARD_PROGRAMMING"
