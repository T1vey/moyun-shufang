# Run only inside the directory prepared by scripts/10_r1a_hls.ps1.
set stage $::env(R1A_HLS_STAGE)
if {$stage ni {csim csynth cosim export}} { error "Unsupported stage" }
open_project -reset r1a_wls_project
set_top z20_wls_step
add_files wls_step.cpp
add_files wls_step.h
add_files -tb tb_wls_step.cpp
add_files -tb vectors.txt
open_solution -reset solution1 -flow_target vivado
set_part {xc7z020clg400-2}
create_clock -period 10 -name default
csim_design -clean
if {$stage in {csynth cosim export}} { csynth_design }
if {$stage in {cosim export}} { cosim_design -rtl verilog }
if {$stage eq "export"} { export_design -format ip_catalog -rtl verilog }
exit
