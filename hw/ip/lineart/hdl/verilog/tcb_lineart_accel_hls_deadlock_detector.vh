
    wire dl_reset;
    wire dl_clock;
    assign dl_reset = ap_rst_n;
    assign dl_clock = ap_clk;
    wire [2:0] proc_0_data_FIFO_blk;
    wire [2:0] proc_0_data_PIPO_blk;
    wire [2:0] proc_0_start_FIFO_blk;
    wire [2:0] proc_0_TLF_FIFO_blk;
    wire [2:0] proc_0_input_sync_blk;
    wire [2:0] proc_0_output_sync_blk;
    wire [2:0] proc_dep_vld_vec_0;
    reg [2:0] proc_dep_vld_vec_0_reg;
    wire [2:0] in_chan_dep_vld_vec_0;
    wire [32:0] in_chan_dep_data_vec_0;
    wire [2:0] token_in_vec_0;
    wire [2:0] out_chan_dep_vld_vec_0;
    wire [10:0] out_chan_dep_data_0;
    wire [2:0] token_out_vec_0;
    wire dl_detect_out_0;
    wire dep_chan_vld_1_0;
    wire [10:0] dep_chan_data_1_0;
    wire token_1_0;
    wire dep_chan_vld_2_0;
    wire [10:0] dep_chan_data_2_0;
    wire token_2_0;
    wire dep_chan_vld_10_0;
    wire [10:0] dep_chan_data_10_0;
    wire token_10_0;
    wire [2:0] proc_1_data_FIFO_blk;
    wire [2:0] proc_1_data_PIPO_blk;
    wire [2:0] proc_1_start_FIFO_blk;
    wire [2:0] proc_1_TLF_FIFO_blk;
    wire [2:0] proc_1_input_sync_blk;
    wire [2:0] proc_1_output_sync_blk;
    wire [2:0] proc_dep_vld_vec_1;
    reg [2:0] proc_dep_vld_vec_1_reg;
    wire [2:0] in_chan_dep_vld_vec_1;
    wire [32:0] in_chan_dep_data_vec_1;
    wire [2:0] token_in_vec_1;
    wire [2:0] out_chan_dep_vld_vec_1;
    wire [10:0] out_chan_dep_data_1;
    wire [2:0] token_out_vec_1;
    wire dl_detect_out_1;
    wire dep_chan_vld_0_1;
    wire [10:0] dep_chan_data_0_1;
    wire token_0_1;
    wire dep_chan_vld_2_1;
    wire [10:0] dep_chan_data_2_1;
    wire token_2_1;
    wire dep_chan_vld_10_1;
    wire [10:0] dep_chan_data_10_1;
    wire token_10_1;
    wire [9:0] proc_2_data_FIFO_blk;
    wire [9:0] proc_2_data_PIPO_blk;
    wire [9:0] proc_2_start_FIFO_blk;
    wire [9:0] proc_2_TLF_FIFO_blk;
    wire [9:0] proc_2_input_sync_blk;
    wire [9:0] proc_2_output_sync_blk;
    wire [9:0] proc_dep_vld_vec_2;
    reg [9:0] proc_dep_vld_vec_2_reg;
    wire [9:0] in_chan_dep_vld_vec_2;
    wire [109:0] in_chan_dep_data_vec_2;
    wire [9:0] token_in_vec_2;
    wire [9:0] out_chan_dep_vld_vec_2;
    wire [10:0] out_chan_dep_data_2;
    wire [9:0] token_out_vec_2;
    wire dl_detect_out_2;
    wire dep_chan_vld_0_2;
    wire [10:0] dep_chan_data_0_2;
    wire token_0_2;
    wire dep_chan_vld_1_2;
    wire [10:0] dep_chan_data_1_2;
    wire token_1_2;
    wire dep_chan_vld_3_2;
    wire [10:0] dep_chan_data_3_2;
    wire token_3_2;
    wire dep_chan_vld_4_2;
    wire [10:0] dep_chan_data_4_2;
    wire token_4_2;
    wire dep_chan_vld_5_2;
    wire [10:0] dep_chan_data_5_2;
    wire token_5_2;
    wire dep_chan_vld_6_2;
    wire [10:0] dep_chan_data_6_2;
    wire token_6_2;
    wire dep_chan_vld_7_2;
    wire [10:0] dep_chan_data_7_2;
    wire token_7_2;
    wire dep_chan_vld_8_2;
    wire [10:0] dep_chan_data_8_2;
    wire token_8_2;
    wire dep_chan_vld_9_2;
    wire [10:0] dep_chan_data_9_2;
    wire token_9_2;
    wire dep_chan_vld_10_2;
    wire [10:0] dep_chan_data_10_2;
    wire token_10_2;
    wire [7:0] proc_3_data_FIFO_blk;
    wire [7:0] proc_3_data_PIPO_blk;
    wire [7:0] proc_3_start_FIFO_blk;
    wire [7:0] proc_3_TLF_FIFO_blk;
    wire [7:0] proc_3_input_sync_blk;
    wire [7:0] proc_3_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_3;
    reg [7:0] proc_dep_vld_vec_3_reg;
    wire [7:0] in_chan_dep_vld_vec_3;
    wire [87:0] in_chan_dep_data_vec_3;
    wire [7:0] token_in_vec_3;
    wire [7:0] out_chan_dep_vld_vec_3;
    wire [10:0] out_chan_dep_data_3;
    wire [7:0] token_out_vec_3;
    wire dl_detect_out_3;
    wire dep_chan_vld_2_3;
    wire [10:0] dep_chan_data_2_3;
    wire token_2_3;
    wire dep_chan_vld_4_3;
    wire [10:0] dep_chan_data_4_3;
    wire token_4_3;
    wire dep_chan_vld_5_3;
    wire [10:0] dep_chan_data_5_3;
    wire token_5_3;
    wire dep_chan_vld_6_3;
    wire [10:0] dep_chan_data_6_3;
    wire token_6_3;
    wire dep_chan_vld_7_3;
    wire [10:0] dep_chan_data_7_3;
    wire token_7_3;
    wire dep_chan_vld_8_3;
    wire [10:0] dep_chan_data_8_3;
    wire token_8_3;
    wire dep_chan_vld_9_3;
    wire [10:0] dep_chan_data_9_3;
    wire token_9_3;
    wire dep_chan_vld_10_3;
    wire [10:0] dep_chan_data_10_3;
    wire token_10_3;
    wire [7:0] proc_4_data_FIFO_blk;
    wire [7:0] proc_4_data_PIPO_blk;
    wire [7:0] proc_4_start_FIFO_blk;
    wire [7:0] proc_4_TLF_FIFO_blk;
    wire [7:0] proc_4_input_sync_blk;
    wire [7:0] proc_4_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_4;
    reg [7:0] proc_dep_vld_vec_4_reg;
    wire [7:0] in_chan_dep_vld_vec_4;
    wire [87:0] in_chan_dep_data_vec_4;
    wire [7:0] token_in_vec_4;
    wire [7:0] out_chan_dep_vld_vec_4;
    wire [10:0] out_chan_dep_data_4;
    wire [7:0] token_out_vec_4;
    wire dl_detect_out_4;
    wire dep_chan_vld_2_4;
    wire [10:0] dep_chan_data_2_4;
    wire token_2_4;
    wire dep_chan_vld_3_4;
    wire [10:0] dep_chan_data_3_4;
    wire token_3_4;
    wire dep_chan_vld_5_4;
    wire [10:0] dep_chan_data_5_4;
    wire token_5_4;
    wire dep_chan_vld_6_4;
    wire [10:0] dep_chan_data_6_4;
    wire token_6_4;
    wire dep_chan_vld_7_4;
    wire [10:0] dep_chan_data_7_4;
    wire token_7_4;
    wire dep_chan_vld_8_4;
    wire [10:0] dep_chan_data_8_4;
    wire token_8_4;
    wire dep_chan_vld_9_4;
    wire [10:0] dep_chan_data_9_4;
    wire token_9_4;
    wire dep_chan_vld_10_4;
    wire [10:0] dep_chan_data_10_4;
    wire token_10_4;
    wire [7:0] proc_5_data_FIFO_blk;
    wire [7:0] proc_5_data_PIPO_blk;
    wire [7:0] proc_5_start_FIFO_blk;
    wire [7:0] proc_5_TLF_FIFO_blk;
    wire [7:0] proc_5_input_sync_blk;
    wire [7:0] proc_5_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_5;
    reg [7:0] proc_dep_vld_vec_5_reg;
    wire [7:0] in_chan_dep_vld_vec_5;
    wire [87:0] in_chan_dep_data_vec_5;
    wire [7:0] token_in_vec_5;
    wire [7:0] out_chan_dep_vld_vec_5;
    wire [10:0] out_chan_dep_data_5;
    wire [7:0] token_out_vec_5;
    wire dl_detect_out_5;
    wire dep_chan_vld_2_5;
    wire [10:0] dep_chan_data_2_5;
    wire token_2_5;
    wire dep_chan_vld_3_5;
    wire [10:0] dep_chan_data_3_5;
    wire token_3_5;
    wire dep_chan_vld_4_5;
    wire [10:0] dep_chan_data_4_5;
    wire token_4_5;
    wire dep_chan_vld_6_5;
    wire [10:0] dep_chan_data_6_5;
    wire token_6_5;
    wire dep_chan_vld_7_5;
    wire [10:0] dep_chan_data_7_5;
    wire token_7_5;
    wire dep_chan_vld_8_5;
    wire [10:0] dep_chan_data_8_5;
    wire token_8_5;
    wire dep_chan_vld_9_5;
    wire [10:0] dep_chan_data_9_5;
    wire token_9_5;
    wire dep_chan_vld_10_5;
    wire [10:0] dep_chan_data_10_5;
    wire token_10_5;
    wire [7:0] proc_6_data_FIFO_blk;
    wire [7:0] proc_6_data_PIPO_blk;
    wire [7:0] proc_6_start_FIFO_blk;
    wire [7:0] proc_6_TLF_FIFO_blk;
    wire [7:0] proc_6_input_sync_blk;
    wire [7:0] proc_6_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_6;
    reg [7:0] proc_dep_vld_vec_6_reg;
    wire [7:0] in_chan_dep_vld_vec_6;
    wire [87:0] in_chan_dep_data_vec_6;
    wire [7:0] token_in_vec_6;
    wire [7:0] out_chan_dep_vld_vec_6;
    wire [10:0] out_chan_dep_data_6;
    wire [7:0] token_out_vec_6;
    wire dl_detect_out_6;
    wire dep_chan_vld_2_6;
    wire [10:0] dep_chan_data_2_6;
    wire token_2_6;
    wire dep_chan_vld_3_6;
    wire [10:0] dep_chan_data_3_6;
    wire token_3_6;
    wire dep_chan_vld_4_6;
    wire [10:0] dep_chan_data_4_6;
    wire token_4_6;
    wire dep_chan_vld_5_6;
    wire [10:0] dep_chan_data_5_6;
    wire token_5_6;
    wire dep_chan_vld_7_6;
    wire [10:0] dep_chan_data_7_6;
    wire token_7_6;
    wire dep_chan_vld_8_6;
    wire [10:0] dep_chan_data_8_6;
    wire token_8_6;
    wire dep_chan_vld_9_6;
    wire [10:0] dep_chan_data_9_6;
    wire token_9_6;
    wire dep_chan_vld_10_6;
    wire [10:0] dep_chan_data_10_6;
    wire token_10_6;
    wire [7:0] proc_7_data_FIFO_blk;
    wire [7:0] proc_7_data_PIPO_blk;
    wire [7:0] proc_7_start_FIFO_blk;
    wire [7:0] proc_7_TLF_FIFO_blk;
    wire [7:0] proc_7_input_sync_blk;
    wire [7:0] proc_7_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_7;
    reg [7:0] proc_dep_vld_vec_7_reg;
    wire [7:0] in_chan_dep_vld_vec_7;
    wire [87:0] in_chan_dep_data_vec_7;
    wire [7:0] token_in_vec_7;
    wire [7:0] out_chan_dep_vld_vec_7;
    wire [10:0] out_chan_dep_data_7;
    wire [7:0] token_out_vec_7;
    wire dl_detect_out_7;
    wire dep_chan_vld_2_7;
    wire [10:0] dep_chan_data_2_7;
    wire token_2_7;
    wire dep_chan_vld_3_7;
    wire [10:0] dep_chan_data_3_7;
    wire token_3_7;
    wire dep_chan_vld_4_7;
    wire [10:0] dep_chan_data_4_7;
    wire token_4_7;
    wire dep_chan_vld_5_7;
    wire [10:0] dep_chan_data_5_7;
    wire token_5_7;
    wire dep_chan_vld_6_7;
    wire [10:0] dep_chan_data_6_7;
    wire token_6_7;
    wire dep_chan_vld_8_7;
    wire [10:0] dep_chan_data_8_7;
    wire token_8_7;
    wire dep_chan_vld_9_7;
    wire [10:0] dep_chan_data_9_7;
    wire token_9_7;
    wire dep_chan_vld_10_7;
    wire [10:0] dep_chan_data_10_7;
    wire token_10_7;
    wire [7:0] proc_8_data_FIFO_blk;
    wire [7:0] proc_8_data_PIPO_blk;
    wire [7:0] proc_8_start_FIFO_blk;
    wire [7:0] proc_8_TLF_FIFO_blk;
    wire [7:0] proc_8_input_sync_blk;
    wire [7:0] proc_8_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_8;
    reg [7:0] proc_dep_vld_vec_8_reg;
    wire [7:0] in_chan_dep_vld_vec_8;
    wire [87:0] in_chan_dep_data_vec_8;
    wire [7:0] token_in_vec_8;
    wire [7:0] out_chan_dep_vld_vec_8;
    wire [10:0] out_chan_dep_data_8;
    wire [7:0] token_out_vec_8;
    wire dl_detect_out_8;
    wire dep_chan_vld_2_8;
    wire [10:0] dep_chan_data_2_8;
    wire token_2_8;
    wire dep_chan_vld_3_8;
    wire [10:0] dep_chan_data_3_8;
    wire token_3_8;
    wire dep_chan_vld_4_8;
    wire [10:0] dep_chan_data_4_8;
    wire token_4_8;
    wire dep_chan_vld_5_8;
    wire [10:0] dep_chan_data_5_8;
    wire token_5_8;
    wire dep_chan_vld_6_8;
    wire [10:0] dep_chan_data_6_8;
    wire token_6_8;
    wire dep_chan_vld_7_8;
    wire [10:0] dep_chan_data_7_8;
    wire token_7_8;
    wire dep_chan_vld_9_8;
    wire [10:0] dep_chan_data_9_8;
    wire token_9_8;
    wire dep_chan_vld_10_8;
    wire [10:0] dep_chan_data_10_8;
    wire token_10_8;
    wire [7:0] proc_9_data_FIFO_blk;
    wire [7:0] proc_9_data_PIPO_blk;
    wire [7:0] proc_9_start_FIFO_blk;
    wire [7:0] proc_9_TLF_FIFO_blk;
    wire [7:0] proc_9_input_sync_blk;
    wire [7:0] proc_9_output_sync_blk;
    wire [7:0] proc_dep_vld_vec_9;
    reg [7:0] proc_dep_vld_vec_9_reg;
    wire [7:0] in_chan_dep_vld_vec_9;
    wire [87:0] in_chan_dep_data_vec_9;
    wire [7:0] token_in_vec_9;
    wire [7:0] out_chan_dep_vld_vec_9;
    wire [10:0] out_chan_dep_data_9;
    wire [7:0] token_out_vec_9;
    wire dl_detect_out_9;
    wire dep_chan_vld_2_9;
    wire [10:0] dep_chan_data_2_9;
    wire token_2_9;
    wire dep_chan_vld_3_9;
    wire [10:0] dep_chan_data_3_9;
    wire token_3_9;
    wire dep_chan_vld_4_9;
    wire [10:0] dep_chan_data_4_9;
    wire token_4_9;
    wire dep_chan_vld_5_9;
    wire [10:0] dep_chan_data_5_9;
    wire token_5_9;
    wire dep_chan_vld_6_9;
    wire [10:0] dep_chan_data_6_9;
    wire token_6_9;
    wire dep_chan_vld_7_9;
    wire [10:0] dep_chan_data_7_9;
    wire token_7_9;
    wire dep_chan_vld_8_9;
    wire [10:0] dep_chan_data_8_9;
    wire token_8_9;
    wire dep_chan_vld_10_9;
    wire [10:0] dep_chan_data_10_9;
    wire token_10_9;
    wire [9:0] proc_10_data_FIFO_blk;
    wire [9:0] proc_10_data_PIPO_blk;
    wire [9:0] proc_10_start_FIFO_blk;
    wire [9:0] proc_10_TLF_FIFO_blk;
    wire [9:0] proc_10_input_sync_blk;
    wire [9:0] proc_10_output_sync_blk;
    wire [9:0] proc_dep_vld_vec_10;
    reg [9:0] proc_dep_vld_vec_10_reg;
    wire [9:0] in_chan_dep_vld_vec_10;
    wire [109:0] in_chan_dep_data_vec_10;
    wire [9:0] token_in_vec_10;
    wire [9:0] out_chan_dep_vld_vec_10;
    wire [10:0] out_chan_dep_data_10;
    wire [9:0] token_out_vec_10;
    wire dl_detect_out_10;
    wire dep_chan_vld_0_10;
    wire [10:0] dep_chan_data_0_10;
    wire token_0_10;
    wire dep_chan_vld_1_10;
    wire [10:0] dep_chan_data_1_10;
    wire token_1_10;
    wire dep_chan_vld_2_10;
    wire [10:0] dep_chan_data_2_10;
    wire token_2_10;
    wire dep_chan_vld_3_10;
    wire [10:0] dep_chan_data_3_10;
    wire token_3_10;
    wire dep_chan_vld_4_10;
    wire [10:0] dep_chan_data_4_10;
    wire token_4_10;
    wire dep_chan_vld_5_10;
    wire [10:0] dep_chan_data_5_10;
    wire token_5_10;
    wire dep_chan_vld_6_10;
    wire [10:0] dep_chan_data_6_10;
    wire token_6_10;
    wire dep_chan_vld_7_10;
    wire [10:0] dep_chan_data_7_10;
    wire token_7_10;
    wire dep_chan_vld_8_10;
    wire [10:0] dep_chan_data_8_10;
    wire token_8_10;
    wire dep_chan_vld_9_10;
    wire [10:0] dep_chan_data_9_10;
    wire token_9_10;
    wire [10:0] dl_in_vec;
    wire dl_detect_out;
    wire token_clear;
    reg [10:0] origin;

    reg ap_done_reg_0;// for module grp_cascade_fu_231.thin_stage_0_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_0 <= 'b0;
        end
        else begin
            ap_done_reg_0 <= grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_continue;
        end
    end

    reg ap_done_reg_1;// for module grp_cascade_fu_231.thin_stage_1_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_1 <= 'b0;
        end
        else begin
            ap_done_reg_1 <= grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_continue;
        end
    end

    reg ap_done_reg_2;// for module grp_cascade_fu_231.thin_stage_2_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_2 <= 'b0;
        end
        else begin
            ap_done_reg_2 <= grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_continue;
        end
    end

    reg ap_done_reg_3;// for module grp_cascade_fu_231.thin_stage_3_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_3 <= 'b0;
        end
        else begin
            ap_done_reg_3 <= grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_continue;
        end
    end

    reg ap_done_reg_4;// for module grp_cascade_fu_231.thin_stage_4_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_4 <= 'b0;
        end
        else begin
            ap_done_reg_4 <= grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_continue;
        end
    end

    reg ap_done_reg_5;// for module grp_cascade_fu_231.thin_stage_5_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_5 <= 'b0;
        end
        else begin
            ap_done_reg_5 <= grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_continue;
        end
    end

    reg ap_done_reg_6;// for module grp_cascade_fu_231.thin_stage_6_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_6 <= 'b0;
        end
        else begin
            ap_done_reg_6 <= grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_continue;
        end
    end

    reg ap_done_reg_7;// for module grp_cascade_fu_231.thin_stage_7_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_7 <= 'b0;
        end
        else begin
            ap_done_reg_7 <= grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_continue;
        end
    end

    reg ap_done_reg_8;// for module grp_cascade_fu_231.pack_U0
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            ap_done_reg_8 <= 'b0;
        end
        else begin
            ap_done_reg_8 <= grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_continue;
        end
    end

    // Process: grp_cascade_fu_231.entry_proc_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 0, 3, 3) tcb_lineart_accel_hls_deadlock_detect_unit_0 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_0),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_0),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_0),
        .token_in_vec(token_in_vec_0),
        .dl_detect_in(dl_detect_out),
        .origin(origin[0]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_0),
        .out_chan_dep_data(out_chan_dep_data_0),
        .token_out_vec(token_out_vec_0),
        .dl_detect_out(dl_in_vec[0]));

    assign proc_0_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.entry_proc_U0.dst_c_blk_n);
    assign proc_0_data_PIPO_blk[0] = 1'b0;
    assign proc_0_start_FIFO_blk[0] = 1'b0;
    assign proc_0_TLF_FIFO_blk[0] = 1'b0;
    assign proc_0_input_sync_blk[0] = 1'b0;
    assign proc_0_output_sync_blk[0] = 1'b0;
    assign proc_dep_vld_vec_0[0] = dl_detect_out ? proc_dep_vld_vec_0_reg[0] : (proc_0_data_FIFO_blk[0] | proc_0_data_PIPO_blk[0] | proc_0_start_FIFO_blk[0] | proc_0_TLF_FIFO_blk[0] | proc_0_input_sync_blk[0] | proc_0_output_sync_blk[0]);
    assign proc_0_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.entry_proc_U0.w_c7_blk_n) | (~grp_cascade_fu_231.entry_proc_U0.h_c14_blk_n);
    assign proc_0_data_PIPO_blk[1] = 1'b0;
    assign proc_0_start_FIFO_blk[1] = 1'b0;
    assign proc_0_TLF_FIFO_blk[1] = 1'b0;
    assign proc_0_input_sync_blk[1] = 1'b0;
    assign proc_0_output_sync_blk[1] = 1'b0;
    assign proc_dep_vld_vec_0[1] = dl_detect_out ? proc_dep_vld_vec_0_reg[1] : (proc_0_data_FIFO_blk[1] | proc_0_data_PIPO_blk[1] | proc_0_start_FIFO_blk[1] | proc_0_TLF_FIFO_blk[1] | proc_0_input_sync_blk[1] | proc_0_output_sync_blk[1]);
    assign proc_0_data_FIFO_blk[2] = 1'b0;
    assign proc_0_data_PIPO_blk[2] = 1'b0;
    assign proc_0_start_FIFO_blk[2] = 1'b0;
    assign proc_0_TLF_FIFO_blk[2] = 1'b0;
    assign proc_0_input_sync_blk[2] = 1'b0 | (grp_cascade_fu_231.ap_sync_entry_proc_U0_ap_ready & grp_cascade_fu_231.entry_proc_U0.ap_idle & ~grp_cascade_fu_231.ap_sync_unpack_U0_ap_ready);
    assign proc_0_output_sync_blk[2] = 1'b0;
    assign proc_dep_vld_vec_0[2] = dl_detect_out ? proc_dep_vld_vec_0_reg[2] : (proc_0_data_FIFO_blk[2] | proc_0_data_PIPO_blk[2] | proc_0_start_FIFO_blk[2] | proc_0_TLF_FIFO_blk[2] | proc_0_input_sync_blk[2] | proc_0_output_sync_blk[2]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_0_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_0_reg <= proc_dep_vld_vec_0;
        end
    end
    assign in_chan_dep_vld_vec_0[0] = dep_chan_vld_1_0;
    assign in_chan_dep_data_vec_0[10 : 0] = dep_chan_data_1_0;
    assign token_in_vec_0[0] = token_1_0;
    assign in_chan_dep_vld_vec_0[1] = dep_chan_vld_2_0;
    assign in_chan_dep_data_vec_0[21 : 11] = dep_chan_data_2_0;
    assign token_in_vec_0[1] = token_2_0;
    assign in_chan_dep_vld_vec_0[2] = dep_chan_vld_10_0;
    assign in_chan_dep_data_vec_0[32 : 22] = dep_chan_data_10_0;
    assign token_in_vec_0[2] = token_10_0;
    assign dep_chan_vld_0_10 = out_chan_dep_vld_vec_0[0];
    assign dep_chan_data_0_10 = out_chan_dep_data_0;
    assign token_0_10 = token_out_vec_0[0];
    assign dep_chan_vld_0_2 = out_chan_dep_vld_vec_0[1];
    assign dep_chan_data_0_2 = out_chan_dep_data_0;
    assign token_0_2 = token_out_vec_0[1];
    assign dep_chan_vld_0_1 = out_chan_dep_vld_vec_0[2];
    assign dep_chan_data_0_1 = out_chan_dep_data_0;
    assign token_0_1 = token_out_vec_0[2];

    // Process: grp_cascade_fu_231.unpack_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 1, 3, 3) tcb_lineart_accel_hls_deadlock_detect_unit_1 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_1),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_1),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_1),
        .token_in_vec(token_in_vec_1),
        .dl_detect_in(dl_detect_out),
        .origin(origin[1]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_1),
        .out_chan_dep_data(out_chan_dep_data_1),
        .token_out_vec(token_out_vec_1),
        .dl_detect_out(dl_in_vec[1]));

    assign proc_1_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.unpack_U0.grp_unpack_Pipeline_VITIS_LOOP_5_1_VITIS_LOOP_7_2_fu_94.s_0_blk_n);
    assign proc_1_data_PIPO_blk[0] = 1'b0;
    assign proc_1_start_FIFO_blk[0] = 1'b0;
    assign proc_1_TLF_FIFO_blk[0] = 1'b0;
    assign proc_1_input_sync_blk[0] = 1'b0;
    assign proc_1_output_sync_blk[0] = 1'b0;
    assign proc_dep_vld_vec_1[0] = dl_detect_out ? proc_dep_vld_vec_1_reg[0] : (proc_1_data_FIFO_blk[0] | proc_1_data_PIPO_blk[0] | proc_1_start_FIFO_blk[0] | proc_1_TLF_FIFO_blk[0] | proc_1_input_sync_blk[0] | proc_1_output_sync_blk[0]);
    assign proc_1_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.unpack_U0.n_c_blk_n);
    assign proc_1_data_PIPO_blk[1] = 1'b0;
    assign proc_1_start_FIFO_blk[1] = 1'b0;
    assign proc_1_TLF_FIFO_blk[1] = 1'b0;
    assign proc_1_input_sync_blk[1] = 1'b0;
    assign proc_1_output_sync_blk[1] = 1'b0;
    assign proc_dep_vld_vec_1[1] = dl_detect_out ? proc_dep_vld_vec_1_reg[1] : (proc_1_data_FIFO_blk[1] | proc_1_data_PIPO_blk[1] | proc_1_start_FIFO_blk[1] | proc_1_TLF_FIFO_blk[1] | proc_1_input_sync_blk[1] | proc_1_output_sync_blk[1]);
    assign proc_1_data_FIFO_blk[2] = 1'b0;
    assign proc_1_data_PIPO_blk[2] = 1'b0;
    assign proc_1_start_FIFO_blk[2] = 1'b0;
    assign proc_1_TLF_FIFO_blk[2] = 1'b0;
    assign proc_1_input_sync_blk[2] = 1'b0 | (grp_cascade_fu_231.ap_sync_unpack_U0_ap_ready & grp_cascade_fu_231.unpack_U0.ap_idle & ~grp_cascade_fu_231.ap_sync_entry_proc_U0_ap_ready);
    assign proc_1_output_sync_blk[2] = 1'b0;
    assign proc_dep_vld_vec_1[2] = dl_detect_out ? proc_dep_vld_vec_1_reg[2] : (proc_1_data_FIFO_blk[2] | proc_1_data_PIPO_blk[2] | proc_1_start_FIFO_blk[2] | proc_1_TLF_FIFO_blk[2] | proc_1_input_sync_blk[2] | proc_1_output_sync_blk[2]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_1_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_1_reg <= proc_dep_vld_vec_1;
        end
    end
    assign in_chan_dep_vld_vec_1[0] = dep_chan_vld_0_1;
    assign in_chan_dep_data_vec_1[10 : 0] = dep_chan_data_0_1;
    assign token_in_vec_1[0] = token_0_1;
    assign in_chan_dep_vld_vec_1[1] = dep_chan_vld_2_1;
    assign in_chan_dep_data_vec_1[21 : 11] = dep_chan_data_2_1;
    assign token_in_vec_1[1] = token_2_1;
    assign in_chan_dep_vld_vec_1[2] = dep_chan_vld_10_1;
    assign in_chan_dep_data_vec_1[32 : 22] = dep_chan_data_10_1;
    assign token_in_vec_1[2] = token_10_1;
    assign dep_chan_vld_1_2 = out_chan_dep_vld_vec_1[0];
    assign dep_chan_data_1_2 = out_chan_dep_data_1;
    assign token_1_2 = token_out_vec_1[0];
    assign dep_chan_vld_1_10 = out_chan_dep_vld_vec_1[1];
    assign dep_chan_data_1_10 = out_chan_dep_data_1;
    assign token_1_10 = token_out_vec_1[1];
    assign dep_chan_vld_1_0 = out_chan_dep_vld_vec_1[2];
    assign dep_chan_data_1_0 = out_chan_dep_data_1;
    assign token_1_0 = token_out_vec_1[2];

    // Process: grp_cascade_fu_231.thin_stage_0_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 2, 10, 10) tcb_lineart_accel_hls_deadlock_detect_unit_2 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_2),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_2),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_2),
        .token_in_vec(token_in_vec_2),
        .dl_detect_in(dl_detect_out),
        .origin(origin[2]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_2),
        .out_chan_dep_data(out_chan_dep_data_2),
        .token_out_vec(token_out_vec_2),
        .dl_detect_out(dl_in_vec[2]));

    assign proc_2_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_0_U0.grp_thin_stage_0_Pipeline_VITIS_LOOP_44_4_fu_128.s_0_blk_n);
    assign proc_2_data_PIPO_blk[0] = 1'b0;
    assign proc_2_start_FIFO_blk[0] = 1'b0;
    assign proc_2_TLF_FIFO_blk[0] = 1'b0;
    assign proc_2_input_sync_blk[0] = 1'b0;
    assign proc_2_output_sync_blk[0] = 1'b0;
    assign proc_dep_vld_vec_2[0] = dl_detect_out ? proc_dep_vld_vec_2_reg[0] : (proc_2_data_FIFO_blk[0] | proc_2_data_PIPO_blk[0] | proc_2_start_FIFO_blk[0] | proc_2_TLF_FIFO_blk[0] | proc_2_input_sync_blk[0] | proc_2_output_sync_blk[0]);
    assign proc_2_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_0_U0.grp_thin_stage_0_Pipeline_VITIS_LOOP_44_4_fu_128.s_1_blk_n) | (~grp_cascade_fu_231.thin_stage_0_U0.w_c6_blk_n) | (~grp_cascade_fu_231.thin_stage_0_U0.h_c13_blk_n);
    assign proc_2_data_PIPO_blk[1] = 1'b0;
    assign proc_2_start_FIFO_blk[1] = 1'b0;
    assign proc_2_TLF_FIFO_blk[1] = 1'b0;
    assign proc_2_input_sync_blk[1] = 1'b0;
    assign proc_2_output_sync_blk[1] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_2[1] = dl_detect_out ? proc_dep_vld_vec_2_reg[1] : (proc_2_data_FIFO_blk[1] | proc_2_data_PIPO_blk[1] | proc_2_start_FIFO_blk[1] | proc_2_TLF_FIFO_blk[1] | proc_2_input_sync_blk[1] | proc_2_output_sync_blk[1]);
    assign proc_2_data_FIFO_blk[2] = 1'b0 | (~grp_cascade_fu_231.thin_stage_0_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_0_U0.h_blk_n);
    assign proc_2_data_PIPO_blk[2] = 1'b0;
    assign proc_2_start_FIFO_blk[2] = 1'b0;
    assign proc_2_TLF_FIFO_blk[2] = 1'b0;
    assign proc_2_input_sync_blk[2] = 1'b0;
    assign proc_2_output_sync_blk[2] = 1'b0;
    assign proc_dep_vld_vec_2[2] = dl_detect_out ? proc_dep_vld_vec_2_reg[2] : (proc_2_data_FIFO_blk[2] | proc_2_data_PIPO_blk[2] | proc_2_start_FIFO_blk[2] | proc_2_TLF_FIFO_blk[2] | proc_2_input_sync_blk[2] | proc_2_output_sync_blk[2]);
    assign proc_2_data_FIFO_blk[3] = 1'b0;
    assign proc_2_data_PIPO_blk[3] = 1'b0;
    assign proc_2_start_FIFO_blk[3] = 1'b0;
    assign proc_2_TLF_FIFO_blk[3] = 1'b0;
    assign proc_2_input_sync_blk[3] = 1'b0;
    assign proc_2_output_sync_blk[3] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_2[3] = dl_detect_out ? proc_dep_vld_vec_2_reg[3] : (proc_2_data_FIFO_blk[3] | proc_2_data_PIPO_blk[3] | proc_2_start_FIFO_blk[3] | proc_2_TLF_FIFO_blk[3] | proc_2_input_sync_blk[3] | proc_2_output_sync_blk[3]);
    assign proc_2_data_FIFO_blk[4] = 1'b0;
    assign proc_2_data_PIPO_blk[4] = 1'b0;
    assign proc_2_start_FIFO_blk[4] = 1'b0;
    assign proc_2_TLF_FIFO_blk[4] = 1'b0;
    assign proc_2_input_sync_blk[4] = 1'b0;
    assign proc_2_output_sync_blk[4] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_2[4] = dl_detect_out ? proc_dep_vld_vec_2_reg[4] : (proc_2_data_FIFO_blk[4] | proc_2_data_PIPO_blk[4] | proc_2_start_FIFO_blk[4] | proc_2_TLF_FIFO_blk[4] | proc_2_input_sync_blk[4] | proc_2_output_sync_blk[4]);
    assign proc_2_data_FIFO_blk[5] = 1'b0;
    assign proc_2_data_PIPO_blk[5] = 1'b0;
    assign proc_2_start_FIFO_blk[5] = 1'b0;
    assign proc_2_TLF_FIFO_blk[5] = 1'b0;
    assign proc_2_input_sync_blk[5] = 1'b0;
    assign proc_2_output_sync_blk[5] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_2[5] = dl_detect_out ? proc_dep_vld_vec_2_reg[5] : (proc_2_data_FIFO_blk[5] | proc_2_data_PIPO_blk[5] | proc_2_start_FIFO_blk[5] | proc_2_TLF_FIFO_blk[5] | proc_2_input_sync_blk[5] | proc_2_output_sync_blk[5]);
    assign proc_2_data_FIFO_blk[6] = 1'b0;
    assign proc_2_data_PIPO_blk[6] = 1'b0;
    assign proc_2_start_FIFO_blk[6] = 1'b0;
    assign proc_2_TLF_FIFO_blk[6] = 1'b0;
    assign proc_2_input_sync_blk[6] = 1'b0;
    assign proc_2_output_sync_blk[6] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_2[6] = dl_detect_out ? proc_dep_vld_vec_2_reg[6] : (proc_2_data_FIFO_blk[6] | proc_2_data_PIPO_blk[6] | proc_2_start_FIFO_blk[6] | proc_2_TLF_FIFO_blk[6] | proc_2_input_sync_blk[6] | proc_2_output_sync_blk[6]);
    assign proc_2_data_FIFO_blk[7] = 1'b0;
    assign proc_2_data_PIPO_blk[7] = 1'b0;
    assign proc_2_start_FIFO_blk[7] = 1'b0;
    assign proc_2_TLF_FIFO_blk[7] = 1'b0;
    assign proc_2_input_sync_blk[7] = 1'b0;
    assign proc_2_output_sync_blk[7] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_2[7] = dl_detect_out ? proc_dep_vld_vec_2_reg[7] : (proc_2_data_FIFO_blk[7] | proc_2_data_PIPO_blk[7] | proc_2_start_FIFO_blk[7] | proc_2_TLF_FIFO_blk[7] | proc_2_input_sync_blk[7] | proc_2_output_sync_blk[7]);
    assign proc_2_data_FIFO_blk[8] = 1'b0;
    assign proc_2_data_PIPO_blk[8] = 1'b0;
    assign proc_2_start_FIFO_blk[8] = 1'b0;
    assign proc_2_TLF_FIFO_blk[8] = 1'b0;
    assign proc_2_input_sync_blk[8] = 1'b0;
    assign proc_2_output_sync_blk[8] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_2[8] = dl_detect_out ? proc_dep_vld_vec_2_reg[8] : (proc_2_data_FIFO_blk[8] | proc_2_data_PIPO_blk[8] | proc_2_start_FIFO_blk[8] | proc_2_TLF_FIFO_blk[8] | proc_2_input_sync_blk[8] | proc_2_output_sync_blk[8]);
    assign proc_2_data_FIFO_blk[9] = 1'b0;
    assign proc_2_data_PIPO_blk[9] = 1'b0;
    assign proc_2_start_FIFO_blk[9] = 1'b0;
    assign proc_2_TLF_FIFO_blk[9] = 1'b0;
    assign proc_2_input_sync_blk[9] = 1'b0;
    assign proc_2_output_sync_blk[9] = 1'b0 | (ap_done_reg_0 & grp_cascade_fu_231.thin_stage_0_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_2[9] = dl_detect_out ? proc_dep_vld_vec_2_reg[9] : (proc_2_data_FIFO_blk[9] | proc_2_data_PIPO_blk[9] | proc_2_start_FIFO_blk[9] | proc_2_TLF_FIFO_blk[9] | proc_2_input_sync_blk[9] | proc_2_output_sync_blk[9]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_2_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_2_reg <= proc_dep_vld_vec_2;
        end
    end
    assign in_chan_dep_vld_vec_2[0] = dep_chan_vld_0_2;
    assign in_chan_dep_data_vec_2[10 : 0] = dep_chan_data_0_2;
    assign token_in_vec_2[0] = token_0_2;
    assign in_chan_dep_vld_vec_2[1] = dep_chan_vld_1_2;
    assign in_chan_dep_data_vec_2[21 : 11] = dep_chan_data_1_2;
    assign token_in_vec_2[1] = token_1_2;
    assign in_chan_dep_vld_vec_2[2] = dep_chan_vld_3_2;
    assign in_chan_dep_data_vec_2[32 : 22] = dep_chan_data_3_2;
    assign token_in_vec_2[2] = token_3_2;
    assign in_chan_dep_vld_vec_2[3] = dep_chan_vld_4_2;
    assign in_chan_dep_data_vec_2[43 : 33] = dep_chan_data_4_2;
    assign token_in_vec_2[3] = token_4_2;
    assign in_chan_dep_vld_vec_2[4] = dep_chan_vld_5_2;
    assign in_chan_dep_data_vec_2[54 : 44] = dep_chan_data_5_2;
    assign token_in_vec_2[4] = token_5_2;
    assign in_chan_dep_vld_vec_2[5] = dep_chan_vld_6_2;
    assign in_chan_dep_data_vec_2[65 : 55] = dep_chan_data_6_2;
    assign token_in_vec_2[5] = token_6_2;
    assign in_chan_dep_vld_vec_2[6] = dep_chan_vld_7_2;
    assign in_chan_dep_data_vec_2[76 : 66] = dep_chan_data_7_2;
    assign token_in_vec_2[6] = token_7_2;
    assign in_chan_dep_vld_vec_2[7] = dep_chan_vld_8_2;
    assign in_chan_dep_data_vec_2[87 : 77] = dep_chan_data_8_2;
    assign token_in_vec_2[7] = token_8_2;
    assign in_chan_dep_vld_vec_2[8] = dep_chan_vld_9_2;
    assign in_chan_dep_data_vec_2[98 : 88] = dep_chan_data_9_2;
    assign token_in_vec_2[8] = token_9_2;
    assign in_chan_dep_vld_vec_2[9] = dep_chan_vld_10_2;
    assign in_chan_dep_data_vec_2[109 : 99] = dep_chan_data_10_2;
    assign token_in_vec_2[9] = token_10_2;
    assign dep_chan_vld_2_1 = out_chan_dep_vld_vec_2[0];
    assign dep_chan_data_2_1 = out_chan_dep_data_2;
    assign token_2_1 = token_out_vec_2[0];
    assign dep_chan_vld_2_3 = out_chan_dep_vld_vec_2[1];
    assign dep_chan_data_2_3 = out_chan_dep_data_2;
    assign token_2_3 = token_out_vec_2[1];
    assign dep_chan_vld_2_0 = out_chan_dep_vld_vec_2[2];
    assign dep_chan_data_2_0 = out_chan_dep_data_2;
    assign token_2_0 = token_out_vec_2[2];
    assign dep_chan_vld_2_4 = out_chan_dep_vld_vec_2[3];
    assign dep_chan_data_2_4 = out_chan_dep_data_2;
    assign token_2_4 = token_out_vec_2[3];
    assign dep_chan_vld_2_5 = out_chan_dep_vld_vec_2[4];
    assign dep_chan_data_2_5 = out_chan_dep_data_2;
    assign token_2_5 = token_out_vec_2[4];
    assign dep_chan_vld_2_6 = out_chan_dep_vld_vec_2[5];
    assign dep_chan_data_2_6 = out_chan_dep_data_2;
    assign token_2_6 = token_out_vec_2[5];
    assign dep_chan_vld_2_7 = out_chan_dep_vld_vec_2[6];
    assign dep_chan_data_2_7 = out_chan_dep_data_2;
    assign token_2_7 = token_out_vec_2[6];
    assign dep_chan_vld_2_8 = out_chan_dep_vld_vec_2[7];
    assign dep_chan_data_2_8 = out_chan_dep_data_2;
    assign token_2_8 = token_out_vec_2[7];
    assign dep_chan_vld_2_9 = out_chan_dep_vld_vec_2[8];
    assign dep_chan_data_2_9 = out_chan_dep_data_2;
    assign token_2_9 = token_out_vec_2[8];
    assign dep_chan_vld_2_10 = out_chan_dep_vld_vec_2[9];
    assign dep_chan_data_2_10 = out_chan_dep_data_2;
    assign token_2_10 = token_out_vec_2[9];

    // Process: grp_cascade_fu_231.thin_stage_1_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 3, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_3 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_3),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_3),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_3),
        .token_in_vec(token_in_vec_3),
        .dl_detect_in(dl_detect_out),
        .origin(origin[3]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_3),
        .out_chan_dep_data(out_chan_dep_data_3),
        .token_out_vec(token_out_vec_3),
        .dl_detect_out(dl_in_vec[3]));

    assign proc_3_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_1_U0.grp_thin_stage_1_Pipeline_VITIS_LOOP_44_4_fu_128.s_1_blk_n) | (~grp_cascade_fu_231.thin_stage_1_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_1_U0.h_blk_n);
    assign proc_3_data_PIPO_blk[0] = 1'b0;
    assign proc_3_start_FIFO_blk[0] = 1'b0;
    assign proc_3_TLF_FIFO_blk[0] = 1'b0;
    assign proc_3_input_sync_blk[0] = 1'b0;
    assign proc_3_output_sync_blk[0] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_3[0] = dl_detect_out ? proc_dep_vld_vec_3_reg[0] : (proc_3_data_FIFO_blk[0] | proc_3_data_PIPO_blk[0] | proc_3_start_FIFO_blk[0] | proc_3_TLF_FIFO_blk[0] | proc_3_input_sync_blk[0] | proc_3_output_sync_blk[0]);
    assign proc_3_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_1_U0.grp_thin_stage_1_Pipeline_VITIS_LOOP_44_4_fu_128.s_2_blk_n) | (~grp_cascade_fu_231.thin_stage_1_U0.w_c5_blk_n) | (~grp_cascade_fu_231.thin_stage_1_U0.h_c12_blk_n);
    assign proc_3_data_PIPO_blk[1] = 1'b0;
    assign proc_3_start_FIFO_blk[1] = 1'b0;
    assign proc_3_TLF_FIFO_blk[1] = 1'b0;
    assign proc_3_input_sync_blk[1] = 1'b0;
    assign proc_3_output_sync_blk[1] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_3[1] = dl_detect_out ? proc_dep_vld_vec_3_reg[1] : (proc_3_data_FIFO_blk[1] | proc_3_data_PIPO_blk[1] | proc_3_start_FIFO_blk[1] | proc_3_TLF_FIFO_blk[1] | proc_3_input_sync_blk[1] | proc_3_output_sync_blk[1]);
    assign proc_3_data_FIFO_blk[2] = 1'b0;
    assign proc_3_data_PIPO_blk[2] = 1'b0;
    assign proc_3_start_FIFO_blk[2] = 1'b0;
    assign proc_3_TLF_FIFO_blk[2] = 1'b0;
    assign proc_3_input_sync_blk[2] = 1'b0;
    assign proc_3_output_sync_blk[2] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_3[2] = dl_detect_out ? proc_dep_vld_vec_3_reg[2] : (proc_3_data_FIFO_blk[2] | proc_3_data_PIPO_blk[2] | proc_3_start_FIFO_blk[2] | proc_3_TLF_FIFO_blk[2] | proc_3_input_sync_blk[2] | proc_3_output_sync_blk[2]);
    assign proc_3_data_FIFO_blk[3] = 1'b0;
    assign proc_3_data_PIPO_blk[3] = 1'b0;
    assign proc_3_start_FIFO_blk[3] = 1'b0;
    assign proc_3_TLF_FIFO_blk[3] = 1'b0;
    assign proc_3_input_sync_blk[3] = 1'b0;
    assign proc_3_output_sync_blk[3] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_3[3] = dl_detect_out ? proc_dep_vld_vec_3_reg[3] : (proc_3_data_FIFO_blk[3] | proc_3_data_PIPO_blk[3] | proc_3_start_FIFO_blk[3] | proc_3_TLF_FIFO_blk[3] | proc_3_input_sync_blk[3] | proc_3_output_sync_blk[3]);
    assign proc_3_data_FIFO_blk[4] = 1'b0;
    assign proc_3_data_PIPO_blk[4] = 1'b0;
    assign proc_3_start_FIFO_blk[4] = 1'b0;
    assign proc_3_TLF_FIFO_blk[4] = 1'b0;
    assign proc_3_input_sync_blk[4] = 1'b0;
    assign proc_3_output_sync_blk[4] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_3[4] = dl_detect_out ? proc_dep_vld_vec_3_reg[4] : (proc_3_data_FIFO_blk[4] | proc_3_data_PIPO_blk[4] | proc_3_start_FIFO_blk[4] | proc_3_TLF_FIFO_blk[4] | proc_3_input_sync_blk[4] | proc_3_output_sync_blk[4]);
    assign proc_3_data_FIFO_blk[5] = 1'b0;
    assign proc_3_data_PIPO_blk[5] = 1'b0;
    assign proc_3_start_FIFO_blk[5] = 1'b0;
    assign proc_3_TLF_FIFO_blk[5] = 1'b0;
    assign proc_3_input_sync_blk[5] = 1'b0;
    assign proc_3_output_sync_blk[5] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_3[5] = dl_detect_out ? proc_dep_vld_vec_3_reg[5] : (proc_3_data_FIFO_blk[5] | proc_3_data_PIPO_blk[5] | proc_3_start_FIFO_blk[5] | proc_3_TLF_FIFO_blk[5] | proc_3_input_sync_blk[5] | proc_3_output_sync_blk[5]);
    assign proc_3_data_FIFO_blk[6] = 1'b0;
    assign proc_3_data_PIPO_blk[6] = 1'b0;
    assign proc_3_start_FIFO_blk[6] = 1'b0;
    assign proc_3_TLF_FIFO_blk[6] = 1'b0;
    assign proc_3_input_sync_blk[6] = 1'b0;
    assign proc_3_output_sync_blk[6] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_3[6] = dl_detect_out ? proc_dep_vld_vec_3_reg[6] : (proc_3_data_FIFO_blk[6] | proc_3_data_PIPO_blk[6] | proc_3_start_FIFO_blk[6] | proc_3_TLF_FIFO_blk[6] | proc_3_input_sync_blk[6] | proc_3_output_sync_blk[6]);
    assign proc_3_data_FIFO_blk[7] = 1'b0;
    assign proc_3_data_PIPO_blk[7] = 1'b0;
    assign proc_3_start_FIFO_blk[7] = 1'b0;
    assign proc_3_TLF_FIFO_blk[7] = 1'b0;
    assign proc_3_input_sync_blk[7] = 1'b0;
    assign proc_3_output_sync_blk[7] = 1'b0 | (ap_done_reg_1 & grp_cascade_fu_231.thin_stage_1_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_3[7] = dl_detect_out ? proc_dep_vld_vec_3_reg[7] : (proc_3_data_FIFO_blk[7] | proc_3_data_PIPO_blk[7] | proc_3_start_FIFO_blk[7] | proc_3_TLF_FIFO_blk[7] | proc_3_input_sync_blk[7] | proc_3_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_3_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_3_reg <= proc_dep_vld_vec_3;
        end
    end
    assign in_chan_dep_vld_vec_3[0] = dep_chan_vld_2_3;
    assign in_chan_dep_data_vec_3[10 : 0] = dep_chan_data_2_3;
    assign token_in_vec_3[0] = token_2_3;
    assign in_chan_dep_vld_vec_3[1] = dep_chan_vld_4_3;
    assign in_chan_dep_data_vec_3[21 : 11] = dep_chan_data_4_3;
    assign token_in_vec_3[1] = token_4_3;
    assign in_chan_dep_vld_vec_3[2] = dep_chan_vld_5_3;
    assign in_chan_dep_data_vec_3[32 : 22] = dep_chan_data_5_3;
    assign token_in_vec_3[2] = token_5_3;
    assign in_chan_dep_vld_vec_3[3] = dep_chan_vld_6_3;
    assign in_chan_dep_data_vec_3[43 : 33] = dep_chan_data_6_3;
    assign token_in_vec_3[3] = token_6_3;
    assign in_chan_dep_vld_vec_3[4] = dep_chan_vld_7_3;
    assign in_chan_dep_data_vec_3[54 : 44] = dep_chan_data_7_3;
    assign token_in_vec_3[4] = token_7_3;
    assign in_chan_dep_vld_vec_3[5] = dep_chan_vld_8_3;
    assign in_chan_dep_data_vec_3[65 : 55] = dep_chan_data_8_3;
    assign token_in_vec_3[5] = token_8_3;
    assign in_chan_dep_vld_vec_3[6] = dep_chan_vld_9_3;
    assign in_chan_dep_data_vec_3[76 : 66] = dep_chan_data_9_3;
    assign token_in_vec_3[6] = token_9_3;
    assign in_chan_dep_vld_vec_3[7] = dep_chan_vld_10_3;
    assign in_chan_dep_data_vec_3[87 : 77] = dep_chan_data_10_3;
    assign token_in_vec_3[7] = token_10_3;
    assign dep_chan_vld_3_2 = out_chan_dep_vld_vec_3[0];
    assign dep_chan_data_3_2 = out_chan_dep_data_3;
    assign token_3_2 = token_out_vec_3[0];
    assign dep_chan_vld_3_4 = out_chan_dep_vld_vec_3[1];
    assign dep_chan_data_3_4 = out_chan_dep_data_3;
    assign token_3_4 = token_out_vec_3[1];
    assign dep_chan_vld_3_5 = out_chan_dep_vld_vec_3[2];
    assign dep_chan_data_3_5 = out_chan_dep_data_3;
    assign token_3_5 = token_out_vec_3[2];
    assign dep_chan_vld_3_6 = out_chan_dep_vld_vec_3[3];
    assign dep_chan_data_3_6 = out_chan_dep_data_3;
    assign token_3_6 = token_out_vec_3[3];
    assign dep_chan_vld_3_7 = out_chan_dep_vld_vec_3[4];
    assign dep_chan_data_3_7 = out_chan_dep_data_3;
    assign token_3_7 = token_out_vec_3[4];
    assign dep_chan_vld_3_8 = out_chan_dep_vld_vec_3[5];
    assign dep_chan_data_3_8 = out_chan_dep_data_3;
    assign token_3_8 = token_out_vec_3[5];
    assign dep_chan_vld_3_9 = out_chan_dep_vld_vec_3[6];
    assign dep_chan_data_3_9 = out_chan_dep_data_3;
    assign token_3_9 = token_out_vec_3[6];
    assign dep_chan_vld_3_10 = out_chan_dep_vld_vec_3[7];
    assign dep_chan_data_3_10 = out_chan_dep_data_3;
    assign token_3_10 = token_out_vec_3[7];

    // Process: grp_cascade_fu_231.thin_stage_2_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 4, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_4 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_4),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_4),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_4),
        .token_in_vec(token_in_vec_4),
        .dl_detect_in(dl_detect_out),
        .origin(origin[4]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_4),
        .out_chan_dep_data(out_chan_dep_data_4),
        .token_out_vec(token_out_vec_4),
        .dl_detect_out(dl_in_vec[4]));

    assign proc_4_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_2_U0.grp_thin_stage_2_Pipeline_VITIS_LOOP_44_4_fu_128.s_2_blk_n) | (~grp_cascade_fu_231.thin_stage_2_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_2_U0.h_blk_n);
    assign proc_4_data_PIPO_blk[0] = 1'b0;
    assign proc_4_start_FIFO_blk[0] = 1'b0;
    assign proc_4_TLF_FIFO_blk[0] = 1'b0;
    assign proc_4_input_sync_blk[0] = 1'b0;
    assign proc_4_output_sync_blk[0] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_4[0] = dl_detect_out ? proc_dep_vld_vec_4_reg[0] : (proc_4_data_FIFO_blk[0] | proc_4_data_PIPO_blk[0] | proc_4_start_FIFO_blk[0] | proc_4_TLF_FIFO_blk[0] | proc_4_input_sync_blk[0] | proc_4_output_sync_blk[0]);
    assign proc_4_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_2_U0.grp_thin_stage_2_Pipeline_VITIS_LOOP_44_4_fu_128.s_3_blk_n) | (~grp_cascade_fu_231.thin_stage_2_U0.w_c4_blk_n) | (~grp_cascade_fu_231.thin_stage_2_U0.h_c11_blk_n);
    assign proc_4_data_PIPO_blk[1] = 1'b0;
    assign proc_4_start_FIFO_blk[1] = 1'b0;
    assign proc_4_TLF_FIFO_blk[1] = 1'b0;
    assign proc_4_input_sync_blk[1] = 1'b0;
    assign proc_4_output_sync_blk[1] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_4[1] = dl_detect_out ? proc_dep_vld_vec_4_reg[1] : (proc_4_data_FIFO_blk[1] | proc_4_data_PIPO_blk[1] | proc_4_start_FIFO_blk[1] | proc_4_TLF_FIFO_blk[1] | proc_4_input_sync_blk[1] | proc_4_output_sync_blk[1]);
    assign proc_4_data_FIFO_blk[2] = 1'b0;
    assign proc_4_data_PIPO_blk[2] = 1'b0;
    assign proc_4_start_FIFO_blk[2] = 1'b0;
    assign proc_4_TLF_FIFO_blk[2] = 1'b0;
    assign proc_4_input_sync_blk[2] = 1'b0;
    assign proc_4_output_sync_blk[2] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_4[2] = dl_detect_out ? proc_dep_vld_vec_4_reg[2] : (proc_4_data_FIFO_blk[2] | proc_4_data_PIPO_blk[2] | proc_4_start_FIFO_blk[2] | proc_4_TLF_FIFO_blk[2] | proc_4_input_sync_blk[2] | proc_4_output_sync_blk[2]);
    assign proc_4_data_FIFO_blk[3] = 1'b0;
    assign proc_4_data_PIPO_blk[3] = 1'b0;
    assign proc_4_start_FIFO_blk[3] = 1'b0;
    assign proc_4_TLF_FIFO_blk[3] = 1'b0;
    assign proc_4_input_sync_blk[3] = 1'b0;
    assign proc_4_output_sync_blk[3] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_4[3] = dl_detect_out ? proc_dep_vld_vec_4_reg[3] : (proc_4_data_FIFO_blk[3] | proc_4_data_PIPO_blk[3] | proc_4_start_FIFO_blk[3] | proc_4_TLF_FIFO_blk[3] | proc_4_input_sync_blk[3] | proc_4_output_sync_blk[3]);
    assign proc_4_data_FIFO_blk[4] = 1'b0;
    assign proc_4_data_PIPO_blk[4] = 1'b0;
    assign proc_4_start_FIFO_blk[4] = 1'b0;
    assign proc_4_TLF_FIFO_blk[4] = 1'b0;
    assign proc_4_input_sync_blk[4] = 1'b0;
    assign proc_4_output_sync_blk[4] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_4[4] = dl_detect_out ? proc_dep_vld_vec_4_reg[4] : (proc_4_data_FIFO_blk[4] | proc_4_data_PIPO_blk[4] | proc_4_start_FIFO_blk[4] | proc_4_TLF_FIFO_blk[4] | proc_4_input_sync_blk[4] | proc_4_output_sync_blk[4]);
    assign proc_4_data_FIFO_blk[5] = 1'b0;
    assign proc_4_data_PIPO_blk[5] = 1'b0;
    assign proc_4_start_FIFO_blk[5] = 1'b0;
    assign proc_4_TLF_FIFO_blk[5] = 1'b0;
    assign proc_4_input_sync_blk[5] = 1'b0;
    assign proc_4_output_sync_blk[5] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_4[5] = dl_detect_out ? proc_dep_vld_vec_4_reg[5] : (proc_4_data_FIFO_blk[5] | proc_4_data_PIPO_blk[5] | proc_4_start_FIFO_blk[5] | proc_4_TLF_FIFO_blk[5] | proc_4_input_sync_blk[5] | proc_4_output_sync_blk[5]);
    assign proc_4_data_FIFO_blk[6] = 1'b0;
    assign proc_4_data_PIPO_blk[6] = 1'b0;
    assign proc_4_start_FIFO_blk[6] = 1'b0;
    assign proc_4_TLF_FIFO_blk[6] = 1'b0;
    assign proc_4_input_sync_blk[6] = 1'b0;
    assign proc_4_output_sync_blk[6] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_4[6] = dl_detect_out ? proc_dep_vld_vec_4_reg[6] : (proc_4_data_FIFO_blk[6] | proc_4_data_PIPO_blk[6] | proc_4_start_FIFO_blk[6] | proc_4_TLF_FIFO_blk[6] | proc_4_input_sync_blk[6] | proc_4_output_sync_blk[6]);
    assign proc_4_data_FIFO_blk[7] = 1'b0;
    assign proc_4_data_PIPO_blk[7] = 1'b0;
    assign proc_4_start_FIFO_blk[7] = 1'b0;
    assign proc_4_TLF_FIFO_blk[7] = 1'b0;
    assign proc_4_input_sync_blk[7] = 1'b0;
    assign proc_4_output_sync_blk[7] = 1'b0 | (ap_done_reg_2 & grp_cascade_fu_231.thin_stage_2_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_4[7] = dl_detect_out ? proc_dep_vld_vec_4_reg[7] : (proc_4_data_FIFO_blk[7] | proc_4_data_PIPO_blk[7] | proc_4_start_FIFO_blk[7] | proc_4_TLF_FIFO_blk[7] | proc_4_input_sync_blk[7] | proc_4_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_4_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_4_reg <= proc_dep_vld_vec_4;
        end
    end
    assign in_chan_dep_vld_vec_4[0] = dep_chan_vld_2_4;
    assign in_chan_dep_data_vec_4[10 : 0] = dep_chan_data_2_4;
    assign token_in_vec_4[0] = token_2_4;
    assign in_chan_dep_vld_vec_4[1] = dep_chan_vld_3_4;
    assign in_chan_dep_data_vec_4[21 : 11] = dep_chan_data_3_4;
    assign token_in_vec_4[1] = token_3_4;
    assign in_chan_dep_vld_vec_4[2] = dep_chan_vld_5_4;
    assign in_chan_dep_data_vec_4[32 : 22] = dep_chan_data_5_4;
    assign token_in_vec_4[2] = token_5_4;
    assign in_chan_dep_vld_vec_4[3] = dep_chan_vld_6_4;
    assign in_chan_dep_data_vec_4[43 : 33] = dep_chan_data_6_4;
    assign token_in_vec_4[3] = token_6_4;
    assign in_chan_dep_vld_vec_4[4] = dep_chan_vld_7_4;
    assign in_chan_dep_data_vec_4[54 : 44] = dep_chan_data_7_4;
    assign token_in_vec_4[4] = token_7_4;
    assign in_chan_dep_vld_vec_4[5] = dep_chan_vld_8_4;
    assign in_chan_dep_data_vec_4[65 : 55] = dep_chan_data_8_4;
    assign token_in_vec_4[5] = token_8_4;
    assign in_chan_dep_vld_vec_4[6] = dep_chan_vld_9_4;
    assign in_chan_dep_data_vec_4[76 : 66] = dep_chan_data_9_4;
    assign token_in_vec_4[6] = token_9_4;
    assign in_chan_dep_vld_vec_4[7] = dep_chan_vld_10_4;
    assign in_chan_dep_data_vec_4[87 : 77] = dep_chan_data_10_4;
    assign token_in_vec_4[7] = token_10_4;
    assign dep_chan_vld_4_3 = out_chan_dep_vld_vec_4[0];
    assign dep_chan_data_4_3 = out_chan_dep_data_4;
    assign token_4_3 = token_out_vec_4[0];
    assign dep_chan_vld_4_5 = out_chan_dep_vld_vec_4[1];
    assign dep_chan_data_4_5 = out_chan_dep_data_4;
    assign token_4_5 = token_out_vec_4[1];
    assign dep_chan_vld_4_2 = out_chan_dep_vld_vec_4[2];
    assign dep_chan_data_4_2 = out_chan_dep_data_4;
    assign token_4_2 = token_out_vec_4[2];
    assign dep_chan_vld_4_6 = out_chan_dep_vld_vec_4[3];
    assign dep_chan_data_4_6 = out_chan_dep_data_4;
    assign token_4_6 = token_out_vec_4[3];
    assign dep_chan_vld_4_7 = out_chan_dep_vld_vec_4[4];
    assign dep_chan_data_4_7 = out_chan_dep_data_4;
    assign token_4_7 = token_out_vec_4[4];
    assign dep_chan_vld_4_8 = out_chan_dep_vld_vec_4[5];
    assign dep_chan_data_4_8 = out_chan_dep_data_4;
    assign token_4_8 = token_out_vec_4[5];
    assign dep_chan_vld_4_9 = out_chan_dep_vld_vec_4[6];
    assign dep_chan_data_4_9 = out_chan_dep_data_4;
    assign token_4_9 = token_out_vec_4[6];
    assign dep_chan_vld_4_10 = out_chan_dep_vld_vec_4[7];
    assign dep_chan_data_4_10 = out_chan_dep_data_4;
    assign token_4_10 = token_out_vec_4[7];

    // Process: grp_cascade_fu_231.thin_stage_3_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 5, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_5 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_5),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_5),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_5),
        .token_in_vec(token_in_vec_5),
        .dl_detect_in(dl_detect_out),
        .origin(origin[5]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_5),
        .out_chan_dep_data(out_chan_dep_data_5),
        .token_out_vec(token_out_vec_5),
        .dl_detect_out(dl_in_vec[5]));

    assign proc_5_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_3_U0.grp_thin_stage_3_Pipeline_VITIS_LOOP_44_4_fu_128.s_3_blk_n) | (~grp_cascade_fu_231.thin_stage_3_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_3_U0.h_blk_n);
    assign proc_5_data_PIPO_blk[0] = 1'b0;
    assign proc_5_start_FIFO_blk[0] = 1'b0;
    assign proc_5_TLF_FIFO_blk[0] = 1'b0;
    assign proc_5_input_sync_blk[0] = 1'b0;
    assign proc_5_output_sync_blk[0] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_5[0] = dl_detect_out ? proc_dep_vld_vec_5_reg[0] : (proc_5_data_FIFO_blk[0] | proc_5_data_PIPO_blk[0] | proc_5_start_FIFO_blk[0] | proc_5_TLF_FIFO_blk[0] | proc_5_input_sync_blk[0] | proc_5_output_sync_blk[0]);
    assign proc_5_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_3_U0.grp_thin_stage_3_Pipeline_VITIS_LOOP_44_4_fu_128.s_4_blk_n) | (~grp_cascade_fu_231.thin_stage_3_U0.w_c3_blk_n) | (~grp_cascade_fu_231.thin_stage_3_U0.h_c10_blk_n);
    assign proc_5_data_PIPO_blk[1] = 1'b0;
    assign proc_5_start_FIFO_blk[1] = 1'b0;
    assign proc_5_TLF_FIFO_blk[1] = 1'b0;
    assign proc_5_input_sync_blk[1] = 1'b0;
    assign proc_5_output_sync_blk[1] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_5[1] = dl_detect_out ? proc_dep_vld_vec_5_reg[1] : (proc_5_data_FIFO_blk[1] | proc_5_data_PIPO_blk[1] | proc_5_start_FIFO_blk[1] | proc_5_TLF_FIFO_blk[1] | proc_5_input_sync_blk[1] | proc_5_output_sync_blk[1]);
    assign proc_5_data_FIFO_blk[2] = 1'b0;
    assign proc_5_data_PIPO_blk[2] = 1'b0;
    assign proc_5_start_FIFO_blk[2] = 1'b0;
    assign proc_5_TLF_FIFO_blk[2] = 1'b0;
    assign proc_5_input_sync_blk[2] = 1'b0;
    assign proc_5_output_sync_blk[2] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_5[2] = dl_detect_out ? proc_dep_vld_vec_5_reg[2] : (proc_5_data_FIFO_blk[2] | proc_5_data_PIPO_blk[2] | proc_5_start_FIFO_blk[2] | proc_5_TLF_FIFO_blk[2] | proc_5_input_sync_blk[2] | proc_5_output_sync_blk[2]);
    assign proc_5_data_FIFO_blk[3] = 1'b0;
    assign proc_5_data_PIPO_blk[3] = 1'b0;
    assign proc_5_start_FIFO_blk[3] = 1'b0;
    assign proc_5_TLF_FIFO_blk[3] = 1'b0;
    assign proc_5_input_sync_blk[3] = 1'b0;
    assign proc_5_output_sync_blk[3] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_5[3] = dl_detect_out ? proc_dep_vld_vec_5_reg[3] : (proc_5_data_FIFO_blk[3] | proc_5_data_PIPO_blk[3] | proc_5_start_FIFO_blk[3] | proc_5_TLF_FIFO_blk[3] | proc_5_input_sync_blk[3] | proc_5_output_sync_blk[3]);
    assign proc_5_data_FIFO_blk[4] = 1'b0;
    assign proc_5_data_PIPO_blk[4] = 1'b0;
    assign proc_5_start_FIFO_blk[4] = 1'b0;
    assign proc_5_TLF_FIFO_blk[4] = 1'b0;
    assign proc_5_input_sync_blk[4] = 1'b0;
    assign proc_5_output_sync_blk[4] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_5[4] = dl_detect_out ? proc_dep_vld_vec_5_reg[4] : (proc_5_data_FIFO_blk[4] | proc_5_data_PIPO_blk[4] | proc_5_start_FIFO_blk[4] | proc_5_TLF_FIFO_blk[4] | proc_5_input_sync_blk[4] | proc_5_output_sync_blk[4]);
    assign proc_5_data_FIFO_blk[5] = 1'b0;
    assign proc_5_data_PIPO_blk[5] = 1'b0;
    assign proc_5_start_FIFO_blk[5] = 1'b0;
    assign proc_5_TLF_FIFO_blk[5] = 1'b0;
    assign proc_5_input_sync_blk[5] = 1'b0;
    assign proc_5_output_sync_blk[5] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_5[5] = dl_detect_out ? proc_dep_vld_vec_5_reg[5] : (proc_5_data_FIFO_blk[5] | proc_5_data_PIPO_blk[5] | proc_5_start_FIFO_blk[5] | proc_5_TLF_FIFO_blk[5] | proc_5_input_sync_blk[5] | proc_5_output_sync_blk[5]);
    assign proc_5_data_FIFO_blk[6] = 1'b0;
    assign proc_5_data_PIPO_blk[6] = 1'b0;
    assign proc_5_start_FIFO_blk[6] = 1'b0;
    assign proc_5_TLF_FIFO_blk[6] = 1'b0;
    assign proc_5_input_sync_blk[6] = 1'b0;
    assign proc_5_output_sync_blk[6] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_5[6] = dl_detect_out ? proc_dep_vld_vec_5_reg[6] : (proc_5_data_FIFO_blk[6] | proc_5_data_PIPO_blk[6] | proc_5_start_FIFO_blk[6] | proc_5_TLF_FIFO_blk[6] | proc_5_input_sync_blk[6] | proc_5_output_sync_blk[6]);
    assign proc_5_data_FIFO_blk[7] = 1'b0;
    assign proc_5_data_PIPO_blk[7] = 1'b0;
    assign proc_5_start_FIFO_blk[7] = 1'b0;
    assign proc_5_TLF_FIFO_blk[7] = 1'b0;
    assign proc_5_input_sync_blk[7] = 1'b0;
    assign proc_5_output_sync_blk[7] = 1'b0 | (ap_done_reg_3 & grp_cascade_fu_231.thin_stage_3_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_5[7] = dl_detect_out ? proc_dep_vld_vec_5_reg[7] : (proc_5_data_FIFO_blk[7] | proc_5_data_PIPO_blk[7] | proc_5_start_FIFO_blk[7] | proc_5_TLF_FIFO_blk[7] | proc_5_input_sync_blk[7] | proc_5_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_5_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_5_reg <= proc_dep_vld_vec_5;
        end
    end
    assign in_chan_dep_vld_vec_5[0] = dep_chan_vld_2_5;
    assign in_chan_dep_data_vec_5[10 : 0] = dep_chan_data_2_5;
    assign token_in_vec_5[0] = token_2_5;
    assign in_chan_dep_vld_vec_5[1] = dep_chan_vld_3_5;
    assign in_chan_dep_data_vec_5[21 : 11] = dep_chan_data_3_5;
    assign token_in_vec_5[1] = token_3_5;
    assign in_chan_dep_vld_vec_5[2] = dep_chan_vld_4_5;
    assign in_chan_dep_data_vec_5[32 : 22] = dep_chan_data_4_5;
    assign token_in_vec_5[2] = token_4_5;
    assign in_chan_dep_vld_vec_5[3] = dep_chan_vld_6_5;
    assign in_chan_dep_data_vec_5[43 : 33] = dep_chan_data_6_5;
    assign token_in_vec_5[3] = token_6_5;
    assign in_chan_dep_vld_vec_5[4] = dep_chan_vld_7_5;
    assign in_chan_dep_data_vec_5[54 : 44] = dep_chan_data_7_5;
    assign token_in_vec_5[4] = token_7_5;
    assign in_chan_dep_vld_vec_5[5] = dep_chan_vld_8_5;
    assign in_chan_dep_data_vec_5[65 : 55] = dep_chan_data_8_5;
    assign token_in_vec_5[5] = token_8_5;
    assign in_chan_dep_vld_vec_5[6] = dep_chan_vld_9_5;
    assign in_chan_dep_data_vec_5[76 : 66] = dep_chan_data_9_5;
    assign token_in_vec_5[6] = token_9_5;
    assign in_chan_dep_vld_vec_5[7] = dep_chan_vld_10_5;
    assign in_chan_dep_data_vec_5[87 : 77] = dep_chan_data_10_5;
    assign token_in_vec_5[7] = token_10_5;
    assign dep_chan_vld_5_4 = out_chan_dep_vld_vec_5[0];
    assign dep_chan_data_5_4 = out_chan_dep_data_5;
    assign token_5_4 = token_out_vec_5[0];
    assign dep_chan_vld_5_6 = out_chan_dep_vld_vec_5[1];
    assign dep_chan_data_5_6 = out_chan_dep_data_5;
    assign token_5_6 = token_out_vec_5[1];
    assign dep_chan_vld_5_2 = out_chan_dep_vld_vec_5[2];
    assign dep_chan_data_5_2 = out_chan_dep_data_5;
    assign token_5_2 = token_out_vec_5[2];
    assign dep_chan_vld_5_3 = out_chan_dep_vld_vec_5[3];
    assign dep_chan_data_5_3 = out_chan_dep_data_5;
    assign token_5_3 = token_out_vec_5[3];
    assign dep_chan_vld_5_7 = out_chan_dep_vld_vec_5[4];
    assign dep_chan_data_5_7 = out_chan_dep_data_5;
    assign token_5_7 = token_out_vec_5[4];
    assign dep_chan_vld_5_8 = out_chan_dep_vld_vec_5[5];
    assign dep_chan_data_5_8 = out_chan_dep_data_5;
    assign token_5_8 = token_out_vec_5[5];
    assign dep_chan_vld_5_9 = out_chan_dep_vld_vec_5[6];
    assign dep_chan_data_5_9 = out_chan_dep_data_5;
    assign token_5_9 = token_out_vec_5[6];
    assign dep_chan_vld_5_10 = out_chan_dep_vld_vec_5[7];
    assign dep_chan_data_5_10 = out_chan_dep_data_5;
    assign token_5_10 = token_out_vec_5[7];

    // Process: grp_cascade_fu_231.thin_stage_4_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 6, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_6 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_6),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_6),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_6),
        .token_in_vec(token_in_vec_6),
        .dl_detect_in(dl_detect_out),
        .origin(origin[6]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_6),
        .out_chan_dep_data(out_chan_dep_data_6),
        .token_out_vec(token_out_vec_6),
        .dl_detect_out(dl_in_vec[6]));

    assign proc_6_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_4_U0.grp_thin_stage_4_Pipeline_VITIS_LOOP_44_4_fu_128.s_4_blk_n) | (~grp_cascade_fu_231.thin_stage_4_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_4_U0.h_blk_n);
    assign proc_6_data_PIPO_blk[0] = 1'b0;
    assign proc_6_start_FIFO_blk[0] = 1'b0;
    assign proc_6_TLF_FIFO_blk[0] = 1'b0;
    assign proc_6_input_sync_blk[0] = 1'b0;
    assign proc_6_output_sync_blk[0] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_6[0] = dl_detect_out ? proc_dep_vld_vec_6_reg[0] : (proc_6_data_FIFO_blk[0] | proc_6_data_PIPO_blk[0] | proc_6_start_FIFO_blk[0] | proc_6_TLF_FIFO_blk[0] | proc_6_input_sync_blk[0] | proc_6_output_sync_blk[0]);
    assign proc_6_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_4_U0.grp_thin_stage_4_Pipeline_VITIS_LOOP_44_4_fu_128.s_5_blk_n) | (~grp_cascade_fu_231.thin_stage_4_U0.w_c2_blk_n) | (~grp_cascade_fu_231.thin_stage_4_U0.h_c9_blk_n);
    assign proc_6_data_PIPO_blk[1] = 1'b0;
    assign proc_6_start_FIFO_blk[1] = 1'b0;
    assign proc_6_TLF_FIFO_blk[1] = 1'b0;
    assign proc_6_input_sync_blk[1] = 1'b0;
    assign proc_6_output_sync_blk[1] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_6[1] = dl_detect_out ? proc_dep_vld_vec_6_reg[1] : (proc_6_data_FIFO_blk[1] | proc_6_data_PIPO_blk[1] | proc_6_start_FIFO_blk[1] | proc_6_TLF_FIFO_blk[1] | proc_6_input_sync_blk[1] | proc_6_output_sync_blk[1]);
    assign proc_6_data_FIFO_blk[2] = 1'b0;
    assign proc_6_data_PIPO_blk[2] = 1'b0;
    assign proc_6_start_FIFO_blk[2] = 1'b0;
    assign proc_6_TLF_FIFO_blk[2] = 1'b0;
    assign proc_6_input_sync_blk[2] = 1'b0;
    assign proc_6_output_sync_blk[2] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_6[2] = dl_detect_out ? proc_dep_vld_vec_6_reg[2] : (proc_6_data_FIFO_blk[2] | proc_6_data_PIPO_blk[2] | proc_6_start_FIFO_blk[2] | proc_6_TLF_FIFO_blk[2] | proc_6_input_sync_blk[2] | proc_6_output_sync_blk[2]);
    assign proc_6_data_FIFO_blk[3] = 1'b0;
    assign proc_6_data_PIPO_blk[3] = 1'b0;
    assign proc_6_start_FIFO_blk[3] = 1'b0;
    assign proc_6_TLF_FIFO_blk[3] = 1'b0;
    assign proc_6_input_sync_blk[3] = 1'b0;
    assign proc_6_output_sync_blk[3] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_6[3] = dl_detect_out ? proc_dep_vld_vec_6_reg[3] : (proc_6_data_FIFO_blk[3] | proc_6_data_PIPO_blk[3] | proc_6_start_FIFO_blk[3] | proc_6_TLF_FIFO_blk[3] | proc_6_input_sync_blk[3] | proc_6_output_sync_blk[3]);
    assign proc_6_data_FIFO_blk[4] = 1'b0;
    assign proc_6_data_PIPO_blk[4] = 1'b0;
    assign proc_6_start_FIFO_blk[4] = 1'b0;
    assign proc_6_TLF_FIFO_blk[4] = 1'b0;
    assign proc_6_input_sync_blk[4] = 1'b0;
    assign proc_6_output_sync_blk[4] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_6[4] = dl_detect_out ? proc_dep_vld_vec_6_reg[4] : (proc_6_data_FIFO_blk[4] | proc_6_data_PIPO_blk[4] | proc_6_start_FIFO_blk[4] | proc_6_TLF_FIFO_blk[4] | proc_6_input_sync_blk[4] | proc_6_output_sync_blk[4]);
    assign proc_6_data_FIFO_blk[5] = 1'b0;
    assign proc_6_data_PIPO_blk[5] = 1'b0;
    assign proc_6_start_FIFO_blk[5] = 1'b0;
    assign proc_6_TLF_FIFO_blk[5] = 1'b0;
    assign proc_6_input_sync_blk[5] = 1'b0;
    assign proc_6_output_sync_blk[5] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_6[5] = dl_detect_out ? proc_dep_vld_vec_6_reg[5] : (proc_6_data_FIFO_blk[5] | proc_6_data_PIPO_blk[5] | proc_6_start_FIFO_blk[5] | proc_6_TLF_FIFO_blk[5] | proc_6_input_sync_blk[5] | proc_6_output_sync_blk[5]);
    assign proc_6_data_FIFO_blk[6] = 1'b0;
    assign proc_6_data_PIPO_blk[6] = 1'b0;
    assign proc_6_start_FIFO_blk[6] = 1'b0;
    assign proc_6_TLF_FIFO_blk[6] = 1'b0;
    assign proc_6_input_sync_blk[6] = 1'b0;
    assign proc_6_output_sync_blk[6] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_6[6] = dl_detect_out ? proc_dep_vld_vec_6_reg[6] : (proc_6_data_FIFO_blk[6] | proc_6_data_PIPO_blk[6] | proc_6_start_FIFO_blk[6] | proc_6_TLF_FIFO_blk[6] | proc_6_input_sync_blk[6] | proc_6_output_sync_blk[6]);
    assign proc_6_data_FIFO_blk[7] = 1'b0;
    assign proc_6_data_PIPO_blk[7] = 1'b0;
    assign proc_6_start_FIFO_blk[7] = 1'b0;
    assign proc_6_TLF_FIFO_blk[7] = 1'b0;
    assign proc_6_input_sync_blk[7] = 1'b0;
    assign proc_6_output_sync_blk[7] = 1'b0 | (ap_done_reg_4 & grp_cascade_fu_231.thin_stage_4_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_6[7] = dl_detect_out ? proc_dep_vld_vec_6_reg[7] : (proc_6_data_FIFO_blk[7] | proc_6_data_PIPO_blk[7] | proc_6_start_FIFO_blk[7] | proc_6_TLF_FIFO_blk[7] | proc_6_input_sync_blk[7] | proc_6_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_6_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_6_reg <= proc_dep_vld_vec_6;
        end
    end
    assign in_chan_dep_vld_vec_6[0] = dep_chan_vld_2_6;
    assign in_chan_dep_data_vec_6[10 : 0] = dep_chan_data_2_6;
    assign token_in_vec_6[0] = token_2_6;
    assign in_chan_dep_vld_vec_6[1] = dep_chan_vld_3_6;
    assign in_chan_dep_data_vec_6[21 : 11] = dep_chan_data_3_6;
    assign token_in_vec_6[1] = token_3_6;
    assign in_chan_dep_vld_vec_6[2] = dep_chan_vld_4_6;
    assign in_chan_dep_data_vec_6[32 : 22] = dep_chan_data_4_6;
    assign token_in_vec_6[2] = token_4_6;
    assign in_chan_dep_vld_vec_6[3] = dep_chan_vld_5_6;
    assign in_chan_dep_data_vec_6[43 : 33] = dep_chan_data_5_6;
    assign token_in_vec_6[3] = token_5_6;
    assign in_chan_dep_vld_vec_6[4] = dep_chan_vld_7_6;
    assign in_chan_dep_data_vec_6[54 : 44] = dep_chan_data_7_6;
    assign token_in_vec_6[4] = token_7_6;
    assign in_chan_dep_vld_vec_6[5] = dep_chan_vld_8_6;
    assign in_chan_dep_data_vec_6[65 : 55] = dep_chan_data_8_6;
    assign token_in_vec_6[5] = token_8_6;
    assign in_chan_dep_vld_vec_6[6] = dep_chan_vld_9_6;
    assign in_chan_dep_data_vec_6[76 : 66] = dep_chan_data_9_6;
    assign token_in_vec_6[6] = token_9_6;
    assign in_chan_dep_vld_vec_6[7] = dep_chan_vld_10_6;
    assign in_chan_dep_data_vec_6[87 : 77] = dep_chan_data_10_6;
    assign token_in_vec_6[7] = token_10_6;
    assign dep_chan_vld_6_5 = out_chan_dep_vld_vec_6[0];
    assign dep_chan_data_6_5 = out_chan_dep_data_6;
    assign token_6_5 = token_out_vec_6[0];
    assign dep_chan_vld_6_7 = out_chan_dep_vld_vec_6[1];
    assign dep_chan_data_6_7 = out_chan_dep_data_6;
    assign token_6_7 = token_out_vec_6[1];
    assign dep_chan_vld_6_2 = out_chan_dep_vld_vec_6[2];
    assign dep_chan_data_6_2 = out_chan_dep_data_6;
    assign token_6_2 = token_out_vec_6[2];
    assign dep_chan_vld_6_3 = out_chan_dep_vld_vec_6[3];
    assign dep_chan_data_6_3 = out_chan_dep_data_6;
    assign token_6_3 = token_out_vec_6[3];
    assign dep_chan_vld_6_4 = out_chan_dep_vld_vec_6[4];
    assign dep_chan_data_6_4 = out_chan_dep_data_6;
    assign token_6_4 = token_out_vec_6[4];
    assign dep_chan_vld_6_8 = out_chan_dep_vld_vec_6[5];
    assign dep_chan_data_6_8 = out_chan_dep_data_6;
    assign token_6_8 = token_out_vec_6[5];
    assign dep_chan_vld_6_9 = out_chan_dep_vld_vec_6[6];
    assign dep_chan_data_6_9 = out_chan_dep_data_6;
    assign token_6_9 = token_out_vec_6[6];
    assign dep_chan_vld_6_10 = out_chan_dep_vld_vec_6[7];
    assign dep_chan_data_6_10 = out_chan_dep_data_6;
    assign token_6_10 = token_out_vec_6[7];

    // Process: grp_cascade_fu_231.thin_stage_5_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 7, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_7 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_7),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_7),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_7),
        .token_in_vec(token_in_vec_7),
        .dl_detect_in(dl_detect_out),
        .origin(origin[7]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_7),
        .out_chan_dep_data(out_chan_dep_data_7),
        .token_out_vec(token_out_vec_7),
        .dl_detect_out(dl_in_vec[7]));

    assign proc_7_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_5_U0.grp_thin_stage_5_Pipeline_VITIS_LOOP_44_4_fu_128.s_5_blk_n) | (~grp_cascade_fu_231.thin_stage_5_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_5_U0.h_blk_n);
    assign proc_7_data_PIPO_blk[0] = 1'b0;
    assign proc_7_start_FIFO_blk[0] = 1'b0;
    assign proc_7_TLF_FIFO_blk[0] = 1'b0;
    assign proc_7_input_sync_blk[0] = 1'b0;
    assign proc_7_output_sync_blk[0] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_7[0] = dl_detect_out ? proc_dep_vld_vec_7_reg[0] : (proc_7_data_FIFO_blk[0] | proc_7_data_PIPO_blk[0] | proc_7_start_FIFO_blk[0] | proc_7_TLF_FIFO_blk[0] | proc_7_input_sync_blk[0] | proc_7_output_sync_blk[0]);
    assign proc_7_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_5_U0.grp_thin_stage_5_Pipeline_VITIS_LOOP_44_4_fu_128.s_6_blk_n) | (~grp_cascade_fu_231.thin_stage_5_U0.w_c1_blk_n) | (~grp_cascade_fu_231.thin_stage_5_U0.h_c8_blk_n);
    assign proc_7_data_PIPO_blk[1] = 1'b0;
    assign proc_7_start_FIFO_blk[1] = 1'b0;
    assign proc_7_TLF_FIFO_blk[1] = 1'b0;
    assign proc_7_input_sync_blk[1] = 1'b0;
    assign proc_7_output_sync_blk[1] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_7[1] = dl_detect_out ? proc_dep_vld_vec_7_reg[1] : (proc_7_data_FIFO_blk[1] | proc_7_data_PIPO_blk[1] | proc_7_start_FIFO_blk[1] | proc_7_TLF_FIFO_blk[1] | proc_7_input_sync_blk[1] | proc_7_output_sync_blk[1]);
    assign proc_7_data_FIFO_blk[2] = 1'b0;
    assign proc_7_data_PIPO_blk[2] = 1'b0;
    assign proc_7_start_FIFO_blk[2] = 1'b0;
    assign proc_7_TLF_FIFO_blk[2] = 1'b0;
    assign proc_7_input_sync_blk[2] = 1'b0;
    assign proc_7_output_sync_blk[2] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_7[2] = dl_detect_out ? proc_dep_vld_vec_7_reg[2] : (proc_7_data_FIFO_blk[2] | proc_7_data_PIPO_blk[2] | proc_7_start_FIFO_blk[2] | proc_7_TLF_FIFO_blk[2] | proc_7_input_sync_blk[2] | proc_7_output_sync_blk[2]);
    assign proc_7_data_FIFO_blk[3] = 1'b0;
    assign proc_7_data_PIPO_blk[3] = 1'b0;
    assign proc_7_start_FIFO_blk[3] = 1'b0;
    assign proc_7_TLF_FIFO_blk[3] = 1'b0;
    assign proc_7_input_sync_blk[3] = 1'b0;
    assign proc_7_output_sync_blk[3] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_7[3] = dl_detect_out ? proc_dep_vld_vec_7_reg[3] : (proc_7_data_FIFO_blk[3] | proc_7_data_PIPO_blk[3] | proc_7_start_FIFO_blk[3] | proc_7_TLF_FIFO_blk[3] | proc_7_input_sync_blk[3] | proc_7_output_sync_blk[3]);
    assign proc_7_data_FIFO_blk[4] = 1'b0;
    assign proc_7_data_PIPO_blk[4] = 1'b0;
    assign proc_7_start_FIFO_blk[4] = 1'b0;
    assign proc_7_TLF_FIFO_blk[4] = 1'b0;
    assign proc_7_input_sync_blk[4] = 1'b0;
    assign proc_7_output_sync_blk[4] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_7[4] = dl_detect_out ? proc_dep_vld_vec_7_reg[4] : (proc_7_data_FIFO_blk[4] | proc_7_data_PIPO_blk[4] | proc_7_start_FIFO_blk[4] | proc_7_TLF_FIFO_blk[4] | proc_7_input_sync_blk[4] | proc_7_output_sync_blk[4]);
    assign proc_7_data_FIFO_blk[5] = 1'b0;
    assign proc_7_data_PIPO_blk[5] = 1'b0;
    assign proc_7_start_FIFO_blk[5] = 1'b0;
    assign proc_7_TLF_FIFO_blk[5] = 1'b0;
    assign proc_7_input_sync_blk[5] = 1'b0;
    assign proc_7_output_sync_blk[5] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_7[5] = dl_detect_out ? proc_dep_vld_vec_7_reg[5] : (proc_7_data_FIFO_blk[5] | proc_7_data_PIPO_blk[5] | proc_7_start_FIFO_blk[5] | proc_7_TLF_FIFO_blk[5] | proc_7_input_sync_blk[5] | proc_7_output_sync_blk[5]);
    assign proc_7_data_FIFO_blk[6] = 1'b0;
    assign proc_7_data_PIPO_blk[6] = 1'b0;
    assign proc_7_start_FIFO_blk[6] = 1'b0;
    assign proc_7_TLF_FIFO_blk[6] = 1'b0;
    assign proc_7_input_sync_blk[6] = 1'b0;
    assign proc_7_output_sync_blk[6] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_7[6] = dl_detect_out ? proc_dep_vld_vec_7_reg[6] : (proc_7_data_FIFO_blk[6] | proc_7_data_PIPO_blk[6] | proc_7_start_FIFO_blk[6] | proc_7_TLF_FIFO_blk[6] | proc_7_input_sync_blk[6] | proc_7_output_sync_blk[6]);
    assign proc_7_data_FIFO_blk[7] = 1'b0;
    assign proc_7_data_PIPO_blk[7] = 1'b0;
    assign proc_7_start_FIFO_blk[7] = 1'b0;
    assign proc_7_TLF_FIFO_blk[7] = 1'b0;
    assign proc_7_input_sync_blk[7] = 1'b0;
    assign proc_7_output_sync_blk[7] = 1'b0 | (ap_done_reg_5 & grp_cascade_fu_231.thin_stage_5_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_7[7] = dl_detect_out ? proc_dep_vld_vec_7_reg[7] : (proc_7_data_FIFO_blk[7] | proc_7_data_PIPO_blk[7] | proc_7_start_FIFO_blk[7] | proc_7_TLF_FIFO_blk[7] | proc_7_input_sync_blk[7] | proc_7_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_7_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_7_reg <= proc_dep_vld_vec_7;
        end
    end
    assign in_chan_dep_vld_vec_7[0] = dep_chan_vld_2_7;
    assign in_chan_dep_data_vec_7[10 : 0] = dep_chan_data_2_7;
    assign token_in_vec_7[0] = token_2_7;
    assign in_chan_dep_vld_vec_7[1] = dep_chan_vld_3_7;
    assign in_chan_dep_data_vec_7[21 : 11] = dep_chan_data_3_7;
    assign token_in_vec_7[1] = token_3_7;
    assign in_chan_dep_vld_vec_7[2] = dep_chan_vld_4_7;
    assign in_chan_dep_data_vec_7[32 : 22] = dep_chan_data_4_7;
    assign token_in_vec_7[2] = token_4_7;
    assign in_chan_dep_vld_vec_7[3] = dep_chan_vld_5_7;
    assign in_chan_dep_data_vec_7[43 : 33] = dep_chan_data_5_7;
    assign token_in_vec_7[3] = token_5_7;
    assign in_chan_dep_vld_vec_7[4] = dep_chan_vld_6_7;
    assign in_chan_dep_data_vec_7[54 : 44] = dep_chan_data_6_7;
    assign token_in_vec_7[4] = token_6_7;
    assign in_chan_dep_vld_vec_7[5] = dep_chan_vld_8_7;
    assign in_chan_dep_data_vec_7[65 : 55] = dep_chan_data_8_7;
    assign token_in_vec_7[5] = token_8_7;
    assign in_chan_dep_vld_vec_7[6] = dep_chan_vld_9_7;
    assign in_chan_dep_data_vec_7[76 : 66] = dep_chan_data_9_7;
    assign token_in_vec_7[6] = token_9_7;
    assign in_chan_dep_vld_vec_7[7] = dep_chan_vld_10_7;
    assign in_chan_dep_data_vec_7[87 : 77] = dep_chan_data_10_7;
    assign token_in_vec_7[7] = token_10_7;
    assign dep_chan_vld_7_6 = out_chan_dep_vld_vec_7[0];
    assign dep_chan_data_7_6 = out_chan_dep_data_7;
    assign token_7_6 = token_out_vec_7[0];
    assign dep_chan_vld_7_8 = out_chan_dep_vld_vec_7[1];
    assign dep_chan_data_7_8 = out_chan_dep_data_7;
    assign token_7_8 = token_out_vec_7[1];
    assign dep_chan_vld_7_2 = out_chan_dep_vld_vec_7[2];
    assign dep_chan_data_7_2 = out_chan_dep_data_7;
    assign token_7_2 = token_out_vec_7[2];
    assign dep_chan_vld_7_3 = out_chan_dep_vld_vec_7[3];
    assign dep_chan_data_7_3 = out_chan_dep_data_7;
    assign token_7_3 = token_out_vec_7[3];
    assign dep_chan_vld_7_4 = out_chan_dep_vld_vec_7[4];
    assign dep_chan_data_7_4 = out_chan_dep_data_7;
    assign token_7_4 = token_out_vec_7[4];
    assign dep_chan_vld_7_5 = out_chan_dep_vld_vec_7[5];
    assign dep_chan_data_7_5 = out_chan_dep_data_7;
    assign token_7_5 = token_out_vec_7[5];
    assign dep_chan_vld_7_9 = out_chan_dep_vld_vec_7[6];
    assign dep_chan_data_7_9 = out_chan_dep_data_7;
    assign token_7_9 = token_out_vec_7[6];
    assign dep_chan_vld_7_10 = out_chan_dep_vld_vec_7[7];
    assign dep_chan_data_7_10 = out_chan_dep_data_7;
    assign token_7_10 = token_out_vec_7[7];

    // Process: grp_cascade_fu_231.thin_stage_6_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 8, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_8 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_8),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_8),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_8),
        .token_in_vec(token_in_vec_8),
        .dl_detect_in(dl_detect_out),
        .origin(origin[8]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_8),
        .out_chan_dep_data(out_chan_dep_data_8),
        .token_out_vec(token_out_vec_8),
        .dl_detect_out(dl_in_vec[8]));

    assign proc_8_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_6_U0.grp_thin_stage_6_Pipeline_VITIS_LOOP_44_4_fu_128.s_6_blk_n) | (~grp_cascade_fu_231.thin_stage_6_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_6_U0.h_blk_n);
    assign proc_8_data_PIPO_blk[0] = 1'b0;
    assign proc_8_start_FIFO_blk[0] = 1'b0;
    assign proc_8_TLF_FIFO_blk[0] = 1'b0;
    assign proc_8_input_sync_blk[0] = 1'b0;
    assign proc_8_output_sync_blk[0] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_8[0] = dl_detect_out ? proc_dep_vld_vec_8_reg[0] : (proc_8_data_FIFO_blk[0] | proc_8_data_PIPO_blk[0] | proc_8_start_FIFO_blk[0] | proc_8_TLF_FIFO_blk[0] | proc_8_input_sync_blk[0] | proc_8_output_sync_blk[0]);
    assign proc_8_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_6_U0.grp_thin_stage_6_Pipeline_VITIS_LOOP_44_4_fu_128.s_7_blk_n) | (~grp_cascade_fu_231.thin_stage_6_U0.w_c_blk_n) | (~grp_cascade_fu_231.thin_stage_6_U0.h_c_blk_n);
    assign proc_8_data_PIPO_blk[1] = 1'b0;
    assign proc_8_start_FIFO_blk[1] = 1'b0;
    assign proc_8_TLF_FIFO_blk[1] = 1'b0;
    assign proc_8_input_sync_blk[1] = 1'b0;
    assign proc_8_output_sync_blk[1] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_8[1] = dl_detect_out ? proc_dep_vld_vec_8_reg[1] : (proc_8_data_FIFO_blk[1] | proc_8_data_PIPO_blk[1] | proc_8_start_FIFO_blk[1] | proc_8_TLF_FIFO_blk[1] | proc_8_input_sync_blk[1] | proc_8_output_sync_blk[1]);
    assign proc_8_data_FIFO_blk[2] = 1'b0;
    assign proc_8_data_PIPO_blk[2] = 1'b0;
    assign proc_8_start_FIFO_blk[2] = 1'b0;
    assign proc_8_TLF_FIFO_blk[2] = 1'b0;
    assign proc_8_input_sync_blk[2] = 1'b0;
    assign proc_8_output_sync_blk[2] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_8[2] = dl_detect_out ? proc_dep_vld_vec_8_reg[2] : (proc_8_data_FIFO_blk[2] | proc_8_data_PIPO_blk[2] | proc_8_start_FIFO_blk[2] | proc_8_TLF_FIFO_blk[2] | proc_8_input_sync_blk[2] | proc_8_output_sync_blk[2]);
    assign proc_8_data_FIFO_blk[3] = 1'b0;
    assign proc_8_data_PIPO_blk[3] = 1'b0;
    assign proc_8_start_FIFO_blk[3] = 1'b0;
    assign proc_8_TLF_FIFO_blk[3] = 1'b0;
    assign proc_8_input_sync_blk[3] = 1'b0;
    assign proc_8_output_sync_blk[3] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_8[3] = dl_detect_out ? proc_dep_vld_vec_8_reg[3] : (proc_8_data_FIFO_blk[3] | proc_8_data_PIPO_blk[3] | proc_8_start_FIFO_blk[3] | proc_8_TLF_FIFO_blk[3] | proc_8_input_sync_blk[3] | proc_8_output_sync_blk[3]);
    assign proc_8_data_FIFO_blk[4] = 1'b0;
    assign proc_8_data_PIPO_blk[4] = 1'b0;
    assign proc_8_start_FIFO_blk[4] = 1'b0;
    assign proc_8_TLF_FIFO_blk[4] = 1'b0;
    assign proc_8_input_sync_blk[4] = 1'b0;
    assign proc_8_output_sync_blk[4] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_8[4] = dl_detect_out ? proc_dep_vld_vec_8_reg[4] : (proc_8_data_FIFO_blk[4] | proc_8_data_PIPO_blk[4] | proc_8_start_FIFO_blk[4] | proc_8_TLF_FIFO_blk[4] | proc_8_input_sync_blk[4] | proc_8_output_sync_blk[4]);
    assign proc_8_data_FIFO_blk[5] = 1'b0;
    assign proc_8_data_PIPO_blk[5] = 1'b0;
    assign proc_8_start_FIFO_blk[5] = 1'b0;
    assign proc_8_TLF_FIFO_blk[5] = 1'b0;
    assign proc_8_input_sync_blk[5] = 1'b0;
    assign proc_8_output_sync_blk[5] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_8[5] = dl_detect_out ? proc_dep_vld_vec_8_reg[5] : (proc_8_data_FIFO_blk[5] | proc_8_data_PIPO_blk[5] | proc_8_start_FIFO_blk[5] | proc_8_TLF_FIFO_blk[5] | proc_8_input_sync_blk[5] | proc_8_output_sync_blk[5]);
    assign proc_8_data_FIFO_blk[6] = 1'b0;
    assign proc_8_data_PIPO_blk[6] = 1'b0;
    assign proc_8_start_FIFO_blk[6] = 1'b0;
    assign proc_8_TLF_FIFO_blk[6] = 1'b0;
    assign proc_8_input_sync_blk[6] = 1'b0;
    assign proc_8_output_sync_blk[6] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_8[6] = dl_detect_out ? proc_dep_vld_vec_8_reg[6] : (proc_8_data_FIFO_blk[6] | proc_8_data_PIPO_blk[6] | proc_8_start_FIFO_blk[6] | proc_8_TLF_FIFO_blk[6] | proc_8_input_sync_blk[6] | proc_8_output_sync_blk[6]);
    assign proc_8_data_FIFO_blk[7] = 1'b0;
    assign proc_8_data_PIPO_blk[7] = 1'b0;
    assign proc_8_start_FIFO_blk[7] = 1'b0;
    assign proc_8_TLF_FIFO_blk[7] = 1'b0;
    assign proc_8_input_sync_blk[7] = 1'b0;
    assign proc_8_output_sync_blk[7] = 1'b0 | (ap_done_reg_6 & grp_cascade_fu_231.thin_stage_6_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_8[7] = dl_detect_out ? proc_dep_vld_vec_8_reg[7] : (proc_8_data_FIFO_blk[7] | proc_8_data_PIPO_blk[7] | proc_8_start_FIFO_blk[7] | proc_8_TLF_FIFO_blk[7] | proc_8_input_sync_blk[7] | proc_8_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_8_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_8_reg <= proc_dep_vld_vec_8;
        end
    end
    assign in_chan_dep_vld_vec_8[0] = dep_chan_vld_2_8;
    assign in_chan_dep_data_vec_8[10 : 0] = dep_chan_data_2_8;
    assign token_in_vec_8[0] = token_2_8;
    assign in_chan_dep_vld_vec_8[1] = dep_chan_vld_3_8;
    assign in_chan_dep_data_vec_8[21 : 11] = dep_chan_data_3_8;
    assign token_in_vec_8[1] = token_3_8;
    assign in_chan_dep_vld_vec_8[2] = dep_chan_vld_4_8;
    assign in_chan_dep_data_vec_8[32 : 22] = dep_chan_data_4_8;
    assign token_in_vec_8[2] = token_4_8;
    assign in_chan_dep_vld_vec_8[3] = dep_chan_vld_5_8;
    assign in_chan_dep_data_vec_8[43 : 33] = dep_chan_data_5_8;
    assign token_in_vec_8[3] = token_5_8;
    assign in_chan_dep_vld_vec_8[4] = dep_chan_vld_6_8;
    assign in_chan_dep_data_vec_8[54 : 44] = dep_chan_data_6_8;
    assign token_in_vec_8[4] = token_6_8;
    assign in_chan_dep_vld_vec_8[5] = dep_chan_vld_7_8;
    assign in_chan_dep_data_vec_8[65 : 55] = dep_chan_data_7_8;
    assign token_in_vec_8[5] = token_7_8;
    assign in_chan_dep_vld_vec_8[6] = dep_chan_vld_9_8;
    assign in_chan_dep_data_vec_8[76 : 66] = dep_chan_data_9_8;
    assign token_in_vec_8[6] = token_9_8;
    assign in_chan_dep_vld_vec_8[7] = dep_chan_vld_10_8;
    assign in_chan_dep_data_vec_8[87 : 77] = dep_chan_data_10_8;
    assign token_in_vec_8[7] = token_10_8;
    assign dep_chan_vld_8_7 = out_chan_dep_vld_vec_8[0];
    assign dep_chan_data_8_7 = out_chan_dep_data_8;
    assign token_8_7 = token_out_vec_8[0];
    assign dep_chan_vld_8_9 = out_chan_dep_vld_vec_8[1];
    assign dep_chan_data_8_9 = out_chan_dep_data_8;
    assign token_8_9 = token_out_vec_8[1];
    assign dep_chan_vld_8_2 = out_chan_dep_vld_vec_8[2];
    assign dep_chan_data_8_2 = out_chan_dep_data_8;
    assign token_8_2 = token_out_vec_8[2];
    assign dep_chan_vld_8_3 = out_chan_dep_vld_vec_8[3];
    assign dep_chan_data_8_3 = out_chan_dep_data_8;
    assign token_8_3 = token_out_vec_8[3];
    assign dep_chan_vld_8_4 = out_chan_dep_vld_vec_8[4];
    assign dep_chan_data_8_4 = out_chan_dep_data_8;
    assign token_8_4 = token_out_vec_8[4];
    assign dep_chan_vld_8_5 = out_chan_dep_vld_vec_8[5];
    assign dep_chan_data_8_5 = out_chan_dep_data_8;
    assign token_8_5 = token_out_vec_8[5];
    assign dep_chan_vld_8_6 = out_chan_dep_vld_vec_8[6];
    assign dep_chan_data_8_6 = out_chan_dep_data_8;
    assign token_8_6 = token_out_vec_8[6];
    assign dep_chan_vld_8_10 = out_chan_dep_vld_vec_8[7];
    assign dep_chan_data_8_10 = out_chan_dep_data_8;
    assign token_8_10 = token_out_vec_8[7];

    // Process: grp_cascade_fu_231.thin_stage_7_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 9, 8, 8) tcb_lineart_accel_hls_deadlock_detect_unit_9 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_9),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_9),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_9),
        .token_in_vec(token_in_vec_9),
        .dl_detect_in(dl_detect_out),
        .origin(origin[9]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_9),
        .out_chan_dep_data(out_chan_dep_data_9),
        .token_out_vec(token_out_vec_9),
        .dl_detect_out(dl_in_vec[9]));

    assign proc_9_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.thin_stage_7_U0.grp_thin_stage_7_Pipeline_VITIS_LOOP_44_4_fu_106.s_7_blk_n) | (~grp_cascade_fu_231.thin_stage_7_U0.w_blk_n) | (~grp_cascade_fu_231.thin_stage_7_U0.h_blk_n);
    assign proc_9_data_PIPO_blk[0] = 1'b0;
    assign proc_9_start_FIFO_blk[0] = 1'b0;
    assign proc_9_TLF_FIFO_blk[0] = 1'b0;
    assign proc_9_input_sync_blk[0] = 1'b0;
    assign proc_9_output_sync_blk[0] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_9[0] = dl_detect_out ? proc_dep_vld_vec_9_reg[0] : (proc_9_data_FIFO_blk[0] | proc_9_data_PIPO_blk[0] | proc_9_start_FIFO_blk[0] | proc_9_TLF_FIFO_blk[0] | proc_9_input_sync_blk[0] | proc_9_output_sync_blk[0]);
    assign proc_9_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.thin_stage_7_U0.grp_thin_stage_7_Pipeline_VITIS_LOOP_44_4_fu_106.s_8_blk_n);
    assign proc_9_data_PIPO_blk[1] = 1'b0;
    assign proc_9_start_FIFO_blk[1] = 1'b0;
    assign proc_9_TLF_FIFO_blk[1] = 1'b0;
    assign proc_9_input_sync_blk[1] = 1'b0;
    assign proc_9_output_sync_blk[1] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.pack_U0.ap_done);
    assign proc_dep_vld_vec_9[1] = dl_detect_out ? proc_dep_vld_vec_9_reg[1] : (proc_9_data_FIFO_blk[1] | proc_9_data_PIPO_blk[1] | proc_9_start_FIFO_blk[1] | proc_9_TLF_FIFO_blk[1] | proc_9_input_sync_blk[1] | proc_9_output_sync_blk[1]);
    assign proc_9_data_FIFO_blk[2] = 1'b0;
    assign proc_9_data_PIPO_blk[2] = 1'b0;
    assign proc_9_start_FIFO_blk[2] = 1'b0;
    assign proc_9_TLF_FIFO_blk[2] = 1'b0;
    assign proc_9_input_sync_blk[2] = 1'b0;
    assign proc_9_output_sync_blk[2] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_9[2] = dl_detect_out ? proc_dep_vld_vec_9_reg[2] : (proc_9_data_FIFO_blk[2] | proc_9_data_PIPO_blk[2] | proc_9_start_FIFO_blk[2] | proc_9_TLF_FIFO_blk[2] | proc_9_input_sync_blk[2] | proc_9_output_sync_blk[2]);
    assign proc_9_data_FIFO_blk[3] = 1'b0;
    assign proc_9_data_PIPO_blk[3] = 1'b0;
    assign proc_9_start_FIFO_blk[3] = 1'b0;
    assign proc_9_TLF_FIFO_blk[3] = 1'b0;
    assign proc_9_input_sync_blk[3] = 1'b0;
    assign proc_9_output_sync_blk[3] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_9[3] = dl_detect_out ? proc_dep_vld_vec_9_reg[3] : (proc_9_data_FIFO_blk[3] | proc_9_data_PIPO_blk[3] | proc_9_start_FIFO_blk[3] | proc_9_TLF_FIFO_blk[3] | proc_9_input_sync_blk[3] | proc_9_output_sync_blk[3]);
    assign proc_9_data_FIFO_blk[4] = 1'b0;
    assign proc_9_data_PIPO_blk[4] = 1'b0;
    assign proc_9_start_FIFO_blk[4] = 1'b0;
    assign proc_9_TLF_FIFO_blk[4] = 1'b0;
    assign proc_9_input_sync_blk[4] = 1'b0;
    assign proc_9_output_sync_blk[4] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_9[4] = dl_detect_out ? proc_dep_vld_vec_9_reg[4] : (proc_9_data_FIFO_blk[4] | proc_9_data_PIPO_blk[4] | proc_9_start_FIFO_blk[4] | proc_9_TLF_FIFO_blk[4] | proc_9_input_sync_blk[4] | proc_9_output_sync_blk[4]);
    assign proc_9_data_FIFO_blk[5] = 1'b0;
    assign proc_9_data_PIPO_blk[5] = 1'b0;
    assign proc_9_start_FIFO_blk[5] = 1'b0;
    assign proc_9_TLF_FIFO_blk[5] = 1'b0;
    assign proc_9_input_sync_blk[5] = 1'b0;
    assign proc_9_output_sync_blk[5] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_9[5] = dl_detect_out ? proc_dep_vld_vec_9_reg[5] : (proc_9_data_FIFO_blk[5] | proc_9_data_PIPO_blk[5] | proc_9_start_FIFO_blk[5] | proc_9_TLF_FIFO_blk[5] | proc_9_input_sync_blk[5] | proc_9_output_sync_blk[5]);
    assign proc_9_data_FIFO_blk[6] = 1'b0;
    assign proc_9_data_PIPO_blk[6] = 1'b0;
    assign proc_9_start_FIFO_blk[6] = 1'b0;
    assign proc_9_TLF_FIFO_blk[6] = 1'b0;
    assign proc_9_input_sync_blk[6] = 1'b0;
    assign proc_9_output_sync_blk[6] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_9[6] = dl_detect_out ? proc_dep_vld_vec_9_reg[6] : (proc_9_data_FIFO_blk[6] | proc_9_data_PIPO_blk[6] | proc_9_start_FIFO_blk[6] | proc_9_TLF_FIFO_blk[6] | proc_9_input_sync_blk[6] | proc_9_output_sync_blk[6]);
    assign proc_9_data_FIFO_blk[7] = 1'b0;
    assign proc_9_data_PIPO_blk[7] = 1'b0;
    assign proc_9_start_FIFO_blk[7] = 1'b0;
    assign proc_9_TLF_FIFO_blk[7] = 1'b0;
    assign proc_9_input_sync_blk[7] = 1'b0;
    assign proc_9_output_sync_blk[7] = 1'b0 | (ap_done_reg_7 & grp_cascade_fu_231.thin_stage_7_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_9[7] = dl_detect_out ? proc_dep_vld_vec_9_reg[7] : (proc_9_data_FIFO_blk[7] | proc_9_data_PIPO_blk[7] | proc_9_start_FIFO_blk[7] | proc_9_TLF_FIFO_blk[7] | proc_9_input_sync_blk[7] | proc_9_output_sync_blk[7]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_9_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_9_reg <= proc_dep_vld_vec_9;
        end
    end
    assign in_chan_dep_vld_vec_9[0] = dep_chan_vld_2_9;
    assign in_chan_dep_data_vec_9[10 : 0] = dep_chan_data_2_9;
    assign token_in_vec_9[0] = token_2_9;
    assign in_chan_dep_vld_vec_9[1] = dep_chan_vld_3_9;
    assign in_chan_dep_data_vec_9[21 : 11] = dep_chan_data_3_9;
    assign token_in_vec_9[1] = token_3_9;
    assign in_chan_dep_vld_vec_9[2] = dep_chan_vld_4_9;
    assign in_chan_dep_data_vec_9[32 : 22] = dep_chan_data_4_9;
    assign token_in_vec_9[2] = token_4_9;
    assign in_chan_dep_vld_vec_9[3] = dep_chan_vld_5_9;
    assign in_chan_dep_data_vec_9[43 : 33] = dep_chan_data_5_9;
    assign token_in_vec_9[3] = token_5_9;
    assign in_chan_dep_vld_vec_9[4] = dep_chan_vld_6_9;
    assign in_chan_dep_data_vec_9[54 : 44] = dep_chan_data_6_9;
    assign token_in_vec_9[4] = token_6_9;
    assign in_chan_dep_vld_vec_9[5] = dep_chan_vld_7_9;
    assign in_chan_dep_data_vec_9[65 : 55] = dep_chan_data_7_9;
    assign token_in_vec_9[5] = token_7_9;
    assign in_chan_dep_vld_vec_9[6] = dep_chan_vld_8_9;
    assign in_chan_dep_data_vec_9[76 : 66] = dep_chan_data_8_9;
    assign token_in_vec_9[6] = token_8_9;
    assign in_chan_dep_vld_vec_9[7] = dep_chan_vld_10_9;
    assign in_chan_dep_data_vec_9[87 : 77] = dep_chan_data_10_9;
    assign token_in_vec_9[7] = token_10_9;
    assign dep_chan_vld_9_8 = out_chan_dep_vld_vec_9[0];
    assign dep_chan_data_9_8 = out_chan_dep_data_9;
    assign token_9_8 = token_out_vec_9[0];
    assign dep_chan_vld_9_10 = out_chan_dep_vld_vec_9[1];
    assign dep_chan_data_9_10 = out_chan_dep_data_9;
    assign token_9_10 = token_out_vec_9[1];
    assign dep_chan_vld_9_2 = out_chan_dep_vld_vec_9[2];
    assign dep_chan_data_9_2 = out_chan_dep_data_9;
    assign token_9_2 = token_out_vec_9[2];
    assign dep_chan_vld_9_3 = out_chan_dep_vld_vec_9[3];
    assign dep_chan_data_9_3 = out_chan_dep_data_9;
    assign token_9_3 = token_out_vec_9[3];
    assign dep_chan_vld_9_4 = out_chan_dep_vld_vec_9[4];
    assign dep_chan_data_9_4 = out_chan_dep_data_9;
    assign token_9_4 = token_out_vec_9[4];
    assign dep_chan_vld_9_5 = out_chan_dep_vld_vec_9[5];
    assign dep_chan_data_9_5 = out_chan_dep_data_9;
    assign token_9_5 = token_out_vec_9[5];
    assign dep_chan_vld_9_6 = out_chan_dep_vld_vec_9[6];
    assign dep_chan_data_9_6 = out_chan_dep_data_9;
    assign token_9_6 = token_out_vec_9[6];
    assign dep_chan_vld_9_7 = out_chan_dep_vld_vec_9[7];
    assign dep_chan_data_9_7 = out_chan_dep_data_9;
    assign token_9_7 = token_out_vec_9[7];

    // Process: grp_cascade_fu_231.pack_U0
    tcb_lineart_accel_hls_deadlock_detect_unit #(11, 10, 10, 10) tcb_lineart_accel_hls_deadlock_detect_unit_10 (
        .reset(dl_reset),
        .clock(dl_clock),
        .proc_dep_vld_vec(proc_dep_vld_vec_10),
        .in_chan_dep_vld_vec(in_chan_dep_vld_vec_10),
        .in_chan_dep_data_vec(in_chan_dep_data_vec_10),
        .token_in_vec(token_in_vec_10),
        .dl_detect_in(dl_detect_out),
        .origin(origin[10]),
        .token_clear(token_clear),
        .out_chan_dep_vld_vec(out_chan_dep_vld_vec_10),
        .out_chan_dep_data(out_chan_dep_data_10),
        .token_out_vec(token_out_vec_10),
        .dl_detect_out(dl_in_vec[10]));

    assign proc_10_data_FIFO_blk[0] = 1'b0 | (~grp_cascade_fu_231.pack_U0.grp_pack_Pipeline_VITIS_LOOP_14_1_VITIS_LOOP_16_2_fu_85.s_8_blk_n);
    assign proc_10_data_PIPO_blk[0] = 1'b0;
    assign proc_10_start_FIFO_blk[0] = 1'b0;
    assign proc_10_TLF_FIFO_blk[0] = 1'b0;
    assign proc_10_input_sync_blk[0] = 1'b0;
    assign proc_10_output_sync_blk[0] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_7_U0.ap_done);
    assign proc_dep_vld_vec_10[0] = dl_detect_out ? proc_dep_vld_vec_10_reg[0] : (proc_10_data_FIFO_blk[0] | proc_10_data_PIPO_blk[0] | proc_10_start_FIFO_blk[0] | proc_10_TLF_FIFO_blk[0] | proc_10_input_sync_blk[0] | proc_10_output_sync_blk[0]);
    assign proc_10_data_FIFO_blk[1] = 1'b0 | (~grp_cascade_fu_231.pack_U0.dst_blk_n);
    assign proc_10_data_PIPO_blk[1] = 1'b0;
    assign proc_10_start_FIFO_blk[1] = 1'b0;
    assign proc_10_TLF_FIFO_blk[1] = 1'b0;
    assign proc_10_input_sync_blk[1] = 1'b0;
    assign proc_10_output_sync_blk[1] = 1'b0;
    assign proc_dep_vld_vec_10[1] = dl_detect_out ? proc_dep_vld_vec_10_reg[1] : (proc_10_data_FIFO_blk[1] | proc_10_data_PIPO_blk[1] | proc_10_start_FIFO_blk[1] | proc_10_TLF_FIFO_blk[1] | proc_10_input_sync_blk[1] | proc_10_output_sync_blk[1]);
    assign proc_10_data_FIFO_blk[2] = 1'b0 | (~grp_cascade_fu_231.pack_U0.n_blk_n);
    assign proc_10_data_PIPO_blk[2] = 1'b0;
    assign proc_10_start_FIFO_blk[2] = 1'b0;
    assign proc_10_TLF_FIFO_blk[2] = 1'b0;
    assign proc_10_input_sync_blk[2] = 1'b0;
    assign proc_10_output_sync_blk[2] = 1'b0;
    assign proc_dep_vld_vec_10[2] = dl_detect_out ? proc_dep_vld_vec_10_reg[2] : (proc_10_data_FIFO_blk[2] | proc_10_data_PIPO_blk[2] | proc_10_start_FIFO_blk[2] | proc_10_TLF_FIFO_blk[2] | proc_10_input_sync_blk[2] | proc_10_output_sync_blk[2]);
    assign proc_10_data_FIFO_blk[3] = 1'b0;
    assign proc_10_data_PIPO_blk[3] = 1'b0;
    assign proc_10_start_FIFO_blk[3] = 1'b0;
    assign proc_10_TLF_FIFO_blk[3] = 1'b0;
    assign proc_10_input_sync_blk[3] = 1'b0;
    assign proc_10_output_sync_blk[3] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_0_U0.ap_done);
    assign proc_dep_vld_vec_10[3] = dl_detect_out ? proc_dep_vld_vec_10_reg[3] : (proc_10_data_FIFO_blk[3] | proc_10_data_PIPO_blk[3] | proc_10_start_FIFO_blk[3] | proc_10_TLF_FIFO_blk[3] | proc_10_input_sync_blk[3] | proc_10_output_sync_blk[3]);
    assign proc_10_data_FIFO_blk[4] = 1'b0;
    assign proc_10_data_PIPO_blk[4] = 1'b0;
    assign proc_10_start_FIFO_blk[4] = 1'b0;
    assign proc_10_TLF_FIFO_blk[4] = 1'b0;
    assign proc_10_input_sync_blk[4] = 1'b0;
    assign proc_10_output_sync_blk[4] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_1_U0.ap_done);
    assign proc_dep_vld_vec_10[4] = dl_detect_out ? proc_dep_vld_vec_10_reg[4] : (proc_10_data_FIFO_blk[4] | proc_10_data_PIPO_blk[4] | proc_10_start_FIFO_blk[4] | proc_10_TLF_FIFO_blk[4] | proc_10_input_sync_blk[4] | proc_10_output_sync_blk[4]);
    assign proc_10_data_FIFO_blk[5] = 1'b0;
    assign proc_10_data_PIPO_blk[5] = 1'b0;
    assign proc_10_start_FIFO_blk[5] = 1'b0;
    assign proc_10_TLF_FIFO_blk[5] = 1'b0;
    assign proc_10_input_sync_blk[5] = 1'b0;
    assign proc_10_output_sync_blk[5] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_2_U0.ap_done);
    assign proc_dep_vld_vec_10[5] = dl_detect_out ? proc_dep_vld_vec_10_reg[5] : (proc_10_data_FIFO_blk[5] | proc_10_data_PIPO_blk[5] | proc_10_start_FIFO_blk[5] | proc_10_TLF_FIFO_blk[5] | proc_10_input_sync_blk[5] | proc_10_output_sync_blk[5]);
    assign proc_10_data_FIFO_blk[6] = 1'b0;
    assign proc_10_data_PIPO_blk[6] = 1'b0;
    assign proc_10_start_FIFO_blk[6] = 1'b0;
    assign proc_10_TLF_FIFO_blk[6] = 1'b0;
    assign proc_10_input_sync_blk[6] = 1'b0;
    assign proc_10_output_sync_blk[6] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_3_U0.ap_done);
    assign proc_dep_vld_vec_10[6] = dl_detect_out ? proc_dep_vld_vec_10_reg[6] : (proc_10_data_FIFO_blk[6] | proc_10_data_PIPO_blk[6] | proc_10_start_FIFO_blk[6] | proc_10_TLF_FIFO_blk[6] | proc_10_input_sync_blk[6] | proc_10_output_sync_blk[6]);
    assign proc_10_data_FIFO_blk[7] = 1'b0;
    assign proc_10_data_PIPO_blk[7] = 1'b0;
    assign proc_10_start_FIFO_blk[7] = 1'b0;
    assign proc_10_TLF_FIFO_blk[7] = 1'b0;
    assign proc_10_input_sync_blk[7] = 1'b0;
    assign proc_10_output_sync_blk[7] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_4_U0.ap_done);
    assign proc_dep_vld_vec_10[7] = dl_detect_out ? proc_dep_vld_vec_10_reg[7] : (proc_10_data_FIFO_blk[7] | proc_10_data_PIPO_blk[7] | proc_10_start_FIFO_blk[7] | proc_10_TLF_FIFO_blk[7] | proc_10_input_sync_blk[7] | proc_10_output_sync_blk[7]);
    assign proc_10_data_FIFO_blk[8] = 1'b0;
    assign proc_10_data_PIPO_blk[8] = 1'b0;
    assign proc_10_start_FIFO_blk[8] = 1'b0;
    assign proc_10_TLF_FIFO_blk[8] = 1'b0;
    assign proc_10_input_sync_blk[8] = 1'b0;
    assign proc_10_output_sync_blk[8] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_5_U0.ap_done);
    assign proc_dep_vld_vec_10[8] = dl_detect_out ? proc_dep_vld_vec_10_reg[8] : (proc_10_data_FIFO_blk[8] | proc_10_data_PIPO_blk[8] | proc_10_start_FIFO_blk[8] | proc_10_TLF_FIFO_blk[8] | proc_10_input_sync_blk[8] | proc_10_output_sync_blk[8]);
    assign proc_10_data_FIFO_blk[9] = 1'b0;
    assign proc_10_data_PIPO_blk[9] = 1'b0;
    assign proc_10_start_FIFO_blk[9] = 1'b0;
    assign proc_10_TLF_FIFO_blk[9] = 1'b0;
    assign proc_10_input_sync_blk[9] = 1'b0;
    assign proc_10_output_sync_blk[9] = 1'b0 | (ap_done_reg_8 & grp_cascade_fu_231.pack_U0.ap_done & ~grp_cascade_fu_231.thin_stage_6_U0.ap_done);
    assign proc_dep_vld_vec_10[9] = dl_detect_out ? proc_dep_vld_vec_10_reg[9] : (proc_10_data_FIFO_blk[9] | proc_10_data_PIPO_blk[9] | proc_10_start_FIFO_blk[9] | proc_10_TLF_FIFO_blk[9] | proc_10_input_sync_blk[9] | proc_10_output_sync_blk[9]);
    always @ (negedge dl_reset or posedge dl_clock) begin
        if (~dl_reset) begin
            proc_dep_vld_vec_10_reg <= 'b0;
        end
        else begin
            proc_dep_vld_vec_10_reg <= proc_dep_vld_vec_10;
        end
    end
    assign in_chan_dep_vld_vec_10[0] = dep_chan_vld_0_10;
    assign in_chan_dep_data_vec_10[10 : 0] = dep_chan_data_0_10;
    assign token_in_vec_10[0] = token_0_10;
    assign in_chan_dep_vld_vec_10[1] = dep_chan_vld_1_10;
    assign in_chan_dep_data_vec_10[21 : 11] = dep_chan_data_1_10;
    assign token_in_vec_10[1] = token_1_10;
    assign in_chan_dep_vld_vec_10[2] = dep_chan_vld_2_10;
    assign in_chan_dep_data_vec_10[32 : 22] = dep_chan_data_2_10;
    assign token_in_vec_10[2] = token_2_10;
    assign in_chan_dep_vld_vec_10[3] = dep_chan_vld_3_10;
    assign in_chan_dep_data_vec_10[43 : 33] = dep_chan_data_3_10;
    assign token_in_vec_10[3] = token_3_10;
    assign in_chan_dep_vld_vec_10[4] = dep_chan_vld_4_10;
    assign in_chan_dep_data_vec_10[54 : 44] = dep_chan_data_4_10;
    assign token_in_vec_10[4] = token_4_10;
    assign in_chan_dep_vld_vec_10[5] = dep_chan_vld_5_10;
    assign in_chan_dep_data_vec_10[65 : 55] = dep_chan_data_5_10;
    assign token_in_vec_10[5] = token_5_10;
    assign in_chan_dep_vld_vec_10[6] = dep_chan_vld_6_10;
    assign in_chan_dep_data_vec_10[76 : 66] = dep_chan_data_6_10;
    assign token_in_vec_10[6] = token_6_10;
    assign in_chan_dep_vld_vec_10[7] = dep_chan_vld_7_10;
    assign in_chan_dep_data_vec_10[87 : 77] = dep_chan_data_7_10;
    assign token_in_vec_10[7] = token_7_10;
    assign in_chan_dep_vld_vec_10[8] = dep_chan_vld_8_10;
    assign in_chan_dep_data_vec_10[98 : 88] = dep_chan_data_8_10;
    assign token_in_vec_10[8] = token_8_10;
    assign in_chan_dep_vld_vec_10[9] = dep_chan_vld_9_10;
    assign in_chan_dep_data_vec_10[109 : 99] = dep_chan_data_9_10;
    assign token_in_vec_10[9] = token_9_10;
    assign dep_chan_vld_10_9 = out_chan_dep_vld_vec_10[0];
    assign dep_chan_data_10_9 = out_chan_dep_data_10;
    assign token_10_9 = token_out_vec_10[0];
    assign dep_chan_vld_10_0 = out_chan_dep_vld_vec_10[1];
    assign dep_chan_data_10_0 = out_chan_dep_data_10;
    assign token_10_0 = token_out_vec_10[1];
    assign dep_chan_vld_10_1 = out_chan_dep_vld_vec_10[2];
    assign dep_chan_data_10_1 = out_chan_dep_data_10;
    assign token_10_1 = token_out_vec_10[2];
    assign dep_chan_vld_10_2 = out_chan_dep_vld_vec_10[3];
    assign dep_chan_data_10_2 = out_chan_dep_data_10;
    assign token_10_2 = token_out_vec_10[3];
    assign dep_chan_vld_10_3 = out_chan_dep_vld_vec_10[4];
    assign dep_chan_data_10_3 = out_chan_dep_data_10;
    assign token_10_3 = token_out_vec_10[4];
    assign dep_chan_vld_10_4 = out_chan_dep_vld_vec_10[5];
    assign dep_chan_data_10_4 = out_chan_dep_data_10;
    assign token_10_4 = token_out_vec_10[5];
    assign dep_chan_vld_10_5 = out_chan_dep_vld_vec_10[6];
    assign dep_chan_data_10_5 = out_chan_dep_data_10;
    assign token_10_5 = token_out_vec_10[6];
    assign dep_chan_vld_10_6 = out_chan_dep_vld_vec_10[7];
    assign dep_chan_data_10_6 = out_chan_dep_data_10;
    assign token_10_6 = token_out_vec_10[7];
    assign dep_chan_vld_10_7 = out_chan_dep_vld_vec_10[8];
    assign dep_chan_data_10_7 = out_chan_dep_data_10;
    assign token_10_7 = token_out_vec_10[8];
    assign dep_chan_vld_10_8 = out_chan_dep_vld_vec_10[9];
    assign dep_chan_data_10_8 = out_chan_dep_data_10;
    assign token_10_8 = token_out_vec_10[9];


`include "tcb_lineart_accel_hls_deadlock_report_unit.vh"
