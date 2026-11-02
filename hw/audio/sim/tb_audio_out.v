`timescale 1ns/1ps
// audio_out against a behavioural WM8960: I2S master (BCLK 1.536 MHz, 16-bit, 48 kHz)
// that captures DACDAT on BCLK rising edges, and an I2C slave at 0x1A that ACKs and
// records bytes.  Prints TB_PASS / TB_FAIL.
module tb_audio_out;
reg aclk = 0, aresetn = 0;
always #5 aclk = ~aclk;
reg  [15:0] awaddr = 0, araddr = 0;
reg         awvalid = 0, wvalid = 0, arvalid = 0;
reg  [31:0] wdata = 0;
wire        awready, wready, bvalid, arready, rvalid;
wire [31:0] rdata;
wire [1:0]  bresp, rresp;
reg  bclk = 0, lrc = 0;
wire mclk, dacdat, scl, sda;
pullup(sda);
reg  sda_pull = 0;
reg  force_sda_low = 0;
assign sda = (sda_pull || force_sda_low) ? 1'b0 : 1'bz;
integer i, fails = 0, first, firstR;
integer scl_edges = 0;
always @(posedge scl) scl_edges = scl_edges + 1;

audio_out #(.AW(10), .I2C_QDIV(10)) dut (
    .s_axi_aclk(aclk), .s_axi_aresetn(aresetn),
    .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(4'hf), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
    .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
    .aud_mclk(mclk), .aud_bclk(bclk), .aud_daclrc(lrc), .aud_dacdat(dacdat), .aud_scl(scl), .aud_sda(sda));

task wr(input [15:0] a, input [31:0] d);
    begin
        @(posedge aclk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
        @(posedge aclk); while (!(awready && wready)) @(posedge aclk);
        awvalid <= 0; wvalid <= 0;
        while (!bvalid) @(posedge aclk);
        @(posedge aclk);
    end
endtask
task rd(input [15:0] a, output [31:0] d);
    begin
        @(posedge aclk); araddr <= a; arvalid <= 1;
        @(posedge aclk); while (!arready) @(posedge aclk);
        arvalid <= 0;
        while (!rvalid) @(posedge aclk);
        d = rdata; @(posedge aclk);
    end
endtask

task i2c_transaction(input [31:0] command, input want_nack, input want_stuck);
    reg [31:0] before_count, after_count, status;
    integer polls;
    begin
        rd(16'h0024, before_count);
        wr(16'h0010, command);
        after_count = before_count; polls = 0;
        while (after_count == before_count && polls < 10000) begin
            rd(16'h0024, after_count); polls = polls + 1;
        end
        rd(16'h000C, status);
        if (after_count !== before_count + 32'd1 || status[16] !== 1'b0 ||
            status[17] !== want_nack || status[20] !== want_stuck) begin
            fails = fails + 1;
            $display("I2C transaction FAIL cmd=%h count=%h->%h status=%h expected nack=%b stuck=%b",
                command, before_count, after_count, status, want_nack, want_stuck);
        end
    end
endtask

// ---------------------------------------------------------------- codec I2S master
integer bitcnt = 0;
reg [15:0] word = 0;
reg        prev_lrc = 0;
reg [15:0] capL [0:4095];
reg [15:0] capR [0:4095];
integer nL = 0, nR = 0;
initial forever begin
    // I2S: LRC changes on a BCLK falling edge; the word's MSB is sampled on the 2nd rising
    // edge after that, its LSB on the 1st rising edge of the next half frame.
    #325.5 bclk = 1;                                   // rising: codec samples DACDAT
    word = {word[14:0], dacdat};
    if (bitcnt == 0) begin
        if (prev_lrc == 0) begin capL[nL] = word; nL = nL + 1; end
        else begin capR[nR] = word; nR = nR + 1; end
    end
    #325.5 bclk = 0;                                   // falling: codec drives LRC
    bitcnt = bitcnt + 1;
    if (bitcnt == 16) begin prev_lrc = lrc; lrc = ~lrc; bitcnt = 0; end
end

// ---------------------------------------------------------------- codec I2C slave
reg [7:0] ibytes [0:255];
integer   nbytes = 0, ibit = 0, byte_index = 0;
reg [7:0] sh = 0;
reg       active = 0, addressed = 0;
reg       slave_present = 1;
reg [6:0] slave_addr = 7'h1A;
integer   nack_byte = -1;       // -1 ACK all, 0/1/2 reject the selected byte
always @(negedge sda) if (scl) begin active = 1; ibit = 0; addressed = 0; byte_index = 0; end
always @(posedge sda) if (scl) active = 0;
always @(posedge scl) if (active && ibit < 8) begin sh = {sh[6:0], sda}; ibit = ibit + 1; end
always @(negedge scl) if (active) begin
    if (ibit == 8) begin
        ibytes[nbytes] = sh; nbytes = nbytes + 1;
        if (byte_index == 0) addressed = slave_present && (sh == {slave_addr, 1'b0});
        if (addressed && byte_index != nack_byte) sda_pull <= #20 1;
        ibit = 9;
    end else if (ibit == 9) begin sda_pull <= #20 0; ibit = 0; byte_index = byte_index + 1; end
end

// ---------------------------------------------------------------- test
integer before_bytes, before_edges, polls;
reg [31:0] v, before_count;
reg [15:0] samples [0:399];
initial begin
    for (i = 0; i < 400; i = i + 1) samples[i] = (i * 16'd2749) ^ 16'h5a3c;
    // UNISIM primitives observe the global startup reset for the first 100 ns.
    #200 aresetn = 1;
    rd(16'h0000, v); if (v != 32'h41554431) begin fails = fails + 1; $display("ID %h", v); end
    rd(16'h0028, v); if (v !== 3) begin fails = fails + 1; $display("CAPS %h", v); end
    rd(16'h0024, v); if (v !== 0) begin fails = fails + 1; $display("reset count %h", v); end
    rd(16'h000C, v); if (v[19] !== 1'b1 || v[20] !== 1'b0) begin fails = fails + 1; $display("idle SDA %h", v); end
    // I2C write to the codec: R15 reset = {0x1E, 0x00}
    i2c_transaction({8'h00, 8'h00, 8'h1E, 1'b0, 7'h1A}, 0, 0);
    if (nbytes != 3 || ibytes[0] !== 8'h34 || ibytes[1] !== 8'h1E || ibytes[2] !== 8'h00) begin
        fails = fails + 1; $display("I2C nack=%0d n=%0d %h %h %h", v[17], nbytes, ibytes[0], ibytes[1], ibytes[2]);
    end
    $display("stage legacy I2C write done %t n=%0d", $time, nbytes);
    // wrong address must report NACK
    i2c_transaction({8'h00, 8'h12, 8'h34, 1'b0, 7'h22}, 1, 0);
    // Device absent and every possible byte-level NACK must stay visible until done.
    slave_present = 0;
    i2c_transaction(32'h00001E1A, 1, 0);
    slave_present = 1;
    for (i = 0; i < 3; i = i + 1) begin
        nack_byte = i;
        i2c_transaction(32'h00A55A1A, 1, 0);
    end
    nack_byte = -1;
    $display("stage absent device and three byte NACK cases done %t", $time);
    // A shorted idle bus must be rejected without START/SCL activity, then recover.
    force_sda_low = 1; repeat (8) @(posedge aclk);
    before_bytes = nbytes; before_edges = scl_edges;
    rd(16'h000C, v); if (v[19] !== 1'b0) begin fails = fails + 1; $display("SDA stuck not observable"); end
    i2c_transaction(32'h0100001A, 1, 1);
    if (nbytes != before_bytes || scl_edges != before_edges) begin fails = fails + 1; $display("stuck bus was clocked"); end
    force_sda_low = 0; repeat (8) @(posedge aclk);
    i2c_transaction(32'h00001E1A, 0, 0);
    $display("stage stuck SDA rejection and recovery done %t", $time);
    // Address-only probes must never send the two payload bytes, for any outcome.
    before_bytes = nbytes;
    i2c_transaction(32'h01A55A1A, 0, 0);
    if (nbytes != before_bytes + 1 || ibytes[before_bytes] !== 8'h34) begin fails = fails + 1; $display("probe sent payload"); end
    before_bytes = nbytes;
    i2c_transaction(32'h01000022, 1, 0);
    if (nbytes != before_bytes + 1 || ibytes[before_bytes] !== 8'h44) begin fails = fails + 1; $display("negative probe length"); end
    slave_addr = 7'h10; before_bytes = nbytes;
    i2c_transaction(32'h01000010, 0, 0);
    if (nbytes != before_bytes + 1 || ibytes[before_bytes] !== 8'h20) begin fails = fails + 1; $display("0x10 probe packing"); end
    slave_addr = 7'h11; before_bytes = nbytes;
    i2c_transaction(32'h01000011, 0, 0);
    if (nbytes != before_bytes + 1 || ibytes[before_bytes] !== 8'h22) begin fails = fails + 1; $display("0x11 probe packing"); end
    slave_addr = 7'h1A;
    $display("stage address-only probes done %t", $time);
    // Back-to-back MMIO writes without polling: AXI backpressure must keep both.
    rd(16'h0024, before_count); before_bytes = nbytes;
    wr(16'h0010, 32'h0012341A);
    wr(16'h0010, 32'h0056781A);
    v = before_count; polls = 0;
    while (v != before_count + 2 && polls < 10000) begin rd(16'h0024, v); polls = polls + 1; end
    if (v !== before_count + 2 || nbytes != before_bytes + 6 ||
        ibytes[before_bytes + 1] !== 8'h34 || ibytes[before_bytes + 2] !== 8'h12 ||
        ibytes[before_bytes + 4] !== 8'h78 || ibytes[before_bytes + 5] !== 8'h56) begin
        fails = fails + 1; $display("back-to-back commands lost count=%h bytes=%d", v, nbytes-before_bytes);
    end
    rd(16'h000C, v); if (v[20:19] !== 2'b01 || v[17:16] !== 2'b00) begin fails = fails + 1; $display("final I2C status %h", v); end
    $display("stage continuous commands done %t", $time);
    // queue 400 samples (two per write) and play
    for (i = 0; i < 400; i = i + 2) wr(16'h1000 + (i % 64) * 2, {samples[i + 1], samples[i]});
    rd(16'h000C, v); if (v[14:0] != 400) begin fails = fails + 1; $display("level %0d", v[14:0]); end
    $display("stage queued %t lvl=%0d nL=%0d", $time, v[14:0], nL);
    first = nL;
    wr(16'h0008, 32'h5);                               // enable + MCLK
    wait (nL >= first + 420);
    // locate the first played sample, then compare the run
    while (first < nL && capL[first] != samples[0]) first = first + 1;
    firstR = 0;
    while (firstR < nR && capR[firstR] != samples[0]) firstR = firstR + 1;
    for (i = 0; i < 400; i = i + 1)
        if (capL[first + i] !== samples[i] || capR[firstR + i] !== samples[i]) begin
            if (fails < 20) $display("sample %0d L %h R %h want %h", i, capL[first + i], capR[firstR + i], samples[i]);
            fails = fails + 1;
        end
    if (capL[first + 400] !== 16'h0000) begin fails = fails + 1; $display("no silence after drain"); end
    rd(16'h0014, v); if (v == 0) begin fails = fails + 1; $display("underrun not counted"); end
    rd(16'h0018, v); if (v < 400) begin fails = fails + 1; $display("frames %0d", v); end
    // clear: queue, clear, nothing plays
    for (i = 0; i < 20; i = i + 2) wr(16'h1000, 32'h7fff7fff);
    wr(16'h0008, 32'h7);
    repeat (20) @(posedge aclk);
    rd(16'h000C, v); if (v[14:0] != 0) begin fails = fails + 1; $display("clear left %0d", v[14:0]); end
    if (fails) $display("TB_FAIL %0d", fails); else $display("TB_PASS");
    $finish;
end
initial begin #80_000_000; $display("TIMEOUT"); $finish; end
endmodule
