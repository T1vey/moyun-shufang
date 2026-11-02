`timescale 1ns/1ps
// Sequential Otsu threshold over a 256-bin histogram bank (read and cleared).
// sigma_B^2(t) is proportional to (S*n0 - N*s0)^2 / (n0*n1); the square is taken
// on |diff|>>7 and divided with a 62/30-bit restoring divider (~70 clocks/bin).
// Ties extend a contiguous plateau and the threshold is its midpoint, so an empty
// gap between ink and paper peaks does not pin T to the ink side.
// brush_vision/model.py:otsu_threshold mirrors this arithmetic exactly.
module brush_otsu (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire [14:0] n_total,
    input  wire [22:0] s_total,
    output reg  [8:0]  rd_addr_lo,   // bin index (bank selected by the caller)
    output reg         clr_we,
    input  wire [15:0] rd_data,
    output reg  [7:0]  threshold,
    output reg         valid,
    output wire        busy
);
localparam S_IDLE=4'd0, S_RD=4'd1, S_W1=4'd2, S_W2=4'd3, S_ACC=4'd4, S_MUL=4'd5,
           S_DIF=4'd6, S_SQ=4'd7, S_DIV=4'd8, S_CMP=4'd9, S_NEXT=4'd10, S_DONE=4'd11;
reg [3:0]  st;
reg [8:0]  t;
reg [15:0] h;
reg [14:0] n0, n1, nt;
reg [22:0] s0, stt;
reg [37:0] pa, pb;
reg [30:0] d;
reg [29:0] den;
reg [61:0] sq, qt, best;
reg [30:0] rem;
reg [5:0]  i;
reg [7:0]  best_t, last_t;
reg        found, on_best;
wire [38:0] diff = {1'b0, pa} - {1'b0, pb};
wire [38:0] adiff = diff[38] ? (~diff + 39'd1) : diff;
wire [30:0] rnext = {rem[29:0], sq[i]};
assign busy = (st != S_IDLE);

always @(posedge clk) begin
    if (rst) begin
        st <= S_IDLE; threshold <= 8'd100; valid <= 1'b0; clr_we <= 1'b0; rd_addr_lo <= 9'd0;
    end else begin
        clr_we <= 1'b0;
        case (st)
        S_IDLE: if (start) begin
            t <= 9'd0; n0 <= 15'd0; s0 <= 23'd0; best <= 62'd0; found <= 1'b0; on_best <= 1'b0;
            nt <= n_total; stt <= s_total;
            st <= (n_total == 15'd0) ? S_DONE : S_RD;
        end
        S_RD:   begin rd_addr_lo <= t; st <= S_W1; end
        S_W1:   st <= S_W2;
        S_W2:   begin h <= rd_data; clr_we <= 1'b1; st <= S_ACC; end
        S_ACC:  begin n0 <= n0 + h[14:0]; s0 <= s0 + t[7:0] * h[14:0]; st <= S_MUL; end
        S_MUL:  begin pa <= stt * n0; pb <= nt * s0; n1 <= nt - n0; st <= S_DIF; end
        S_DIF:  begin
            if (n0 == 15'd0 || n1 == 15'd0) begin on_best <= 1'b0; st <= S_NEXT; end
            else begin d <= adiff[37:7]; den <= n0 * n1; st <= S_SQ; end
        end
        S_SQ:   begin sq <= d * d; rem <= 31'd0; qt <= 62'd0; i <= 6'd61; st <= S_DIV; end
        S_DIV:  begin
            if (rnext >= {1'b0, den}) begin rem <= rnext - {1'b0, den}; qt[i] <= 1'b1; end
            else rem <= rnext;
            if (i == 6'd0) st <= S_CMP; else i <= i - 6'd1;
        end
        S_CMP:  begin
            if (qt > best) begin best <= qt; best_t <= t[7:0]; last_t <= t[7:0]; found <= 1'b1; on_best <= 1'b1; end
            else if (qt == best && on_best) last_t <= t[7:0];
            else on_best <= 1'b0;
            st <= S_NEXT;
        end
        S_NEXT: begin if (t == 9'd255) st <= S_DONE; else begin t <= t + 9'd1; st <= S_RD; end end
        S_DONE: begin if (found) threshold <= ({1'b0, best_t} + {1'b0, last_t}) >> 1; valid <= found | valid; st <= S_IDLE; end
        default: st <= S_IDLE;
        endcase
    end
end
endmodule
