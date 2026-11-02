`timescale 1ns/1ps
module tb_touch_packet;
reg clk=0,rst_n=0;
always #5 clk=~clk;
wire [63:0] diagnostic;
wire [31:0] touch_packet,data;
wire [6:0] slave_addr;
wire i2c_exec,i2c_rh_wl,bit_ctrl,touch_rst_n;
wire [15:0] i2c_addr;
wire [7:0] i2c_data_w,reg_num;
tri touch_int;
reg [7:0] i2c_data_r=0;
reg i2c_ack=0,i2c_done=0,once_byte_done=0,bus_busy=0;
integer reads=0,clears=0,status_reads=0;
always @(posedge i2c_exec) if(bus_busy) $fatal(1,"Overlapping bus transactions");
touch_dri dut(.diagnostic(diagnostic),.touch_packet(touch_packet),.clk(clk),.rst_n(rst_n),.slave_addr(slave_addr),.i2c_exec(i2c_exec),.i2c_rh_wl(i2c_rh_wl),.i2c_addr(i2c_addr),.i2c_data_w(i2c_data_w),.bit_ctrl(bit_ctrl),.reg_num(reg_num),.i2c_data_r(i2c_data_r),.i2c_ack(i2c_ack),.i2c_done(i2c_done),.once_byte_done(once_byte_done),.lcd_id(16'h7016),.data(data),.touch_rst_n(touch_rst_n),.touch_int(touch_int));
task send_byte(input [7:0] b);
 begin @(negedge clk);i2c_data_r=b;once_byte_done=1;@(negedge clk);once_byte_done=0;end
endtask
initial begin #40;@(negedge clk);rst_n=1;end
initial forever begin
 @(posedge i2c_exec);#1;bus_busy=1;
 if(slave_addr!==7'h14 || bit_ctrl!==1) $fatal(1,"Wrong GT911 address");
 if(i2c_addr==16'h814e && i2c_rh_wl) begin
  @(negedge clk);i2c_data_r=(status_reads%2==0)?8'h81:8'h80;
  status_reads=status_reads+1;i2c_done=1;bus_busy=0;
  @(negedge clk);i2c_done=0;
 end else if(i2c_addr==16'h8150 && i2c_rh_wl && reg_num==4) begin
  if(reads==0) begin send_byte(8'h34);send_byte(8'h01);send_byte(8'h56);send_byte(8'h00);end
  else begin send_byte(8'h90);send_byte(8'h01);send_byte(8'hc8);send_byte(8'h00);end
  reads=reads+1;repeat(10) @(negedge clk);i2c_done=1;bus_busy=0;
  @(negedge clk);i2c_done=0;
 end else if(i2c_addr==16'h814e && !i2c_rh_wl && i2c_data_w==0) begin
  if(reads==0) $fatal(1,"Early acknowledgement");
  clears=clears+1;
  @(negedge clk);i2c_done=1;bus_busy=0;
  @(negedge clk);i2c_done=0;repeat(8) @(negedge clk);
  if(touch_packet[31:22]!==clears || !touch_packet[20]) $fatal(1,"Packet sequence/valid incorrect: %h",touch_packet);
  if(touch_packet[21] !== (clears%2==1)) $fatal(1,"Press/release state incorrect");
  if(clears<=2 && (touch_packet[19:10]!=308 || touch_packet[9:0]!=86)) $fatal(1,"First point incorrect");
  if(clears>=3 && (touch_packet[19:10]!=400 || touch_packet[9:0]!=200)) $fatal(1,"Second point incorrect");
  if(clears==4) begin $display("TOUCH_PACKET_SIM_PASS press1 release1 press2 release2");$finish;end
 end else $fatal(1,"Unexpected transfer");
end
initial begin #2000000;$fatal(1,"Timeout");end
endmodule
