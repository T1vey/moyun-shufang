`timescale 1ns/1ps
// WM8960 playback path (tcb705-audio-v1), everything in the s_axi_aclk (FCLK0, 100 MHz) domain.
//   * MCLK = aclk / 8 = 12.5 MHz; the codec's PLL makes SYSCLK 12.288 MHz from it and the codec
//     is the I2S master (BCLK 1.536 MHz, DACLRC 48 kHz), so no clock enters the PL.
//   * BCLK/DACLRC are 2-FF sampled; DACLRC is read on BCLK rising edges, a new word is loaded
//     after a DACLRC change and shifted out MSB first on BCLK falling edges (I2S, 16 bit).
//   * Mono 16-bit FIFO; each word is sent to both channels; empty FIFO plays silence.
//   * A bare I2C writer sends {address, byte0, byte1}; the init sequence runs on the PS
//     (audio_player/codec.py).
// Registers (64 KiB): 0x00 ID 'AUD1', 0x04 VERSION, 0x08 CTRL, 0x0C STATUS, 0x10 I2C,
// 0x14 UNDERRUN, 0x18 FRAMES, 0x1C DEPTH, 0x20 OVERFLOW, 0x24 I2C_DONE_COUNT,
// 0x28 CAPS=3 (bus diagnostics + address-only probe). I2C command bit24 requests
// address+W+ACK+STOP only; otherwise the original three-byte write is unchanged.
// STATUS bit19 is SDA input, bit20 is BUS_STUCK. Writes to 0x1000-0x1FFF push two
// samples (low half first).
module audio_out #(
    parameter integer AW = 14,                 // FIFO depth = 2^AW samples
    parameter integer I2C_QDIV = 250           // aclk cycles per I2C quarter bit (100 kHz)
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire        s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire        s_axi_aresetn,
    input  wire [15:0] s_axi_awaddr,
    input  wire [2:0]  s_axi_awprot,
    input  wire        s_axi_awvalid,
    output reg         s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output reg         s_axi_wready,
    output wire [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [15:0] s_axi_araddr,
    input  wire [2:0]  s_axi_arprot,
    input  wire        s_axi_arvalid,
    output reg         s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,
    output reg         aud_mclk,
    input  wire        aud_bclk,
    input  wire        aud_daclrc,
    output reg         aud_dacdat,
    output reg         aud_scl,
    inout  wire        aud_sda
);
localparam [31:0] ID = 32'h41554431, VERSION = 32'h20261027;
localparam integer DEPTH = 1 << AW;
wire clk = s_axi_aclk;
wire rst = ~s_axi_aresetn;
assign s_axi_bresp = 2'b00;
assign s_axi_rresp = 2'b00;

// ------------------------------------------------------------------ registers
reg        en, mute, mclk_en;
reg [31:0] underruns, frames, overflows;
reg        clear_req, clear_pend;
reg [22:0] i2c_cmd;            // {byte1, byte0, addr7}
reg        i2c_go;
reg        i2c_probe;
reg        i2c_busy, nack, ack_bad, bus_stuck;
reg [31:0] i2c_done_count;
reg        clr_under, clr_over;

// FIFO (simple dual port, same clock)
(* ram_style = "block" *) reg [15:0] mem [0:DEPTH-1];
reg [AW:0]   wptr, rptr;
wire [AW:0]  level = wptr - rptr;
reg          push_hi;          // second half of a 32-bit write still to push
reg [15:0]   hi_word;
reg          wr_en;
reg [15:0]   wr_data;
reg [AW-1:0] wr_addr;
reg [15:0]   rd_q;
reg          rd_en;
reg [1:0]    ld;               // reader: 1 read issued, 2 data ready, 3 reload held sample
always @(posedge clk) begin
    if (wr_en) mem[wr_addr] <= wr_data;
    if (rd_en) rd_q <= mem[rptr[AW-1:0]];
end

wire full = level[AW];
always @(posedge clk) begin
    if (rst) begin
        s_axi_awready <= 1'b0; s_axi_wready <= 1'b0; s_axi_bvalid <= 1'b0;
        en <= 1'b0; mute <= 1'b0; mclk_en <= 1'b1; clear_req <= 1'b0; clear_pend <= 1'b0; i2c_go <= 1'b0;
        clr_under <= 1'b0; clr_over <= 1'b0; push_hi <= 1'b0; wr_en <= 1'b0; wptr <= 0;
        i2c_cmd <= 23'd0; i2c_probe <= 1'b0;
    end else begin
        clear_req <= 1'b0; i2c_go <= 1'b0; clr_under <= 1'b0; clr_over <= 1'b0; wr_en <= 1'b0;
        if (push_hi) begin                                   // second sample of the last write
            push_hi <= 1'b0;
            if (!full) begin wr_en <= 1'b1; wr_addr <= wptr[AW-1:0]; wr_data <= hi_word; wptr <= wptr + 1'b1; end
        end
        // Never silently discard a new I2C command while its predecessor is active.
        if (!s_axi_awready && !s_axi_wready && s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !push_hi &&
            !((s_axi_awaddr[15:12] != 4'h1) && (s_axi_awaddr[11:2] == 10'h004) && (i2c_busy || i2c_go))) begin
            s_axi_awready <= 1'b1; s_axi_wready <= 1'b1;
        end else begin
            s_axi_awready <= 1'b0; s_axi_wready <= 1'b0;
        end
        if (s_axi_awready && s_axi_wready) begin
            s_axi_bvalid <= 1'b1;
            if (s_axi_awaddr[15:12] == 4'h1) begin
                if (!full) begin
                    wr_en <= 1'b1; wr_addr <= wptr[AW-1:0]; wr_data <= s_axi_wdata[15:0]; wptr <= wptr + 1'b1;
                end
                push_hi <= 1'b1; hi_word <= s_axi_wdata[31:16];
            end else case (s_axi_awaddr[11:2])
                10'h002: begin en <= s_axi_wdata[0]; clear_req <= s_axi_wdata[1]; mclk_en <= s_axi_wdata[2]; mute <= s_axi_wdata[3]; end
                10'h004: begin i2c_cmd <= {s_axi_wdata[23:16], s_axi_wdata[15:8], s_axi_wdata[6:0]}; i2c_probe <= s_axi_wdata[24]; i2c_go <= 1'b1; end
                10'h005: clr_under <= 1'b1;
                10'h008: clr_over <= 1'b1;
                default: ;
            endcase
        end else if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
        // Drop everything queued once no read is in flight (rptr stays owned by the reader).
        if (clear_req) clear_pend <= 1'b1;
        else if (clear_pend && ld == 2'd0 && !rd_en) begin wptr <= rptr; clear_pend <= 1'b0; end
    end
end

// overflow counter: a push attempted while full
always @(posedge clk) begin
    if (rst || clr_over) overflows <= 0;
    else if (((s_axi_awready && s_axi_wready && s_axi_awaddr[15:12] == 4'h1) || push_hi) && full)
        overflows <= overflows + 1'b1;
end

// ------------------------------------------------------------------ MCLK = clk / 8
reg [1:0] mdiv;
always @(posedge clk) begin
    if (rst || !mclk_en) begin mdiv <= 2'd0; aud_mclk <= 1'b0; end
    else begin mdiv <= mdiv + 2'd1; if (mdiv == 2'd3) aud_mclk <= ~aud_mclk; end
end

// ------------------------------------------------------------------ I2S transmitter (slave)
(* ASYNC_REG = "TRUE" *) reg [1:0] bclk_s, lrc_s;
reg        bclk_d, lrc_last;
reg [15:0] sr, sample;
reg        load_left;
wire rise = bclk_s[1] & ~bclk_d;
wire fall = ~bclk_s[1] & bclk_d;
always @(posedge clk) begin
    bclk_s <= {bclk_s[0], aud_bclk};
    lrc_s  <= {lrc_s[0], aud_daclrc};
    bclk_d <= bclk_s[1];
    rd_en <= 1'b0;
    if (rst) begin
        lrc_last <= 1'b0; sr <= 16'd0; aud_dacdat <= 1'b0; rptr <= 0; ld <= 2'd0; sample <= 16'd0;
        frames <= 0;
    end else begin
        if (rise) begin
            lrc_last <= lrc_s[1];
            if (lrc_s[1] != lrc_last) begin
                if (!lrc_s[1]) begin                         // left half starts: fetch next sample
                    frames <= frames + 1'b1;
                    if (en && level != 0 && !clear_pend && !clear_req) begin rd_en <= 1'b1; ld <= 2'd1; end
                    else begin sample <= 16'd0; ld <= 2'd3; end
                end else ld <= 2'd3;                         // right half repeats the sample
            end
        end
        case (ld)
            2'd1: begin ld <= 2'd2; rptr <= rptr + 1'b1; end
            2'd2: begin sample <= rd_q; sr <= mute ? 16'd0 : rd_q; ld <= 2'd0; end
            2'd3: begin sr <= mute ? 16'd0 : sample; ld <= 2'd0; end
            default: ;
        endcase
        if (fall) begin aud_dacdat <= sr[15]; sr <= {sr[14:0], 1'b0}; end
    end
end

always @(posedge clk) begin
    if (rst || clr_under) underruns <= 0;
    else if (rise && lrc_s[1] != lrc_last && !lrc_s[1] && en && level == 0) underruns <= underruns + 1'b1;
end

// ------------------------------------------------------------------ I2C writer (3 bytes)
reg        sda_oe;             // 1 = pull SDA low
wire       sda_in;
// Keep both directions through Vivado's module-reference OOC synthesis. Inferring
// a tri-state here previously allowed the input to collapse to the driven zero.
IOBUF #(.IOSTANDARD("LVCMOS33")) sda_iobuf (
    .I(1'b0), .T(~sda_oe), .O(sda_in), .IO(aud_sda)
);
reg [1:0]  iq;
reg [4:0]  seg;                // 0 start, 1..27 bits, 28 stop
reg [3:0]  bitpos;
reg [23:0] tx;
reg [8:0]  qcnt;
(* ASYNC_REG = "TRUE" *) reg [1:0] sda_s;
always @(posedge clk) begin
    if (rst) sda_s <= 2'b11;
    else sda_s <= {sda_s[0], sda_in};
end
always @(posedge clk) begin
    if (rst) begin
        i2c_busy <= 1'b0; nack <= 1'b0; aud_scl <= 1'b1; sda_oe <= 1'b0; qcnt <= 0;
        ack_bad <= 1'b0; bus_stuck <= 1'b0; i2c_done_count <= 32'd0;
        seg <= 5'd0; iq <= 2'd0; bitpos <= 4'd0; tx <= 24'd0;
    end else if (!i2c_busy) begin
        aud_scl <= 1'b1; sda_oe <= 1'b0;
        if (i2c_go) begin
            ack_bad <= 1'b0; bus_stuck <= 1'b0; nack <= 1'b0;
            if (!sda_s[1]) begin
                // A low idle SDA is not an ACK. Do not generate any clocks/START.
                bus_stuck <= 1'b1; nack <= 1'b1;
                i2c_done_count <= i2c_done_count + 1'b1;
            end else begin
                i2c_busy <= 1'b1; tx <= {i2c_cmd[6:0], 1'b0, i2c_cmd[14:7], i2c_cmd[22:15]};
                seg <= 5'd0; iq <= 2'd0; bitpos <= 4'd0; qcnt <= 0;
            end
        end
    end else begin
        qcnt <= (qcnt == I2C_QDIV - 1) ? 9'd0 : qcnt + 1'b1;
        if (seg == 5'd0) begin                               // START
            aud_scl <= (iq < 2'd2); sda_oe <= (iq != 2'd0);
        end else if (seg == 5'd28) begin                     // STOP
            aud_scl <= (iq != 2'd0); sda_oe <= (iq < 2'd2);
        end else begin
            aud_scl <= (iq == 2'd1) || (iq == 2'd2);
            sda_oe <= (bitpos == 4'd8) ? 1'b0 : ~tx[23];
        end
        if (qcnt == I2C_QDIV - 1) begin
            if (seg != 5'd0 && seg != 5'd28 && bitpos == 4'd8 && iq == 2'd2) ack_bad <= sda_s[1];
            iq <= iq + 2'd1;
            if (iq == 2'd3) begin
                if (seg != 5'd0 && seg != 5'd28) begin
                    if (bitpos == 4'd8) begin bitpos <= 4'd0; if (ack_bad) nack <= 1'b1; end
                    else begin bitpos <= bitpos + 4'd1; tx <= {tx[22:0], 1'b0}; end
                end
                if (seg == 5'd28) begin
                    i2c_busy <= 1'b0;
                    i2c_done_count <= i2c_done_count + 1'b1;
                end else if (seg == 5'd9 && i2c_probe) seg <= 5'd28;
                else seg <= seg + 5'd1;
            end
        end
    end
end

// ------------------------------------------------------------------ AXI read
reg [15:0] rd_addr;
reg        rd_busy;
always @(posedge clk) begin
    if (rst) begin
        s_axi_arready <= 1'b0; s_axi_rvalid <= 1'b0; rd_busy <= 1'b0; s_axi_rdata <= 32'd0;
    end else begin
        if (!s_axi_arready && s_axi_arvalid && !rd_busy && !s_axi_rvalid) s_axi_arready <= 1'b1;
        else s_axi_arready <= 1'b0;
        if (s_axi_arready && s_axi_arvalid) begin rd_addr <= s_axi_araddr; rd_busy <= 1'b1; end
        else if (rd_busy) begin
            rd_busy <= 1'b0; s_axi_rvalid <= 1'b1;
            case (rd_addr[11:2])
                10'h000: s_axi_rdata <= ID;
                10'h001: s_axi_rdata <= VERSION;
                10'h002: s_axi_rdata <= {28'd0, mute, mclk_en, 1'b0, en};
                10'h003: s_axi_rdata <= {11'd0, bus_stuck, sda_s[1], bclk_s[1], nack, (i2c_busy | i2c_go), {(15-AW){1'b0}}, level};
                10'h004: s_axi_rdata <= {7'd0, i2c_probe, 1'b0, i2c_cmd};
                10'h005: s_axi_rdata <= underruns;
                10'h006: s_axi_rdata <= frames;
                10'h007: s_axi_rdata <= DEPTH;
                10'h008: s_axi_rdata <= overflows;
                10'h009: s_axi_rdata <= i2c_done_count;
                10'h00A: s_axi_rdata <= 32'd3;
                default: s_axi_rdata <= 32'd0;
            endcase
        end
        if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
    end
end
endmodule
