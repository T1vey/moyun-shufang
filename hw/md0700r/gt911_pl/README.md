# GT911 touch integration

Target: Navigator Zynq-7020, MD0700R (1024 x 600), PYNQ 2.7.

The RTL derives from the vendor `28_top_lcd_touch` example. It fixes the controller selection to GT911 at 7-bit address 0x14, reads the coordinate bytes before clearing register 0x814e, and waits for `i2c_done` after the final read byte before issuing the clear write. A regression reproduced the missing-STOP-wait failure; the corrected standalone design passed repeated presses and sliding on the physical panel.

The BD module must explicitly instantiate IOBUF for SDA and INT. The initial inferred tri-state version was converted to ordinary logic during OOC synthesis (`Synth 8-5799`), leaving OBUF-only pads and no returning touch data. Verify SDA has both IBUF and OBUFT in the routed design; verify INT retains OBUFT for address-selection release. Do not accept bit generation alone as proof of working pin connectivity.

For the production display/IK project, the driver runs from FCLK0 at 100 MHz. The I2C driver clock is 500 kHz (generated-clock period 2000 ns); the vendor `I2C_FREQ` parameter is 250000. Pins retain the board constraints: SCL R19, SDA P20, INT U19, RESET M19.

Apply `apply_gt911_pl.tcl` once to a freshly created r4 project, then run the parent `build_fused.tcl`. This replaces the PS external touch interfaces with the PL engine and changes `rest_gpio` to dual channel. Existing display reset outputs and IK addresses are unchanged.

Read the 32-bit packet at 0x41220008:

| Bits | Meaning |
| --- | --- |
| 31:22 | Sequence number, wraps at 1024 |
| 21 | Contact pressed |
| 20 | Packet valid |
| 19:10 | X pixel coordinate |
| 9:0 | Y pixel coordinate |

The software polls every 10 ms and forwards new packets as X11 pointer events on display :9. This supports one contact. `tb_touch_packet.v` checks two press/release cycles and command completion; `deploy/pynq-md0700r/test_gt911_input.py` checks pointer event transitions and stale-input release.

Verified build: `C:/fpga_build/so101_md0700r_touch_20261010/project/so101_md0700r_touch.xpr`. Exported artifacts are in `dist/md0700r_touch_hardware_20261010`. Timing: WNS 0.306 ns, WHS 0.026 ns, TNS/THS 0; no DRC errors. Existing display/IP methodology warnings remain, including clock redefinition and external I/O delay warnings.

Deployment must replace the bitstream, HWH, register map, artifact seal, package hashes, display expected hash, and input service expected hash together. Stop input/display/backend before reloading the overlay. The backend owns production overlay loading.
