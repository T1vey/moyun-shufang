# PS FCLK and dynamically programmed LCD clock cross only through vendor AXI CDC.
set_clock_groups -asynchronous -group [get_clocks clk_fpga_0] -group [get_clocks -of_objects [get_pins system_i/clk_wiz_0/inst/CLK_CORE_DRP_I/clk_inst/mmcm_adv_inst/CLKOUT0]]
