#include "tcb_lineart_accel.h"
#include <hls_stream.h>

static void unpack(const ap_uint<64>* src, hls::stream<ap_uint<1>>& out, unsigned n) {
    for (unsigned word=0; word<(n+63)/64; ++word) {
        ap_uint<64> data=src[word];
        for (unsigned bit=0; bit<64; ++bit) {
#pragma HLS PIPELINE II=1
            if(word*64+bit<n) out.write(data[bit]);
        }
    }
}
static void pack(hls::stream<ap_uint<1>>& in, ap_uint<64>* dst, unsigned n) {
    for (unsigned word=0; word<(n+63)/64; ++word) {
        ap_uint<64> data=0;
        for (unsigned bit=0; bit<64; ++bit) {
#pragma HLS PIPELINE II=1
            if(word*64+bit<n) data[bit]=in.read();
        }
        dst[word]=data;
    }
}

// One stage consumes/produces exactly width*height pixels, with zero outside.
// The two previous rows share one 2-bit-wide RAM; no full-frame on-chip buffer.
template<int STAGE>
static void thin_stage(hls::stream<ap_uint<1>>& in, hls::stream<ap_uint<1>>& out,
                       ap_uint<11> w, ap_uint<11> h, bool &changed) {
#pragma HLS INLINE off
    ap_uint<2> rows[LINEART_MAX_DIM];
#pragma HLS BIND_STORAGE variable=rows type=ram_t2p impl=bram
    ap_uint<1> win[3][3];
#pragma HLS ARRAY_PARTITION variable=win complete dim=0
    bool any_removed=false;
    for(ap_uint<11> y=0;y<=h;++y) {
#pragma HLS LOOP_FLATTEN off
        for(unsigned r=0;r<3;++r) {
#pragma HLS UNROLL
            for(unsigned c=0;c<3;++c) {
#pragma HLS UNROLL
                win[r][c]=0;
            }
        }
        for(ap_uint<11> x=0;x<=w;++x) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
// Distinct addresses within this inner row loop; outer rows are not pipelined.
#pragma HLS DEPENDENCE variable=rows inter false
            ap_uint<2> old=0;
            if(y>0 && x<w) old=rows[x];
            ap_uint<1> a=(y>=2 && x<w)?old[1]:ap_uint<1>(0);
            ap_uint<1> b=(y>=1 && x<w)?old[0]:ap_uint<1>(0);
            ap_uint<1> c=(y<h && x<w)?in.read():ap_uint<1>(0);
            if(x<w) rows[x]=(ap_uint<2>(b)<<1)|ap_uint<2>(c);
            for(unsigned r=0;r<3;++r) {
#pragma HLS UNROLL
                win[r][0]=win[r][1];win[r][1]=win[r][2];
            }
            win[0][2]=a;win[1][2]=b;win[2][2]=c;
            if(y>=1 && x>=1) {
                ap_uint<1> p[8]={win[0][1],win[0][2],win[1][2],win[2][2],
                                win[2][1],win[2][0],win[1][0],win[0][0]};
#pragma HLS ARRAY_PARTITION variable=p complete
                ap_uint<4> neighbors=0, transitions=0;
                for(unsigned k=0;k<8;++k) {
#pragma HLS UNROLL
                    neighbors+=p[k];transitions+=(!p[k] && p[(k+1)%8]);
                }
                // Boolean realization of the same 256-entry neighborhood LUT.
                bool phase=(STAGE%2)==0 ? !(p[0]&&p[2]&&p[4]) && !(p[2]&&p[4]&&p[6])
                                           : !(p[0]&&p[2]&&p[6]) && !(p[0]&&p[4]&&p[6]);
                bool remove=win[1][1] && neighbors>=2 && neighbors<=6 && transitions==1 && phase;
                out.write(win[1][1] && !remove);
                any_removed=any_removed || remove;
            }
        }
    }
    changed=any_removed;
}
static void cascade(const ap_uint<64>* src,ap_uint<64>* dst,ap_uint<11> w,ap_uint<11> h,unsigned n,bool counts[LINEART_STAGES]) {
#pragma HLS DATAFLOW disable_start_propagation
#pragma HLS ARRAY_PARTITION variable=counts complete
    hls::stream<ap_uint<1>> s[LINEART_STAGES+1];
#pragma HLS STREAM variable=s depth=8
#pragma HLS ARRAY_PARTITION variable=s complete
    unpack(src,s[0],n);
    thin_stage<0>(s[0],s[1],w,h,counts[0]);
    thin_stage<1>(s[1],s[2],w,h,counts[1]);
    thin_stage<2>(s[2],s[3],w,h,counts[2]);
    thin_stage<3>(s[3],s[4],w,h,counts[3]);
    thin_stage<4>(s[4],s[5],w,h,counts[4]);
    thin_stage<5>(s[5],s[6],w,h,counts[5]);
    thin_stage<6>(s[6],s[7],w,h,counts[6]);
    thin_stage<7>(s[7],s[8],w,h,counts[7]);
#if LINEART_STAGES == 16
    thin_stage<8>(s[8],s[9],w,h,counts[8]);
    thin_stage<9>(s[9],s[10],w,h,counts[9]);
    thin_stage<10>(s[10],s[11],w,h,counts[10]);
    thin_stage<11>(s[11],s[12],w,h,counts[11]);
    thin_stage<12>(s[12],s[13],w,h,counts[12]);
    thin_stage<13>(s[13],s[14],w,h,counts[13]);
    thin_stage<14>(s[14],s[15],w,h,counts[14]);
    thin_stage<15>(s[15],s[16],w,h,counts[15]);
#endif
    pack(s[LINEART_STAGES],dst,n);
}
unsigned tcb_lineart_accel(const ap_uint<64>* src,ap_uint<64>* dst,unsigned width,unsigned height,
                          unsigned &deleted,unsigned &identity) {
#pragma HLS INTERFACE m_axi port=src offset=slave bundle=gmem depth=36864 max_read_burst_length=16 num_read_outstanding=2
#pragma HLS INTERFACE m_axi port=dst offset=slave bundle=gmem depth=36864 max_write_burst_length=16 num_write_outstanding=2
#pragma HLS INTERFACE s_axilite port=src bundle=control
#pragma HLS INTERFACE s_axilite port=dst bundle=control
#pragma HLS INTERFACE s_axilite port=width bundle=control
#pragma HLS INTERFACE s_axilite port=height bundle=control
#pragma HLS INTERFACE s_axilite port=deleted bundle=control
#pragma HLS INTERFACE s_axilite port=identity bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    identity=LINEART_ID;deleted=0;
    if(!width || !height || width>LINEART_MAX_DIM || height>LINEART_MAX_DIM)return 1;
    bool counts[LINEART_STAGES];
#pragma HLS ARRAY_PARTITION variable=counts complete
    ap_uint<22> n=ap_uint<11>(width)*ap_uint<11>(height);
#pragma HLS BIND_OP variable=n op=mul impl=fabric
    cascade(src,dst,ap_uint<11>(width),ap_uint<11>(height),n,counts);
    for(unsigned i=0;i<LINEART_STAGES;++i)deleted=deleted || counts[i];
    return 0;
}
