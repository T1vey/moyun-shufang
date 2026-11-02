`timescale 1ns/1ps
// Actual proc_sys_reset + bridge startup/restart topology; no external PHY model.
module tb_ge_pl_reset;
  reg refclk=0, rxc=0, ps_resetn=0;
  always #2.5 refclk=~refclk;
  always #4 rxc=~rxc;
  wire reset, locked;
  system_rst_ge_pl_0 resetter (
    .slowest_sync_clk(refclk), .ext_reset_in(ps_resetn), .aux_reset_in(1'b0),
    .mb_debug_sys_rst(1'b0), .dcm_locked(1'b1), .peripheral_reset(reset));
  ge_pl_bridge bridge (
    .clkin(refclk), .tx_reset(reset), .rx_reset(reset), .mmcm_locked_out(locked),
    .rgmii_rxc(rxc), .rgmii_rxd(4'b0), .rgmii_rx_ctl(1'b0),
    .gmii_txd(8'b0), .gmii_tx_en(1'b0), .gmii_tx_er(1'b0),
    .mdio_gem_mdc(1'b0), .mdio_gem_o(1'b1), .mdio_gem_t(1'b1), .mdio_phy_i(1'b1));
  initial begin
    #1000;
    if (reset !== 1'b1) $fatal(1,"reset was not asserted");
    ps_resetn=1;
    #50000;
    if (reset !== 1'b0 || locked !== 1'b1) $fatal(1,"bridge startup stuck in reset");
    ps_resetn=0;
    #1000;
    if (reset !== 1'b1 || locked !== 1'b0) $fatal(1,"reset did not reach the MMCM");
    ps_resetn=1;
    #50000;
    if (reset !== 1'b0 || locked !== 1'b1) $fatal(1,"bridge failed to relock");
    $display("GE_PL_RESET_STARTUP_AND_RELOCK_PASS");
    $finish;
  end
endmodule
