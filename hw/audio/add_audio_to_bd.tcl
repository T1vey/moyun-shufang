# Extend the already-created FP32 platform. No legacy planner replacement here.
if {[llength [get_bd_cells -quiet tcb_planner_parallel_0]] != 1 ||
    [llength [get_bd_cells -quiet tcb_planner_accel_0]] != 0} {
    error "Audio requires the existing FP32 IK platform"
}
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
assign_bd_address -offset 0x40060000 -range 64K \
    -target_address_space [get_bd_addr_spaces $ps/Data] \
    [get_bd_addr_segs $aud/s_axi/reg0] -force
add_files -fileset constrs_1 "$root/hw/audio/audio_pins.xdc"
