`timescale 1ns/1ps
// Drives brush_cam with an OV7725-like DVP stream of frame.hex (640x480 RGB565),
// waits for SCCB init and a few frames, freezes, and dumps registers plus the
// binary and preview BRAMs through AXI4-Lite into dump.txt for tools/check_brush_cam.py.
module tb_brush_cam;
reg aclk = 0, pclk = 0, aresetn = 0;
always #5 aclk = ~aclk;          // 100 MHz
always #20.833 pclk = ~pclk;     // 24 MHz

reg  [16:0] awaddr = 0, araddr = 0;
reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
reg  [31:0] wdata = 0;
wire        awready, wready, bvalid, arready, rvalid;
wire [31:0] rdata;
wire [1:0]  bresp, rresp;
reg         vsync = 0, href = 0;
reg  [7:0]  data = 0;
wire        scl, rst_n, sgm;
wire        sda;
pullup(sda);

brush_cam #(.SCL_HZ(5000000), .SKIP_FRAMES(1), .BOOT_DELAY(100), .RESET_DELAY(100)) dut (
    .s_axi_aclk(aclk), .s_axi_aresetn(aresetn),
    .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
    .s_axi_wdata(wdata), .s_axi_wstrb(4'hf), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
    .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
    .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
    .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
    .cam_pclk(pclk), .cam_vsync(vsync), .cam_href(href), .cam_data(data),
    .cam_rst_n(rst_n), .cam_sgm_ctrl(sgm), .cam_scl(scl), .cam_sda(sda));

task axi_write(input [16:0] a, input [31:0] d);
    begin
        @(posedge aclk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
        @(posedge aclk); while (!(awready && wready)) @(posedge aclk);
        awvalid <= 0; wvalid <= 0;
        while (!bvalid) @(posedge aclk);
        @(posedge aclk);
    end
endtask
task axi_read(input [16:0] a, output [31:0] d);
    begin
        @(posedge aclk); araddr <= a; arvalid <= 1;
        @(posedge aclk); while (!arready) @(posedge aclk);
        arvalid <= 0;
        while (!rvalid) @(posedge aclk);
        d = rdata;
        @(posedge aclk);
    end
endtask

// ----------------------------------------------------------- camera model
reg [15:0] img [0:307199];
integer frames_sent = 0;
integer x, y;
initial $readmemh("frame.hex", img);
initial begin
    #2000;
    forever begin
        @(posedge pclk) vsync <= 1;
        repeat (2 * 1320) @(posedge pclk);
        vsync <= 0;
        repeat (3 * 1320) @(posedge pclk);
        for (y = 0; y < 480; y = y + 1) begin
            for (x = 0; x < 640; x = x + 1) begin
                @(negedge pclk) begin href <= 1; data <= img[y*640+x][15:8]; end
                @(negedge pclk) data <= img[y*640+x][7:0];
            end
            @(negedge pclk) begin href <= 0; data <= 8'h00; end
            repeat (39) @(negedge pclk);
        end
        repeat (2 * 1320) @(posedge pclk);
        frames_sent = frames_sent + 1;
    end
end

// ----------------------------------------------------------- test sequence
integer fd, i;
reg [31:0] v, st;
initial begin
    #100 aresetn = 1;
    axi_read(17'h00000, v); $display("ID %h", v);
    // wait for SCCB table
    st = 0;
    while (!st[0]) begin #20000; axi_read(17'h00040, st); end
    $display("SCCB done at %t status %h", $time, st);
    axi_write(17'h0000c, 32'h0000_0050);       // manual threshold 80, bias 0 (Otsu enabled by default)
    axi_write(17'h00010, {6'd0, 10'd600, 6'd0, 10'd40});   // ROI x 40..600
    axi_write(17'h00014, {7'd0, 9'd440, 7'd0, 9'd40});     // ROI y 40..440
    axi_write(17'h00020, 32'h0000_1300);       // a user SCCB write
    wait (frames_sent == 5);
    axi_write(17'h00008, 32'h0000_6903);       // freeze
    st = 0;
    while (!st[1]) begin #100000; axi_read(17'h00040, st); end
    wait (frames_sent == 6);                    // frozen BRAM must survive another frame
    fd = $fopen("dump.txt", "w");
    for (i = 0; i < 24; i = i + 1) begin axi_read(i * 4, v); $fdisplay(fd, "R %0d %h", i * 4, v); end
    for (i = 0; i < 9600; i = i + 1) begin axi_read(17'h10000 + i * 4, v); $fdisplay(fd, "B %h", v); end
    for (i = 0; i < 4800; i = i + 1) begin axi_read(17'h1A000 + i * 4, v); $fdisplay(fd, "P %h", v); end
    $fclose(fd);
    $display("DONE frames=%0d", frames_sent);
    $finish;
end
initial begin #400_000_000; $display("TIMEOUT"); $finish; end
endmodule
