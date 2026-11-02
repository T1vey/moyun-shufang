`timescale 1ns/1ps
// OV7725 SCCB writer: power-on register table (VGA RGB565, values from the
// ATK Z20 ov7725 example) followed by optional single writes from software.
// Three-phase write only; the ninth bit of each byte is released and sampled
// so a missing camera shows up as NACKs.
module brush_sccb #(
    parameter integer CLK_HZ = 100000000,
    parameter integer SCL_HZ = 100000,
    parameter integer BOOT_DELAY = 200000,   // clocks before the first write (2 ms)
    parameter integer RESET_DELAY = 300000   // clocks after COM7 reset (3 ms)
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        restart,     // rerun the whole table
    input  wire        user_req,    // one-cycle request; ignored while busy
    input  wire [15:0] user_data,   // {register, value}
    output reg         init_done,
    output wire        busy,
    output reg  [7:0]  nack_count,
    output reg         scl,
    output reg         sda_o,
    output reg         sda_oe,
    input  wire        sda_i
);
localparam integer QDIV = CLK_HZ / (SCL_HZ * 4);
localparam integer REG_NUM = 70;

function [15:0] rom;
    input [6:0] i;
    begin
        case (i)
        7'd0 : rom = 16'h1280; 7'd1 : rom = 16'h3d03; 7'd2 : rom = 16'h1500; 7'd3 : rom = 16'h1723;
        7'd4 : rom = 16'h18a0; 7'd5 : rom = 16'h1907; 7'd6 : rom = 16'h1af0; 7'd7 : rom = 16'h3200;
        7'd8 : rom = 16'h29a0; 7'd9 : rom = 16'h2a00; 7'd10: rom = 16'h2b00; 7'd11: rom = 16'h2cf0;
        7'd12: rom = 16'h0d41; 7'd13: rom = 16'h1100; 7'd14: rom = 16'h1206; 7'd15: rom = 16'h0c10;
        7'd16: rom = 16'h427f; 7'd17: rom = 16'h4d09; 7'd18: rom = 16'h63f0; 7'd19: rom = 16'h64ff;
        7'd20: rom = 16'h6500; 7'd21: rom = 16'h6600; 7'd22: rom = 16'h6700; 7'd23: rom = 16'h13ff;
        7'd24: rom = 16'h0fc5; 7'd25: rom = 16'h1411; 7'd26: rom = 16'h2298; 7'd27: rom = 16'h2303;
        7'd28: rom = 16'h2440; 7'd29: rom = 16'h2530; 7'd30: rom = 16'h26a1; 7'd31: rom = 16'h6baa;
        7'd32: rom = 16'h13ff; 7'd33: rom = 16'h900a; 7'd34: rom = 16'h9101; 7'd35: rom = 16'h9201;
        7'd36: rom = 16'h9301; 7'd37: rom = 16'h945f; 7'd38: rom = 16'h9553; 7'd39: rom = 16'h9611;
        7'd40: rom = 16'h971a; 7'd41: rom = 16'h983d; 7'd42: rom = 16'h995a; 7'd43: rom = 16'h9a1e;
        7'd44: rom = 16'h9b3f; 7'd45: rom = 16'h9c25; 7'd46: rom = 16'h9e81; 7'd47: rom = 16'ha606;
        7'd48: rom = 16'ha765; 7'd49: rom = 16'ha865; 7'd50: rom = 16'ha980; 7'd51: rom = 16'haa80;
        7'd52: rom = 16'h7e0c; 7'd53: rom = 16'h7f16; 7'd54: rom = 16'h802a; 7'd55: rom = 16'h814e;
        7'd56: rom = 16'h8261; 7'd57: rom = 16'h836f; 7'd58: rom = 16'h847b; 7'd59: rom = 16'h8586;
        7'd60: rom = 16'h868e; 7'd61: rom = 16'h8797; 7'd62: rom = 16'h88a4; 7'd63: rom = 16'h89af;
        7'd64: rom = 16'h8ac5; 7'd65: rom = 16'h8bd7; 7'd66: rom = 16'h8ce8; 7'd67: rom = 16'h8d20;
        7'd68: rom = 16'h0e65; 7'd69: rom = 16'h0900;
        default: rom = 16'h1c7f;
        endcase
    end
endfunction

localparam S_WAIT = 2'd0, S_XFER = 2'd1, S_IDLE = 2'd2;
reg [1:0]  state;
reg [31:0] wait_cnt;
reg [6:0]  idx;
reg        from_user;
reg [23:0] tx;
reg [15:0] qcnt;
reg [1:0]  q;          // quarter within the current segment
reg [4:0]  seg;        // 0 start, 1..27 bits, 28 stop
reg [3:0]  bitpos;     // 0..8 within a byte (8 = ack)
reg [1:0]  bytei;
reg        ack_bad;

assign busy = (state != S_IDLE);

wire tick = (qcnt == QDIV - 1);

always @(posedge clk) begin
    if (rst || restart) begin
        state <= S_WAIT; wait_cnt <= BOOT_DELAY; idx <= 7'd0; init_done <= 1'b0;
        scl <= 1'b1; sda_o <= 1'b1; sda_oe <= 1'b1; qcnt <= 16'd0; from_user <= 1'b0;
        if (rst) nack_count <= 8'd0;
    end else begin
        case (state)
        S_WAIT: begin
            scl <= 1'b1; sda_o <= 1'b1; sda_oe <= 1'b1;
            if (wait_cnt != 0) wait_cnt <= wait_cnt - 1;
            else begin
                tx <= {8'h42, rom(idx)}; from_user <= 1'b0;
                state <= S_XFER; qcnt <= 16'd0; q <= 2'd0; seg <= 5'd0; bitpos <= 4'd0; bytei <= 2'd0;
            end
        end
        S_IDLE: begin
            scl <= 1'b1; sda_o <= 1'b1; sda_oe <= 1'b1;
            if (user_req) begin
                tx <= {8'h42, user_data}; from_user <= 1'b1;
                state <= S_XFER; qcnt <= 16'd0; q <= 2'd0; seg <= 5'd0; bitpos <= 4'd0; bytei <= 2'd0;
            end
        end
        S_XFER: begin
            qcnt <= tick ? 16'd0 : qcnt + 16'd1;
            // Drive lines for the current quarter.
            if (seg == 5'd0) begin                       // START: SDA falls while SCL high
                sda_oe <= 1'b1;
                case (q) 2'd0: begin scl <= 1'b1; sda_o <= 1'b1; end
                         2'd1: begin scl <= 1'b1; sda_o <= 1'b0; end
                         default: begin scl <= 1'b0; sda_o <= 1'b0; end endcase
            end else if (seg == 5'd28) begin             // STOP: SDA rises while SCL high
                sda_oe <= 1'b1;
                case (q) 2'd0: begin scl <= 1'b0; sda_o <= 1'b0; end
                         2'd1: begin scl <= 1'b1; sda_o <= 1'b0; end
                         default: begin scl <= 1'b1; sda_o <= 1'b1; end endcase
            end else begin
                scl <= (q == 2'd1) || (q == 2'd2);
                if (bitpos == 4'd8) sda_oe <= 1'b0;      // release for don't-care/ack
                else begin sda_oe <= 1'b1; sda_o <= tx[23]; end
            end
            if (tick) begin
                if (seg != 5'd0 && seg != 5'd28 && bitpos == 4'd8 && q == 2'd2)
                    ack_bad <= sda_i;
                q <= q + 2'd1;
                if (q == 2'd3) begin
                    if (seg != 5'd0 && seg != 5'd28) begin
                        if (bitpos == 4'd8) begin
                            bitpos <= 4'd0; bytei <= bytei + 2'd1;
                            if (ack_bad && nack_count != 8'hff) nack_count <= nack_count + 8'd1;
                        end else begin
                            bitpos <= bitpos + 4'd1; tx <= {tx[22:0], 1'b0};
                        end
                    end
                    if (seg == 5'd28) begin
                        if (from_user) state <= S_IDLE;
                        else if (idx == REG_NUM - 1) begin state <= S_IDLE; init_done <= 1'b1; end
                        else begin
                            idx <= idx + 7'd1; state <= S_WAIT;
                            wait_cnt <= (idx == 7'd0) ? RESET_DELAY : 32'd2000;
                        end
                    end else seg <= seg + 5'd1;
                end
            end
        end
        default: state <= S_IDLE;
        endcase
    end
end
endmodule
