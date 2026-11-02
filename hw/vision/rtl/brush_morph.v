`timescale 1ns/1ps
// One 3x3 binary morphology stage for a stream of exactly W pixels per row.
// op: 0 pass (window centre), 1 erode (AND), 2 dilate (OR).
// With a common clock enable, dout after step n is the window centred on
// input n-(W+2); each further stage adds W+3 steps (see brush_cam MORPH_DELAY).
module brush_morph #(parameter integer W = 640) (
    input  wire       clk,
    input  wire       ce,
    input  wire       din,
    input  wire [1:0] op,
    output reg        dout
);
reg [W-1:0] lb1 = {W{1'b0}};
reg [W-1:0] lb2 = {W{1'b0}};
reg [2:0]   r0 = 3'd0, r1 = 3'd0, r2 = 3'd0;
always @(posedge clk) begin
    if (ce) begin
        lb1 <= {lb1[W-2:0], din};
        lb2 <= {lb2[W-2:0], lb1[W-1]};
        r0  <= {r0[1:0], din};
        r1  <= {r1[1:0], lb1[W-1]};
        r2  <= {r2[1:0], lb2[W-1]};
        case (op)
        2'd1:    dout <= &{r0, r1, r2};
        2'd2:    dout <= |{r0, r1, r2};
        default: dout <= r1[1];
        endcase
    end
end
endmodule
