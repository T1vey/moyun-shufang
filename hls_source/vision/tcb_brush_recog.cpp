#include "tcb_brush_recog.h"

// Area-lean implementation: everything except the 8-lane template matcher is a
// bit-serial loop over pixels, because the platform has ~14k LUTs to spare and
// milliseconds of latency budget.  Results are bit-exact with brush_vision/model.py.

// One on-chip bit buffer: the camera frame in mode 1, the rectified page in mode 2.
static ap_uint<64> buf[BR_FRAME_WORDS];

static ap_uint<32> udiv32(ap_uint<32> a, ap_uint<32> b) {
#pragma HLS INLINE off
    ap_uint<32> q = 0;
    ap_uint<33> r = 0;
    for (int i = 31; i >= 0; --i) {
        r = (r << 1) | a[i];
        if (r >= b) { r -= b; q[i] = 1; }
    }
    return q;
}

static ap_uint<9> isqrt17(ap_uint<17> v) {
#pragma HLS INLINE off
    ap_uint<18> num = v, res = 0, bit = ap_uint<18>(1) << 16;
    for (int i = 0; i < 9; ++i) {
        if (num >= res + bit) { num -= res + bit; res = (res >> 1) + bit; }
        else res >>= 1;
        bit >>= 2;
    }
    return res;
}

static ap_uint<1> rect_bit(unsigned x, unsigned y) { return buf[y * BR_RECT_WPR + (x >> 6)][x & 63]; }

// ------------------------------------------------------------------ mode 1
// Fixed-point homography (model.homography_fixed, H_FRAC=24): X/Y/Z start each row
// at h1*v+h2 etc. and step by h0/h3/h6; x = (2X+Z) div (2Z) by a 10-step long
// division, valid iff 0 <= 2X+Z < 2Z*640 (likewise y with 480).
static int rectify(const ap_uint<64>* params, const ap_uint<64>* src, ap_uint<64>* dst) {
    unsigned size = params[0].range(31, 0);
    if (size == 0 || size > BR_MAX_RECT) return 1;
    ap_int<50> h[9];
    for (int i = 0; i < 9; ++i) h[i] = ap_int<64>(params[1 + i]);
LOAD:
    for (int i = 0; i < BR_FRAME_WORDS; ++i) {
#pragma HLS PIPELINE II=1
        buf[i] = src[i];
    }
    ap_uint<16> colp[BR_MAX_RECT], rowp[BR_MAX_RECT];
CLR:
    for (int i = 0; i < BR_MAX_RECT; ++i) {
#pragma HLS PIPELINE II=1
        colp[i] = 0;
        rowp[i] = 0;
    }
ROWS:
    for (unsigned v = 0; v < size; ++v) {
        ap_int<50> X = h[1] * ap_int<12>(v) + h[2];
        ap_int<50> Y = h[4] * ap_int<12>(v) + h[5];
        ap_int<50> Z = h[7] * ap_int<12>(v) + h[8];
        ap_uint<64> row = 0;
        ap_uint<16> rowsum = 0;
    COLS:
        for (unsigned u = 0; u < size; ++u) {
            ap_uint<1> bit = 0;
            if (Z > 0) {
                ap_int<52> nx = ap_int<52>(X) * 2 + Z, ny = ap_int<52>(Y) * 2 + Z;
                ap_int<64> d = ap_int<64>(Z) * 2;
                if (nx >= 0 && ny >= 0 && ap_int<64>(nx) < d * BR_W && ap_int<64>(ny) < d * BR_H) {
                    ap_uint<64> rx = nx, ry = ny, dk = ap_uint<64>(d) << 9;
                    ap_uint<10> qx = 0, qy = 0;
                DIV:
                    for (int k = 9; k >= 0; --k) {
                        if (rx >= dk) { rx -= dk; qx[k] = 1; }
                        if (ry >= dk) { ry -= dk; qy[k] = 1; }
                        dk >>= 1;
                    }
                    ap_uint<19> idx = qy * BR_W + qx;
                    bit = buf[idx >> 6][idx & 63];
                }
            }
            row = (row >> 1) | (ap_uint<64>(bit) << 63);
            colp[u] += bit;
            rowsum += bit;
            if ((u & 63) == 63 || u == size - 1) {
                dst[v * BR_RECT_WPR + (u >> 6)] = row >> (63 - (u & 63));
                row = 0;
            }
            X += h[0];
            Y += h[3];
            Z += h[6];
        }
        for (unsigned k = (size + 63) >> 6; k < BR_RECT_WPR; ++k) dst[v * BR_RECT_WPR + k] = 0;
        rowp[v] = rowsum;
    }
    unsigned base = 0;
PROJ:
    for (unsigned w = 0; w < BR_MAX_RECT / 2; ++w) {
#pragma HLS PIPELINE II=1
        ap_uint<64> pw = 0;
        for (int j = 0; j < 4; ++j) {
            ap_uint<16> v = w < BR_MAX_RECT / 4 ? colp[base + j] : rowp[base + j];
            pw.range(16 * j + 15, 16 * j) = (base + j < size) ? v : ap_uint<16>(0);
        }
        dst[BR_PROJ_COL + w] = pw;
        base = (base == BR_MAX_RECT - 4) ? 0 : base + 4;
    }
    return 0;
}

// ------------------------------------------------------------------ mode 2
static void recognise_box(unsigned size, ap_uint<64> boxw, int expected, unsigned n_tpl, unsigned n_cand,
                          const ap_uint<16> cand[BR_MAX_TEMPLATES], const ap_uint<64>* tpl, ap_uint<64>* out) {
#pragma HLS INLINE off
    unsigned x0 = boxw.range(15, 0), y0 = boxw.range(31, 16), x1 = boxw.range(47, 32), y1 = boxw.range(63, 48);
    if (x1 > size) x1 = size;
    if (y1 > size) y1 = size;
    // ---- tight bounding box
    unsigned bx0 = size, by0 = size, bx1 = 0, by1 = 0;
    bool any = false;
    if (x0 < x1 && y0 < y1) {
        unsigned x = x0, y = y0;
    BBOX:
        for (unsigned it = 0; it < (x1 - x0) * (y1 - y0); ++it) {
#pragma HLS PIPELINE II=1
            if (rect_bit(x, y)) {
                any = true;
                if (x < bx0) bx0 = x;
                if (x + 1 > bx1) bx1 = x + 1;
                if (y < by0) by0 = y;
                by1 = y + 1;
            }
            if (x == x1 - 1) { x = x0; ++y; } else ++x;
        }
    }
    if (!any) {
    EMPTY:
        for (int i = 0; i < BR_RESULT_WORDS; ++i) {
#pragma HLS PIPELINE II=1
            out[i] = i == 1 ? boxw : ap_uint<64>(0);
        }
        return;
    }
    // ---- aspect-preserving normalisation into 64x64
    unsigned w = bx1 - bx0, hgt = by1 - by0, s = w > hgt ? w : hgt;
    ap_uint<32> k = udiv32(ap_uint<32>(BR_BOX) << 16, s);
    unsigned ow = (unsigned)((ap_uint<48>(w) * k) >> 16), oh = (unsigned)((ap_uint<48>(hgt) * k) >> 16);
    if (ow == 0) ow = 1;
    if (oh == 0) oh = 1;
    unsigned ox = (BR_N - ow) >> 1, oy = (BR_N - oh) >> 1;
    ap_uint<64> img[BR_N];
    ap_uint<8> cnt[BR_N * BR_N];
    bool down = s >= BR_BOX;
    ap_uint<32> inv = down ? ap_uint<32>(0) : udiv32(ap_uint<32>(s) << 16, BR_BOX);
CNT_CLR:
    for (int i = 0; i < BR_N * BR_N; ++i) {
#pragma HLS PIPELINE II=1
        cnt[i] = 0;
    }
    if (down) {
        unsigned x = bx0, y = by0;
    CNT_ACC:
        for (unsigned it = 0; it < w * hgt; ++it) {
#pragma HLS PIPELINE II=3
            if (rect_bit(x, y)) {
                unsigned i = (unsigned)((ap_uint<48>(x - bx0) * k) >> 16) + ox;
                unsigned j = (unsigned)((ap_uint<48>(y - by0) * k) >> 16) + oy;
                cnt[j * BR_N + i] = cnt[j * BR_N + i] + 1;
            }
            if (x == bx1 - 1) { x = bx0; ++y; } else ++x;
        }
    }
    ap_uint<32> need = s * s;
    ap_uint<64> row = 0;
IMG:
    for (int p = 0; p < BR_N * BR_N; ++p) {
#pragma HLS PIPELINE II=1
        unsigned i = p & 63, j = p >> 6;
        ap_uint<1> bit = 0;
        if (down) bit = (ap_uint<32>(cnt[p]) * (4 * BR_BOX * BR_BOX) >= need) ? 1 : 0;
        else if (i >= ox && i < ox + ow && j >= oy && j < oy + oh) {
            unsigned sx = bx0 + (unsigned)((ap_uint<48>(i - ox) * inv) >> 16);
            unsigned sy = by0 + (unsigned)((ap_uint<48>(j - oy) * inv) >> 16);
            bit = rect_bit(sx, sy);
        }
        row = (row >> 1) | (ap_uint<64>(bit) << 63);
        if (i == 63) img[j] = row;
    }
    // ---- directional element features
    ap_uint<64> c[BR_N];
CONTOUR:
    for (int y = 0; y < BR_N; ++y) {
        ap_uint<64> up = y > 0 ? img[y - 1] : ap_uint<64>(0);
        ap_uint<64> dn = y < BR_N - 1 ? img[y + 1] : ap_uint<64>(0);
        ap_uint<64> b = img[y];
        c[y] = b & ~(b & up & dn & ap_uint<64>(b << 1) & ap_uint<64>(b >> 1));
    }
    ap_uint<7> raw[4 * 64], zink[64], zcon[64];
ZONES:
    for (int z = 0; z < 64; ++z) {
        unsigned zy = z >> 3, zx = z & 7;
        ap_uint<7> a0 = 0, a1 = 0, a2 = 0, a3 = 0, ai = 0, ac = 0;
        for (int py = 0; py < 8; ++py) {
            int y = zy * 8 + py;
            ap_uint<64> cu = y > 0 ? c[y - 1] : ap_uint<64>(0);
            ap_uint<64> cc = c[y];
            ap_uint<64> cd = y < BR_N - 1 ? c[y + 1] : ap_uint<64>(0);
            ap_uint<64> bb = img[y];
        ZPIX:
            for (int px = 0; px < 8; ++px) {
#pragma HLS PIPELINE II=1
                int x = zx * 8 + px;
                ap_uint<1> l = x > 0 ? cc[x - 1] : ap_uint<1>(0), r = x < 63 ? cc[x + 1] : ap_uint<1>(0);
                ap_uint<1> ul = (x > 0) ? cu[x - 1] : ap_uint<1>(0), ur = (x < 63) ? cu[x + 1] : ap_uint<1>(0);
                ap_uint<1> dl = (x > 0) ? cd[x - 1] : ap_uint<1>(0), dr = (x < 63) ? cd[x + 1] : ap_uint<1>(0);
                ap_uint<1> me = cc[x];
                a0 += me & (l | r);
                a1 += me & (cu[x] | cd[x]);
                a2 += me & (ur | dl);
                a3 += me & (ul | dr);
                ai += bb[x];
                ac += me;
            }
        }
        raw[z] = a0; raw[64 + z] = a1; raw[128 + z] = a2; raw[192 + z] = a3;
        zink[z] = ai; zcon[z] = ac;
    }
    ap_uint<9> f[BR_FEATURES];
    ap_uint<17> total = 0;
BLUR:
    for (int idx = 0; idx < BR_FEATURES; ++idx) {
        int d = idx >> 6, zy = (idx >> 3) & 7, zx = idx & 7;
        ap_uint<11> g = 0;
    TAPS:
        for (int t = 0; t < 9; ++t) {
#pragma HLS PIPELINE II=1
            int dy = t / 3 - 1, dx = t % 3 - 1, yy = zy + dy, xx = zx + dx;
            if (yy >= 0 && yy < BR_ZONES && xx >= 0 && xx < BR_ZONES) {
                ap_uint<11> v = raw[d * 64 + yy * 8 + xx];
                g += v << ((dy == 0) + (dx == 0));
            }
        }
        ap_uint<9> v = isqrt17(ap_uint<17>(g) << 6);
        if (v > 255) v = 255;
        f[idx] = v;
        total += v;
    }
    ap_uint<32> recip = total == 0 ? ap_uint<32>(0) : udiv32(ap_uint<32>(BR_FEATURE_SUM) << 16, total);
    ap_uint<64> q[BR_FEAT_WORDS];
    ap_uint<64> qw = 0;
QUANT:
    for (int i = 0; i < BR_FEATURES; ++i) {
#pragma HLS PIPELINE II=1
        ap_uint<48> t = (ap_uint<48>(f[i]) * recip) >> 16;
        ap_uint<8> b = t > 255 ? ap_uint<8>(255) : ap_uint<8>(t);
        qw = (qw >> 8) | (ap_uint<64>(b) << 56);
        if ((i & 7) == 7) q[i >> 3] = qw;
    }
    // ---- template matching (8 lanes, L1, top 5; ties keep the earlier template)
    ap_uint<16> top_id[5];
    ap_uint<32> top_d[5];
#pragma HLS ARRAY_PARTITION variable=top_id complete
#pragma HLS ARRAY_PARTITION variable=top_d complete
    for (int i = 0; i < 5; ++i) { top_id[i] = 0; top_d[i] = 0xffffffffu; }
    unsigned n = n_cand ? n_cand : n_tpl;
    ap_uint<32> acc = 0;
    ap_uint<16> cur = 0;
    unsigned t = 0, wi = 0;
MATCH:
    for (unsigned it = 0; it < n * BR_FEAT_WORDS; ++it) {
#pragma HLS PIPELINE II=1
        if (wi == 0) { cur = n_cand ? cand[t] : ap_uint<16>(t); acc = 0; }
        ap_uint<64> a = (cur < n_tpl) ? tpl[ap_uint<32>(cur) * BR_FEAT_WORDS + wi] : ap_uint<64>(0);
        ap_uint<64> b = q[wi];
        ap_uint<11> sum = 0;
        for (int j = 0; j < 8; ++j) {
#pragma HLS UNROLL
            ap_uint<8> x = a.range(8 * j + 7, 8 * j), y = b.range(8 * j + 7, 8 * j);
            sum += (x > y) ? ap_uint<8>(x - y) : ap_uint<8>(y - x);
        }
        ap_uint<32> d = acc + sum;
        acc = d;
        if (wi == BR_FEAT_WORDS - 1) {
            if (cur < n_tpl) {
                for (int kk = 4; kk >= 0; --kk) {
#pragma HLS UNROLL
                    bool below = d < top_d[kk];
                    bool above = (kk == 0) || d >= top_d[kk - 1];
                    if (below && above) { top_d[kk] = d; top_id[kk] = cur; }
                    else if (kk > 0 && d < top_d[kk - 1]) { top_d[kk] = top_d[kk - 1]; top_id[kk] = top_id[kk - 1]; }
                }
            }
            wi = 0; ++t;
        } else ++wi;
    }
    // ---- score statistics against the target template image
    unsigned target = (expected >= 0 && (unsigned)expected < n_tpl) ? (unsigned)expected : (unsigned)top_id[0];
    ap_uint<64> t_img[BR_N], hb[BR_N], ht[BR_N];
    ap_uint<32> tbase = ap_uint<32>(n_tpl) * BR_FEAT_WORDS + ap_uint<32>(target) * BR_IMG_WORDS;
TLOAD:
    for (int y = 0; y < BR_N; ++y) {
#pragma HLS PIPELINE II=1
        ap_uint<64> tr = tpl[tbase + y];
        ap_uint<64> br = img[y];
        t_img[y] = tr;
        hb[y] = ap_uint<64>(br >> 2) | ap_uint<64>(br >> 1) | br | ap_uint<64>(br << 1) | ap_uint<64>(br << 2);
        ht[y] = ap_uint<64>(tr >> 2) | ap_uint<64>(tr >> 1) | tr | ap_uint<64>(tr << 1) | ap_uint<64>(tr << 2);
    }
    ap_uint<13> n_w = 0, n_t = 0, hit_w = 0, hit_t = 0;
    ap_uint<32> sx_w = 0, sy_w = 0, sx_t = 0, sy_t = 0;
STATS:
    for (int y = 0; y < BR_N; ++y) {
        ap_uint<64> db = 0, dt = 0;
        for (int d = -2; d <= 2; ++d) {
            int yy = y + d;
            if (yy >= 0 && yy < BR_N) { db |= hb[yy]; dt |= ht[yy]; }
        }
        ap_uint<64> br = img[y], tr = t_img[y];
    SPIX:
        for (int x = 0; x < BR_N; ++x) {
#pragma HLS PIPELINE II=1
            if (br[x]) { ++n_w; sx_w += x; sy_w += y; if (dt[x]) ++hit_w; }
            if (tr[x]) { ++n_t; sx_t += x; sy_t += y; if (db[x]) ++hit_t; }
        }
    }
    // ---- result record
    out[0] = ap_uint<64>(1) | (ap_uint<64>(ow) << 8) | (ap_uint<64>(oh) << 16) | (ap_uint<64>(target) << 32);
    out[1] = ap_uint<64>(bx0) | (ap_uint<64>(by0) << 16) | (ap_uint<64>(bx1) << 32) | (ap_uint<64>(by1) << 48);
    for (int i = 0; i < 5; ++i) out[2 + i] = ap_uint<64>(top_id[i]) | (ap_uint<64>(top_d[i]) << 32);
    out[7] = ap_uint<64>(n_w) | (ap_uint<64>(n_t) << 16) | (ap_uint<64>(hit_w) << 32) | (ap_uint<64>(hit_t) << 48);
    out[8] = ap_uint<64>(sx_w) | (ap_uint<64>(sy_w) << 32);
    out[9] = ap_uint<64>(sx_t) | (ap_uint<64>(sy_t) << 32);
    ap_uint<64> zi = 0, zc = 0;
ZOUT:
    for (int z = 0; z < 64; ++z) {
#pragma HLS PIPELINE II=1
        zi = (zi >> 8) | (ap_uint<64>(zink[z]) << 56);
        zc = (zc >> 8) | (ap_uint<64>(zcon[z]) << 56);
        if ((z & 7) == 7) { out[10 + (z >> 3)] = zi; out[18 + (z >> 3)] = zc; }
    }
FOUT:
    for (int i = 0; i < BR_FEAT_WORDS; ++i) {
#pragma HLS PIPELINE II=1
        out[26 + i] = q[i];
    }
IOUT:
    for (int i = 0; i < BR_N; ++i) {
#pragma HLS PIPELINE II=1
        out[58 + i] = img[i];
    }
    for (int i = 122; i < BR_RESULT_WORDS; ++i) out[i] = 0;
}

static int recognise(const ap_uint<64>* params, const ap_uint<64>* src, ap_uint<64>* dst, const ap_uint<64>* tpl) {
    ap_uint<64> p0 = params[0], p1 = params[1];
    unsigned size = p0.range(31, 0), n_boxes = p0.range(63, 32);
    unsigned n_tpl = p1.range(31, 0), n_cand = p1.range(63, 32);
    if (size == 0 || size > BR_MAX_RECT || n_boxes > BR_MAX_BOXES || n_tpl == 0 ||
        n_tpl > BR_MAX_TEMPLATES || n_cand > BR_MAX_TEMPLATES) return 1;
    static ap_uint<16> cand[BR_MAX_TEMPLATES];
CAND:
    for (unsigned i = 0; i < n_cand; ++i) {
#pragma HLS PIPELINE II=1
        cand[i] = params[BR_PARAM_CAND + (i >> 2)].range(16 * (i & 3) + 15, 16 * (i & 3));
    }
LOAD:
    for (unsigned i = 0; i < size * BR_RECT_WPR; ++i) {
#pragma HLS PIPELINE II=1
        buf[i] = src[i];
    }
BOXES:
    for (unsigned b = 0; b < n_boxes; ++b) {
        int expected = (int)(unsigned)params[BR_PARAM_EXPECT + b].range(31, 0);
        recognise_box(size, params[BR_PARAM_BOXES + b], expected, n_tpl, n_cand, cand, tpl,
                      dst + b * BR_RESULT_WORDS);
    }
    return 0;
}

// ------------------------------------------------------------------ mode 3
static ap_uint<62> udiv62(ap_uint<62> a, ap_uint<30> b) {
#pragma HLS INLINE off
    ap_uint<62> q = 0;
    ap_uint<31> r = 0;
    for (int i = 61; i >= 0; --i) {
        ap_uint<31> n = (r << 1) | a[i];
        if (n >= b) { r = n - b; q[i] = 1; } else r = n;
    }
    return q;
}

static void morph_stage(ap_uint<2> op) {
#pragma HLS INLINE off
    if (op != 1 && op != 2) return;
    bool erode = op == 1;
    ap_uint<64> hp[10], hc[10], hn[10];
    for (int w = 0; w < 10; ++w) { hp[w] = 0; hc[w] = 0; }
    for (int y = -1; y < BR_H; ++y) {
        // hn = horizontal 3-tap of input row y+1 (zero outside the frame)
        ap_uint<64> prev = 0, cur = (y + 1 < BR_H) ? buf[(y + 1) * 10] : ap_uint<64>(0);
    HROW:
        for (int w = 0; w < 10; ++w) {
#pragma HLS PIPELINE II=1
            ap_uint<64> next = (y + 1 < BR_H && w < 9) ? buf[(y + 1) * 10 + w + 1] : ap_uint<64>(0);
            ap_uint<64> l = (cur << 1) | (prev >> 63), r = (cur >> 1) | (next << 63);
            hn[w] = erode ? ap_uint<64>(cur & l & r) : ap_uint<64>(cur | l | r);
            prev = cur; cur = next;
        }
        if (y >= 0) {
        VROW:
            for (int w = 0; w < 10; ++w) {
#pragma HLS PIPELINE II=1
                buf[y * 10 + w] = erode ? ap_uint<64>(hp[w] & hc[w] & hn[w]) : ap_uint<64>(hp[w] | hc[w] | hn[w]);
            }
        }
    SHIFT:
        for (int w = 0; w < 10; ++w) {
#pragma HLS PIPELINE II=1
            hp[w] = hc[w]; hc[w] = hn[w];
        }
    }
}

static int preprocess(const ap_uint<64>* params, const ap_uint<64>* src, ap_uint<64>* dst) {
    ap_uint<64> p0 = params[0], p1 = params[1];
    bool otsu_en = p0[0];
    ap_uint<8> manual = p0.range(15, 8), ops = p0.range(31, 24);
    ap_int<8> bias = p0.range(23, 16);
    unsigned rx0 = p1.range(15, 0), rx1 = p1.range(31, 16), ry0 = p1.range(47, 32), ry1 = p1.range(63, 48);
    ap_uint<15> hist[256];
HCLR:
    for (int i = 0; i < 256; ++i) {
#pragma HLS PIPELINE II=1
        hist[i] = 0;
    }
    ap_uint<15> n = 0;
    ap_uint<23> s = 0;
HIST:
    for (int r = 0; r < BR_H / 4; ++r) {
        for (int w = 0; w < BR_W / 4; ++w) {
#pragma HLS PIPELINE II=3
            unsigned x = 4 * w, y = 4 * r;
            ap_uint<8> g = src[y * (BR_W / 4) + w].range(7, 0);
            if (x >= rx0 && x <= rx1 && y >= ry0 && y <= ry1) {
                hist[g] = hist[g] + 1;
                ++n;
                s += g;
            }
        }
    }
    ap_uint<15> n0 = 0;
    ap_uint<23> s0 = 0;
    ap_uint<62> best = 0;
    int first = -1, last = -1;
    bool on = false;
OTSU:
    for (int t = 0; t < 256; ++t) {
        ap_uint<15> h = hist[t];
        n0 += h;
        s0 += ap_uint<23>(t) * h;
        ap_uint<15> n1 = n - n0;
        if (n0 == 0 || n1 == 0) { on = false; continue; }
        ap_uint<38> a = ap_uint<38>(s) * n0, b = ap_uint<38>(n) * s0;
        ap_uint<31> d = (a > b ? ap_uint<38>(a - b) : ap_uint<38>(b - a)) >> 7;
        ap_uint<62> q = udiv62(ap_uint<62>(d) * d, ap_uint<30>(n0) * n1);
        if (q > best) { best = q; first = t; last = t; on = true; }
        else if (q == best && on) last = t;
        else on = false;
    }
    ap_uint<8> otsu = first < 0 ? 0 : (first + last) >> 1;
    ap_uint<8> thr = manual;
    if (otsu_en && first >= 0) {
        int t = (int)otsu + (int)bias;
        thr = t < 0 ? 0 : (t > 255 ? 255 : t);
    }
    ap_uint<64> acc = 0;
BIN:
    for (int i = 0; i < BR_YUYV_WORDS; ++i) {
#pragma HLS PIPELINE II=1
        ap_uint<64> v = src[i];
        ap_uint<4> nib;
        for (int j = 0; j < 4; ++j) nib[j] = ap_uint<8>(v.range(16 * j + 7, 16 * j)) < thr;
        acc = (acc >> 4) | (ap_uint<64>(nib) << 60);
        if ((i & 15) == 15) buf[i >> 4] = acc;
    }
    for (int k = 0; k < 4; ++k) morph_stage(ops.range(2 * k + 1, 2 * k));
OUT:
    for (int i = 0; i < BR_FRAME_WORDS; ++i) {
#pragma HLS PIPELINE II=1
        int y = i / 10, w = i % 10;
        ap_uint<64> v = buf[i];
        if (y < 4 || y >= BR_H - 4) v = 0;
        if (w == 0) v &= ~ap_uint<64>(0xF);
        if (w == 9) v &= ~(ap_uint<64>(0xF) << 60);
        dst[i] = v;
    }
    dst[BR_STATS_WORD] = ap_uint<64>(otsu) | (ap_uint<64>(thr) << 8) | (ap_uint<64>(first >= 0) << 16);
    dst[BR_STATS_WORD + 1] = ap_uint<64>(n) | (ap_uint<64>(s) << 32);
    return 0;
}

int tcb_brush_recog(unsigned mode, const ap_uint<64>* params, const ap_uint<64>* src,
                    ap_uint<64>* dst, const ap_uint<64>* tpl, unsigned& identity) {
#pragma HLS INTERFACE m_axi port=params offset=slave bundle=gmem depth=1058 max_read_burst_length=16 max_write_burst_length=16 num_read_outstanding=2 num_write_outstanding=2
#pragma HLS INTERFACE m_axi port=src offset=slave bundle=gmem depth=76800
#pragma HLS INTERFACE m_axi port=dst offset=slave bundle=gmem depth=4802
#pragma HLS INTERFACE m_axi port=tpl offset=slave bundle=gmem depth=9600
#pragma HLS INTERFACE s_axilite port=mode
#pragma HLS INTERFACE s_axilite port=params
#pragma HLS INTERFACE s_axilite port=src
#pragma HLS INTERFACE s_axilite port=dst
#pragma HLS INTERFACE s_axilite port=tpl
#pragma HLS INTERFACE s_axilite port=identity
#pragma HLS INTERFACE s_axilite port=return
    identity = BR_IDENTITY;
    if (mode == BR_MODE_RECTIFY) return rectify(params, src, dst);
    if (mode == BR_MODE_RECOGNISE) return recognise(params, src, dst, tpl);
    if (mode == BR_MODE_PREPROCESS) return preprocess(params, src, dst);
    return mode == 0 ? 0 : 1;
}
