#pragma once
#include <ap_int.h>

// tcb705-brushrecog-v1.  brush_vision/model.py is the bit-exact reference and
// brush_vision/contract.py documents the parameter / result word layouts.
#define BR_IDENTITY      0x42524331u   /* "BRC1" */
#define BR_W             640
#define BR_H             480
#define BR_FRAME_WORDS   4800          /* 640x480 bits as u64, row-major LSB first */
#define BR_MAX_RECT      320
#define BR_RECT_WPR      5             /* u64 words per rectified row */
#define BR_RECT_WORDS    (BR_MAX_RECT * BR_RECT_WPR)
#define BR_PROJ_COL      1600          /* dst word offset of column projection */
#define BR_PROJ_ROW      1680          /* dst word offset of row projection */
#define BR_N             64
#define BR_BOX           56
#define BR_ZONES         8
#define BR_FEATURES      256
#define BR_FEAT_WORDS    32
#define BR_IMG_WORDS     64
#define BR_FEATURE_SUM   8192
#define BR_MAX_BOXES     16
#define BR_RESULT_WORDS  128
#define BR_MAX_TEMPLATES 4096
#define BR_PARAM_BOXES   2
#define BR_PARAM_EXPECT  18
#define BR_PARAM_CAND    34
#define BR_PARAM_WORDS   (BR_PARAM_CAND + BR_MAX_TEMPLATES / 4)

#define BR_MODE_RECTIFY   1
#define BR_MODE_RECOGNISE 2
#define BR_MODE_PREPROCESS 3
#define BR_YUYV_WORDS     76800         /* 640x480 YUYV bytes as u64 */
#define BR_STATS_WORD     4800          /* mode 3: dst word after the binary frame */

int tcb_brush_recog(unsigned mode, const ap_uint<64>* params, const ap_uint<64>* src,
                    ap_uint<64>* dst, const ap_uint<64>* tpl, unsigned& identity);
