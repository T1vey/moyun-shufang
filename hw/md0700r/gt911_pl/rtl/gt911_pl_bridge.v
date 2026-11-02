module gt911_pl_bridge(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME clk, ASSOCIATED_RESET resetn, FREQ_HZ 100000000" *)
    input wire clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME resetn, POLARITY ACTIVE_LOW" *)
    input wire resetn,
    inout wire [1:0] gpio_touch_tri_io,
    inout wire i2c_touch_sda_io,
    output wire i2c_touch_scl_io,
    output reg [31:0] packet
);
wire [31:0] raw_packet;
wire [31:0] coordinates;
wire [63:0] diagnostic;
wire [3:0] diagnostic_bus;
wire touch_reset;
assign gpio_touch_tri_io[0]=touch_reset;
touch_top u_touch(
    .clk(clk),.rst_n(resetn),.touch_rst_n(touch_reset),
    .touch_int(gpio_touch_tri_io[1]),.touch_scl(i2c_touch_scl_io),.touch_sda(i2c_touch_sda_io),
    .lcd_id(16'h7016),.data(coordinates),.touch_packet(raw_packet),
    .diagnostic(diagnostic),.diagnostic_bus(diagnostic_bus)
);
(* ASYNC_REG="TRUE" *) reg [31:0] sample1, sample2;
reg [31:0] last_sample;
always @(posedge clk) begin
    if(!resetn) begin sample1<=0;sample2<=0;last_sample<=0;packet<=0;end
    else begin
        sample1<=raw_packet;
        sample2<=sample1;
        last_sample<=sample2;
        if(sample2==last_sample) packet<=sample2;
    end
end
endmodule
