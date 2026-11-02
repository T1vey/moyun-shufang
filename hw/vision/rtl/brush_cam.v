`timescale 1ns/1ps
// OV7725 brush-writing front end (tcb705-brushcam-v1).
//   cam_pclk domain : DVP capture -> RGB565 gray -> ROI histogram/Otsu -> threshold
//                     -> four 3x3 morphology stages -> packed binary frame BRAM,
//                     160x120 gray preview BRAM, frame difference / stability.
//   s_axi_aclk domain: AXI4-Lite registers, SCCB init, BRAM readback.
// Address map (128 KiB): 0x00000 registers, 0x10000 binary frame (9600 x u32,
// 20 words/row, LSB = leftmost pixel), 0x1A000 preview (4800 x u32, 4 px/word).
// Freezing stops both frame writes at the next frame boundary so software can
// read a consistent snapshot; brush_vision/contract.py documents the registers.
module brush_cam #(
    parameter integer CLK_HZ = 100000000,
    parameter integer SCL_HZ = 100000,
    parameter integer SKIP_FRAMES = 8,
    parameter integer BOOT_DELAY = 200000,
    parameter integer RESET_DELAY = 300000
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire        s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire        s_axi_aresetn,
    input  wire [16:0] s_axi_awaddr,
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
    input  wire [16:0] s_axi_araddr,
    input  wire [2:0]  s_axi_arprot,
    input  wire        s_axi_arvalid,
    output reg         s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,
    (* X_INTERFACE_IGNORE = "true" *)
    input  wire        cam_pclk,
    input  wire        cam_vsync,
    input  wire        cam_href,
    input  wire [7:0]  cam_data,
    output wire        cam_rst_n,
    output wire        cam_sgm_ctrl,
    output wire        cam_scl,
    inout  wire        cam_sda
);
localparam integer W = 640, H = 480;
localparam integer WPR = W / 32;                 // binary words per row
localparam integer BIN_WORDS = WPR * H;          // 9600
localparam integer PRV_WORDS = (W / 4) * (H / 4) / 4;   // 4800
// The writer samples the 4th stage at step n; that value is pixel n-MORPH_DELAY.
localparam integer MORPH_DELAY = 4 * (W + 3);
localparam [31:0] ID = 32'h42434d31, VERSION = 32'h20261024;

assign s_axi_bresp = 2'b00;
assign s_axi_rresp = 2'b00;
assign cam_rst_n = 1'b1;
assign cam_sgm_ctrl = 1'b1;

wire aclk = s_axi_aclk;
wire arst = ~s_axi_aresetn;

// ---------------------------------------------------------------- AXI registers
reg  [31:0] r_ctrl, r_thresh, r_roi_x, r_roi_y, r_stable, r_ink_min;
reg         sccb_restart, sccb_req;
reg  [15:0] sccb_data;

always @(posedge aclk) begin
    if (arst) begin
        s_axi_awready <= 1'b0; s_axi_wready <= 1'b0; s_axi_bvalid <= 1'b0;
        r_ctrl <= 32'h0000_6902; r_thresh <= 32'h0000_0064;
        r_roi_x <= {6'd0, 10'd639, 6'd0, 10'd0}; r_roi_y <= {7'd0, 9'd479, 7'd0, 9'd0};
        r_stable <= {8'd10, 5'd0, 19'd400}; r_ink_min <= 32'd200;
        sccb_restart <= 1'b0; sccb_req <= 1'b0; sccb_data <= 16'd0;
    end else begin
        sccb_restart <= 1'b0; sccb_req <= 1'b0;
        if (!s_axi_awready && !s_axi_wready && s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid) begin
            s_axi_awready <= 1'b1; s_axi_wready <= 1'b1;
        end else begin
            s_axi_awready <= 1'b0; s_axi_wready <= 1'b0;
        end
        if (s_axi_awready && s_axi_wready) begin
            s_axi_bvalid <= 1'b1;
            case (s_axi_awaddr[16:2])
            15'h0002: begin r_ctrl <= s_axi_wdata & 32'hffff_fffb; sccb_restart <= s_axi_wdata[2]; end
            15'h0003: r_thresh <= s_axi_wdata;
            15'h0004: r_roi_x <= s_axi_wdata;
            15'h0005: r_roi_y <= s_axi_wdata;
            15'h0006: r_stable <= s_axi_wdata;
            15'h0007: r_ink_min <= s_axi_wdata;
            15'h0008: begin sccb_data <= s_axi_wdata[15:0]; sccb_req <= 1'b1; end
            default: ;
            endcase
        end else if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
    end
end

// ---------------------------------------------------------------- SCCB
wire sccb_done, sccb_busy, sda_o, sda_oe;
wire [7:0] sccb_nack;
brush_sccb #(.CLK_HZ(CLK_HZ), .SCL_HZ(SCL_HZ), .BOOT_DELAY(BOOT_DELAY), .RESET_DELAY(RESET_DELAY)) u_sccb (
    .clk(aclk), .rst(arst), .restart(sccb_restart), .user_req(sccb_req), .user_data(sccb_data),
    .init_done(sccb_done), .busy(sccb_busy), .nack_count(sccb_nack),
    .scl(cam_scl), .sda_o(sda_o), .sda_oe(sda_oe), .sda_i(cam_sda));
assign cam_sda = sda_oe ? sda_o : 1'bz;

// ---------------------------------------------------------------- AXI -> PCLK config
(* ASYNC_REG = "TRUE" *) reg [31:0] c_ctrl1, c_ctrl2, c_thr1, c_thr2, c_rx1, c_rx2, c_ry1, c_ry2;
(* ASYNC_REG = "TRUE" *) reg [31:0] c_st1, c_st2, c_ink1, c_ink2;
(* ASYNC_REG = "TRUE" *) reg        c_init1, c_init2, c_rst1, c_rst2;
wire pclk = cam_pclk;
always @(posedge pclk) begin
    c_ctrl1 <= r_ctrl;  c_ctrl2 <= c_ctrl1;  c_thr1 <= r_thresh; c_thr2 <= c_thr1;
    c_rx1 <= r_roi_x;   c_rx2 <= c_rx1;      c_ry1 <= r_roi_y;   c_ry2 <= c_ry1;
    c_st1 <= r_stable;  c_st2 <= c_st1;      c_ink1 <= r_ink_min; c_ink2 <= c_ink1;
    c_init1 <= sccb_done; c_init2 <= c_init1;
    c_rst1 <= arst; c_rst2 <= c_rst1;
end
wire prst = c_rst2;

// ---------------------------------------------------------------- DVP capture
(* IOB = "TRUE" *) reg [7:0] d_r;
(* IOB = "TRUE" *) reg vs_r, hs_r;
reg vs_d, hs_d, byte_flag;
reg [7:0]  d_hi;
reg [9:0]  x_cnt;
reg [9:0]  y_cnt;
reg [11:0] line_bytes, last_line_bytes;
reg        pv0;
reg [15:0] pix0;
reg [9:0]  px0;
reg [9:0]  py0;
wire frame_start = vs_r & ~vs_d;
reg  [7:0] skip_cnt;
wire run = c_init2 && (skip_cnt >= SKIP_FRAMES);

always @(posedge pclk) begin
    d_r <= cam_data; vs_r <= cam_vsync; hs_r <= cam_href;
    vs_d <= vs_r; hs_d <= hs_r;
    pv0 <= 1'b0;
    if (prst || frame_start) begin
        x_cnt <= 10'd0; y_cnt <= 10'd0; byte_flag <= 1'b0; line_bytes <= 12'd0;
    end else if (hs_r) begin
        byte_flag <= ~byte_flag;
        line_bytes <= line_bytes + 12'd1;
        if (!byte_flag) d_hi <= d_r;
        else begin
            pix0 <= {d_hi, d_r}; px0 <= x_cnt; py0 <= y_cnt;
            pv0 <= run && (x_cnt < W) && (y_cnt < H);
            x_cnt <= x_cnt + 10'd1;
        end
    end else begin
        byte_flag <= 1'b0;
        if (hs_d) begin
            y_cnt <= y_cnt + 10'd1; x_cnt <= 10'd0;
            last_line_bytes <= line_bytes; line_bytes <= 12'd0;
        end
    end
end

// ---------------------------------------------------------------- gray (2 stages)
wire [7:0] r8 = {pix0[15:11], pix0[15:13]};
wire [7:0] g8 = {pix0[10:5],  pix0[10:9]};
wire [7:0] b8 = {pix0[4:0],   pix0[4:2]};
reg [15:0] ysum;
reg        pv1, pv2;
reg [9:0]  px1, px2;
reg [9:0]  py1, py2;
reg [7:0]  gray;
always @(posedge pclk) begin
    ysum <= r8 * 8'd77 + g8 * 8'd150 + b8 * 8'd29;
    pv1 <= pv0; px1 <= px0; py1 <= py0;
    gray <= ysum[15:8];
    pv2 <= pv1; px2 <= px1; py2 <= py1;
end

// ---------------------------------------------------------------- frame state
reg        acc_bank;
reg [7:0]  thr_frame;
reg [7:0]  ops0, ops1, ops2, ops3;
reg        frozen;
reg [31:0] frame_cnt;
reg [18:0] ink_acc, diff_acc;
reg [14:0] hn_acc;
reg [22:0] hs_acc;
reg [7:0]  stable_cnt;
reg [31:0] st_ink, st_diff, st_hn, st_geom, st_misc;
reg        st_tog;
reg        otsu_start;
reg [14:0] otsu_n;
reg [22:0] otsu_s;
wire [7:0] otsu_t;
wire       otsu_valid, otsu_busy;
wire [8:0] otsu_addr;
wire       otsu_clr;
reg        otsu_bank;

// Otsu offset (signed) applied to the automatic threshold.
wire signed [9:0] thr_biased = $signed({2'b00, otsu_t}) + $signed({{2{c_thr2[15]}}, c_thr2[15:8]});
wire [7:0] thr_next = c_ctrl2[1] ? (thr_biased < 0 ? 8'd0 : (thr_biased > 255 ? 8'd255 : thr_biased[7:0]))
                                 : c_thr2[7:0];

// ---------------------------------------------------------------- histogram RAM (2 banks)
(* ram_style = "block" *) reg [15:0] hist [0:511];
reg [8:0]  ha_addr;
reg        ha_we;
reg [15:0] ha_din, ha_q, hb_q;
reg [1:0]  hst;
integer k;
initial for (k = 0; k < 512; k = k + 1) hist[k] = 16'd0;
always @(posedge pclk) begin
    if (ha_we) hist[ha_addr] <= ha_din;
    ha_q <= hist[ha_addr];
end
always @(posedge pclk) begin
    if (otsu_clr) hist[{otsu_bank, otsu_addr[7:0]}] <= 16'd0;
    hb_q <= hist[{otsu_bank, otsu_addr[7:0]}];
end

wire in_roi = (px2 >= c_rx2[9:0]) && (px2 <= c_rx2[25:16]) && (py2 >= c_ry2[9:0]) && (py2 <= c_ry2[25:16]);
wire sample = pv2 && (px2[1:0] == 2'd0) && (py2[1:0] == 2'd0);
always @(posedge pclk) begin
    ha_we <= 1'b0;
    if (prst) hst <= 2'd0;
    else case (hst)
        2'd0: if (sample && in_roi) begin ha_addr <= {acc_bank, gray}; hst <= 2'd1; end
        2'd1: hst <= 2'd2;
        2'd2: begin ha_din <= ha_q + 16'd1; ha_we <= 1'b1; hst <= 2'd3; end
        default: hst <= 2'd0;
    endcase
end

brush_otsu u_otsu (.clk(pclk), .rst(prst), .start(otsu_start), .n_total(otsu_n), .s_total(otsu_s),
    .rd_addr_lo(otsu_addr), .clr_we(otsu_clr), .rd_data(hb_q), .threshold(otsu_t),
    .valid(otsu_valid), .busy(otsu_busy));

// ---------------------------------------------------------------- binarize + morphology
reg bin_px, bin_v;
reg [18:0] step;          // valid-pixel step within the frame
always @(posedge pclk) begin
    bin_px <= (gray < thr_frame);
    bin_v  <= pv2;
end
wire m0, m1, m2, m3;
brush_morph #(.W(W)) u_m0 (.clk(pclk), .ce(bin_v), .din(bin_px), .op(ops0[1:0]), .dout(m0));
brush_morph #(.W(W)) u_m1 (.clk(pclk), .ce(bin_v), .din(m0),     .op(ops1[1:0]), .dout(m1));
brush_morph #(.W(W)) u_m2 (.clk(pclk), .ce(bin_v), .din(m1),     .op(ops2[1:0]), .dout(m2));
brush_morph #(.W(W)) u_m3 (.clk(pclk), .ce(bin_v), .din(m2),     .op(ops3[1:0]), .dout(m3));

// ---------------------------------------------------------------- binary frame RAM
(* ram_style = "block" *) reg [31:0] bin_mem [0:BIN_WORDS-1];
(* ram_style = "block" *) reg [31:0] prv_mem [0:PRV_WORDS-1];
reg [13:0] bw_addr;
reg        bw_we, bw_go;
reg [31:0] bw_din, bw_old, bw_new;
reg        bw_chk;
reg [9:0]  xo;
reg [9:0]  yo;
reg [31:0] shreg;
reg [12:0] pw_addr;
reg        pw_we;
reg [31:0] pw_din, pshreg;
initial begin
    for (k = 0; k < BIN_WORDS; k = k + 1) bin_mem[k] = 32'd0;
    for (k = 0; k < PRV_WORDS; k = k + 1) prv_mem[k] = 32'd0;
end
always @(posedge pclk) begin
    if (bw_we) bin_mem[bw_addr] <= bw_din;
    bw_old <= bin_mem[bw_addr];
end
always @(posedge pclk) if (pw_we) prv_mem[pw_addr] <= pw_din;

function [5:0] popcnt32;
    input [31:0] v;
    integer j;
    begin
        popcnt32 = 6'd0;
        for (j = 0; j < 32; j = j + 1) popcnt32 = popcnt32 + v[j];
    end
endfunction

wire border = (xo < 10'd4) || (xo > W - 5) || (yo < 10'd4) || (yo > H - 5);
always @(posedge pclk) begin
    bw_we <= 1'b0; bw_go <= 1'b0; pw_we <= 1'b0; otsu_start <= 1'b0; bw_chk <= bw_go;
    if (prst) begin
        acc_bank <= 1'b0; otsu_bank <= 1'b1; thr_frame <= 8'd100; frozen <= 1'b0; frame_cnt <= 32'd0;
        ink_acc <= 19'd0; diff_acc <= 19'd0; hn_acc <= 15'd0; hs_acc <= 23'd0; stable_cnt <= 8'd0;
        step <= 19'd0; xo <= 10'd0; yo <= 10'd0; st_tog <= 1'b0; skip_cnt <= 8'd0;
        ops0 <= 8'd0; ops1 <= 8'd0; ops2 <= 8'd0; ops3 <= 8'd0;
    end else if (frame_start) begin
        frame_cnt <= frame_cnt + 32'd1;
        if (!c_init2) skip_cnt <= 8'd0;
        else if (skip_cnt != 8'hff) skip_cnt <= skip_cnt + 8'd1;
        st_ink  <= {13'd0, ink_acc};
        st_diff <= {13'd0, diff_acc};
        st_hn   <= {17'd0, hn_acc};
        st_geom <= {4'd0, last_line_bytes, 6'd0, y_cnt};
        if (!frozen) begin
            if (diff_acc <= c_st2[18:0] && ink_acc >= c_ink2[18:0]) begin
                if (stable_cnt != 8'hff) stable_cnt <= stable_cnt + 8'd1;
            end else stable_cnt <= 8'd0;
        end
        st_tog <= ~st_tog;
        if (!otsu_busy) begin
            otsu_bank <= acc_bank; acc_bank <= ~acc_bank;
            otsu_n <= hn_acc; otsu_s <= hs_acc; otsu_start <= 1'b1;
        end
        ink_acc <= 19'd0; diff_acc <= 19'd0; hn_acc <= 15'd0; hs_acc <= 23'd0;
        thr_frame <= thr_next;
        frozen <= c_ctrl2[0];
        ops0 <= {6'd0, c_ctrl2[9:8]}; ops1 <= {6'd0, c_ctrl2[11:10]};
        ops2 <= {6'd0, c_ctrl2[13:12]}; ops3 <= {6'd0, c_ctrl2[15:14]};
        step <= 19'd0; xo <= 10'd0; yo <= 10'd0;
    end else begin
        if (sample && in_roi) begin hn_acc <= hn_acc + 15'd1; hs_acc <= hs_acc + gray; end
        // Preview: every 4th pixel of every 4th row, 4 pixels per word.
        if (sample) begin
            pshreg <= {gray, pshreg[31:8]};
            if (px2[3:2] == 2'd3) begin
                pw_din <= {gray, pshreg[31:8]};
                pw_addr <= py2[9:2] * 8'd40 + px2[9:4];
                pw_we <= ~frozen;
            end
        end
        if (bin_v) begin
            step <= step + 19'd1;
            if (step >= MORPH_DELAY) begin
                shreg <= {m3 & ~border, shreg[31:1]};
                if (xo[4:0] == 5'd31) begin
                    bw_din <= {m3 & ~border, shreg[31:1]};
                    bw_addr <= yo * WPR + xo[9:5];
                    bw_we <= ~frozen; bw_go <= 1'b1;
                end
                if (xo == W - 1) begin xo <= 10'd0; yo <= yo + 10'd1; end
                else xo <= xo + 10'd1;
            end
        end
        if (bw_go) bw_new <= bw_din;   // live ink/diff also while frozen
        if (bw_chk) begin
            ink_acc  <= ink_acc + popcnt32(bw_new);
            diff_acc <= diff_acc + popcnt32(bw_new ^ bw_old);
        end
    end
end

// ---------------------------------------------------------------- PCLK -> AXI status
(* ASYNC_REG = "TRUE" *) reg tg1, tg2;
reg tg3;
reg [31:0] a_frames, a_ink, a_diff, a_hn, a_geom, a_thr, a_misc;
always @(posedge pclk) begin
    st_misc <= {8'd0, stable_cnt, 6'd0, (stable_cnt >= c_st2[31:24]) && (c_st2[31:24] != 0), frozen, otsu_valid, run, 6'd0};
end
always @(posedge aclk) begin
    tg1 <= st_tog; tg2 <= tg1; tg3 <= tg2;
    if (arst) begin
        a_frames <= 0; a_ink <= 0; a_diff <= 0; a_hn <= 0; a_geom <= 0; a_thr <= 0; a_misc <= 0;
    end else if (tg2 != tg3) begin
        a_frames <= frame_cnt; a_ink <= st_ink; a_diff <= st_diff; a_hn <= st_hn; a_geom <= st_geom;
        a_thr <= {15'd0, otsu_valid, thr_frame, otsu_t};
        a_misc <= st_misc;
    end
end

// ---------------------------------------------------------------- AXI read
reg [16:0] rd_addr;
reg        rd_busy;
reg [1:0]  rd_wait;
reg [31:0] bin_q, prv_q;
wire [13:0] bin_ridx = rd_addr[15:2];
wire [13:0] prv_ridx = rd_addr[15:2] - 14'h2800;
always @(posedge aclk) begin
    bin_q <= bin_mem[bin_ridx];
    prv_q <= prv_mem[prv_ridx[12:0]];
end
always @(posedge aclk) begin
    if (arst) begin
        s_axi_arready <= 1'b0; s_axi_rvalid <= 1'b0; rd_busy <= 1'b0; rd_wait <= 2'd0; s_axi_rdata <= 32'd0;
    end else begin
        if (!s_axi_arready && s_axi_arvalid && !rd_busy && !s_axi_rvalid) s_axi_arready <= 1'b1;
        else s_axi_arready <= 1'b0;
        if (s_axi_arready && s_axi_arvalid) begin
            rd_addr <= s_axi_araddr; rd_busy <= 1'b1; rd_wait <= 2'd0;
        end else if (rd_busy) begin
            rd_wait <= rd_wait + 2'd1;
            if (rd_wait == 2'd2) begin
                rd_busy <= 1'b0; s_axi_rvalid <= 1'b1;
                if (rd_addr[16]) begin
                    if (rd_addr[15:0] < 16'h9600) s_axi_rdata <= bin_q;
                    else if (rd_addr[15:0] >= 16'hA000 && rd_addr[15:0] < 16'hEB00) s_axi_rdata <= prv_q;
                    else s_axi_rdata <= 32'd0;
                end else case (rd_addr[15:2])
                    14'h0000: s_axi_rdata <= ID;
                    14'h0001: s_axi_rdata <= VERSION;
                    14'h0002: s_axi_rdata <= r_ctrl;
                    14'h0003: s_axi_rdata <= r_thresh;
                    14'h0004: s_axi_rdata <= r_roi_x;
                    14'h0005: s_axi_rdata <= r_roi_y;
                    14'h0006: s_axi_rdata <= r_stable;
                    14'h0007: s_axi_rdata <= r_ink_min;
                    // STATUS: init_done, frozen, stable, sccb_busy, running, otsu_valid, nacks
                    14'h0010: s_axi_rdata <= {16'd0, sccb_nack, 2'd0, a_misc[7], a_misc[6], sccb_busy,
                                              a_misc[9], a_misc[8], sccb_done};
                    14'h0011: s_axi_rdata <= a_frames;
                    14'h0012: s_axi_rdata <= a_thr;
                    14'h0013: s_axi_rdata <= a_ink;
                    14'h0014: s_axi_rdata <= a_diff;
                    14'h0015: s_axi_rdata <= a_hn;
                    14'h0016: s_axi_rdata <= a_geom;
                    14'h0017: s_axi_rdata <= a_misc;
                    default:  s_axi_rdata <= 32'd0;
                endcase
            end
        end
        if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
    end
end
endmodule
