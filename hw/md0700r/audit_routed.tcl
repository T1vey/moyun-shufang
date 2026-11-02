if {[llength $argv]!=1} {error "Argument: fused_project.xpr"}
open_project [lindex $argv 0]
open_run impl_1
set output [get_property DIRECTORY [current_project]]
report_bus_skew -file "$output/export/bus_skew.rpt" -warn_on_violation
report_methodology -file "$output/export/methodology.rpt"
close_project
