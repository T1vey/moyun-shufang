# Repair the auxiliary-reset polarity in an already generated seven-axis BD.
if {[llength $argv]!=1} {error "Argument: tcb705_md0700r.xpr"}
open_project [lindex $argv 0]
open_bd_design [get_files */system.bd]
set_property CONFIG.C_AUX_RESET_HIGH {1} [get_bd_cells rst_tcb_planner]
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells rst_tcb_planner]]!=0} {error "PS reset must be active low"}
if {[get_property CONFIG.C_AUX_RESET_HIGH [get_bd_cells rst_tcb_planner]]!=1} {error "Auxiliary zero must be inactive"}
validate_bd_design
save_bd_design
generate_target all [get_files */system.bd]
update_compile_order -fileset sources_1
reset_run synth_1
close_project
