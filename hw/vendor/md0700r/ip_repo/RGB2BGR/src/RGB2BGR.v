`timescale 1ns / 1ps

module RGB2BGR(
    input [23:0] video_din,      // RGB888 video in
    input        video_hsync,    // hsync data
    input        video_vsync,    // vsync data
    input        video_de,       // data enable
    
    output [23:0] video_out,      // BGR888 video out
    output        video_hsync_o,  // hsync data
    output        video_vsync_o,  // vsync data
    output        video_de_o      // data enable
    );
    
    assign video_out = {video_din[7:0],video_din[15:8],video_din[23:16]};
    assign video_hsync_o = video_hsync;
    assign video_vsync_o = video_vsync;
    assign video_de_o = video_de;
    
endmodule
