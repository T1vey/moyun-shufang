# Run once against an r4 display/IK project before synthesis.
if {[llength $argv]!=1} {error "Argument: fused_project.xpr"}
set touch_root [file dirname [file normalize [info script]]]
open_project [lindex $argv 0]
add_files [glob ${touch_root}/rtl/*.v]
add_files -fileset constrs_1 ${touch_root}/touch_clock.xdc
set_property USED_IN_SYNTHESIS false [get_files ${touch_root}/touch_clock.xdc]
open_bd_design [get_files */system.bd]
foreach name {gpio_touch i2c_touch} {
 set p [get_bd_intf_ports $name]
 delete_bd_objs [get_bd_intf_nets -of_objects $p]
 delete_bd_objs $p
}
set_property -dict [list CONFIG.C_IS_DUAL 1 CONFIG.C_GPIO2_WIDTH 32 CONFIG.C_ALL_INPUTS_2 1] [get_bd_cells rest_gpio]
create_bd_cell -type module -reference gt911_pl_bridge touch_pl
create_bd_port -dir IO -from 1 -to 0 gpio_touch_tri_io
create_bd_port -dir IO i2c_touch_sda_io
create_bd_port -dir O i2c_touch_scl_io
foreach name {gpio_touch_tri_io i2c_touch_sda_io i2c_touch_scl_io} {
 connect_bd_net [get_bd_ports $name] [get_bd_pins touch_pl/$name]
}
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins touch_pl/clk]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins touch_pl/resetn]
connect_bd_net [get_bd_pins touch_pl/packet] [get_bd_pins rest_gpio/gpio2_io_i]
validate_bd_design
save_bd_design
set bd [get_files */system.bd]
generate_target all $bd
set wrappers [get_files -quiet *system_wrapper.v]
if {[llength $wrappers]} {remove_files $wrappers}
add_files [make_wrapper -files $bd -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
close_project
