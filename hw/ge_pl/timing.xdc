# External PHY-sourced clock. Generated IP XDC supplies DDR input/output delays;
# its OOC-only clock does not constrain the top-level design.
create_clock -name ge_pl_rxc -period 8.000 [get_ports ge_pl_rgmii_rxc]
set_property SLEW FAST [get_ports {ge_pl_rgmii_td[*] ge_pl_rgmii_tx_ctl ge_pl_rgmii_txc}]
