`timescale 1ns/1ps
// ES8388 normal /256 mode: MCLK 12.5 MHz, BCLK 3.125 MHz, LRCK 48,828.125 Hz.
// There are 32 BCLKs per channel. I2S starts one BCLK after the LRCK edge;
// the first 16 bits carry PCM, the following 16 bits must be zero padding.
// Uses the actual audio_out RTL and UNISIM IOBUF; no alternative serializer model.
module tb_audio_es8388;
reg aclk = 0, aresetn = 0;
always #5 aclk = ~aclk;
reg [15:0] awaddr = 0, araddr = 0;
reg awvalid = 0, wvalid = 0, arvalid = 0;
reg [31:0] wdata = 0;
wire awready, wready, bvalid, arready, rvalid;
wire [31:0] rdata;
wire [1:0] bresp, rresp;
reg bclk = 0, lrc = 0;
wire mclk, dacdat, scl, sda;
pullup(sda);
audio_out #(.AW(10), .I2C_QDIV(10)) dut (
    .s_axi_aclk(aclk), .s_axi_aresetn(aresetn),
    .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(4'hf), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
    .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
    .aud_mclk(mclk), .aud_bclk(bclk), .aud_daclrc(lrc), .aud_dacdat(dacdat),
    .aud_scl(scl), .aud_sda(sda));

task wr(input [15:0] addr, input [31:0] data);
    begin
        @(posedge aclk); awaddr <= addr; wdata <= data; awvalid <= 1; wvalid <= 1;
        @(posedge aclk); while (!(awready && wready)) @(posedge aclk);
        awvalid <= 0; wvalid <= 0;
        while (!bvalid) @(posedge aclk);
        @(posedge aclk);
    end
endtask
task rd(input [15:0] addr, output [31:0] data);
    begin
        @(posedge aclk); araddr <= addr; arvalid <= 1;
        @(posedge aclk); while (!arready) @(posedge aclk);
        arvalid <= 0;
        while (!rvalid) @(posedge aclk);
        data = rdata; @(posedge aclk);
    end
endtask

// Codec is the clock master: LRCK changes on each 32nd BCLK falling edge.
integer clock_slot = 0;
initial forever begin
    #160 bclk = 1;
    #160 bclk = 0;
    if (clock_slot == 31) begin clock_slot = 0; lrc = ~lrc; end
    else clock_slot = clock_slot + 1;
end

// Independent I2S receiver: boundary edge is the previous slot's padding LSB,
// NOT the next word's MSB. Capture exactly positions 1..16 following the edge.
reg last_lrc = 0, receiving = 0, channel = 0;
reg [15:0] word = 0;
reg [15:0] capL [0:2047], capR [0:2047];
integer position = 0, nL = 0, nR = 0, padding_checks = 0, padding_errors = 0;
always @(posedge bclk) begin
    if (lrc != last_lrc) begin
        if (receiving) begin
            padding_checks = padding_checks + 1;
            if (dacdat !== 1'b0) padding_errors = padding_errors + 1;
        end
        receiving = 1; channel = lrc; position = 0; word = 0;
    end else if (receiving) begin
        position = position + 1;
        if (position <= 16) begin
            word = {word[14:0], dacdat};
            if (position == 16) begin
                if (channel) begin capR[nR] = word; nR = nR + 1; end
                else begin capL[nL] = word; nL = nL + 1; end
            end
        end else begin
            padding_checks = padding_checks + 1;
            if (dacdat !== 1'b0) padding_errors = padding_errors + 1;
        end
    end
    last_lrc = lrc;
end

integer i, fails = 0, firstL, firstR, endL, endR;
reg [31:0] value, frames_before, frames_after;
reg [15:0] samples [0:399];
initial begin
    for (i = 0; i < 400; i = i + 1) samples[i] = (i * 16'd2749) ^ 16'h5a3c;
    #200 aresetn = 1;
    rd(16'h0000, value);
    if (value !== 32'h41554431) begin fails = fails + 1; $display("wrong ID %h", value); end
    // Frame counter runs with the DAC clocks even when playback is not enabled.
    rd(16'h0018, frames_before);
    #1_000_000;
    rd(16'h0018, frames_after);
    if (frames_after - frames_before < 48 || frames_after - frames_before > 49) begin
        fails = fails + 1; $display("frame rate mismatch: %d frames/ms", frames_after-frames_before);
    end
    for (i = 0; i < 400; i = i + 2)
        wr(16'h1000 + (i % 64) * 2, {samples[i+1], samples[i]});
    rd(16'h000C, value);
    if (value[14:0] !== 15'd400) begin fails = fails + 1; $display("queue level %d", value[14:0]); end
    firstL = nL; firstR = nR;
    wr(16'h0008, 32'h5);
    wait (nL >= firstL + 420 && nR >= firstR + 420);
    endL = nL; endR = nR;
    while (firstL < endL && capL[firstL] !== samples[0]) firstL = firstL + 1;
    while (firstR < endR && capR[firstR] !== samples[0]) firstR = firstR + 1;
    if (firstL + 400 >= endL || firstR + 400 >= endR) begin
        fails = fails + 1; $display("valid I2S sample stream not found L=%d R=%d", firstL, firstR);
    end else begin
        for (i = 0; i < 400; i = i + 1)
            if (capL[firstL+i] !== samples[i] || capR[firstR+i] !== samples[i]) begin
                if (fails < 12) $display("PCM mismatch sample=%d L=%h R=%h want=%h",
                    i, capL[firstL+i], capR[firstR+i], samples[i]);
                fails = fails + 1;
            end
        if (capL[firstL+400] !== 0 || capR[firstR+400] !== 0) begin
            fails = fails + 1; $display("FIFO drain did not output stereo silence");
        end
    end
    rd(16'h0014, value);
    if (value == 0) begin fails = fails + 1; $display("missing underrun count"); end
    rd(16'h000C, value);
    if (value[14:0] !== 0) begin fails = fails + 1; $display("drained FIFO level %h", value); end
    // Queue while disabled, clear, then enable; no cleared word may escape.
    wr(16'h0008, 32'h4);
    for (i = 0; i < 20; i = i + 2) wr(16'h1000, 32'h7fff8000);
    wr(16'h0008, 32'h6); repeat (20) @(posedge aclk);
    rd(16'h000C, value);
    if (value[14:0] !== 0) begin fails = fails + 1; $display("clear failed %h", value); end
    firstL = nL; firstR = nR;
    wr(16'h0008, 32'h5);
    wait (nL >= firstL + 5 && nR >= firstR + 5);
    for (i = 0; i < 5; i = i + 1)
        if (capL[firstL+i] !== 0 || capR[firstR+i] !== 0) begin
            fails = fails + 1; $display("cleared data leaked into output");
        end
    if (padding_errors != 0 || padding_checks < 12800) begin
        fails = fails + 1; $display("padding errors=%d checks=%d", padding_errors, padding_checks);
    end
    $display("ES8388 64fs: 400 PCM samples matched in both channels; padding checks=%d errors=%d",
        padding_checks, padding_errors);
    $display("clock profile: MCLK=12500000 BCLK=3125000 LRCK=48828.125; 32-bit slots, 16-bit PCM");
    if (fails) $display("TB_FAIL %d", fails); else $display("TB_PASS_ES8388");
    $finish;
end
initial begin #40_000_000; $display("TB_FAIL_ES8388_TIMEOUT"); $finish; end
endmodule
