create_generated_clock -name gt911_i2c_driver -source [get_pins -hier -filter {NAME =~ */u_i2c_dri/dri_clk_reg/C}] -divide_by 200 [get_pins -hier -filter {NAME =~ */u_i2c_dri/dri_clk_reg/Q}]
