#include "tcb_brush_recog.h"
#include <cstdint>
#include <cstdio>
#include <vector>

typedef std::vector<ap_uint<64> > words;

static words block(FILE* f, size_t pad) {
    uint32_t n = 0;
    if (fread(&n, 4, 1, f) != 1) { printf("vector file truncated\n"); return words(); }
    std::vector<uint64_t> raw(n);
    if (n && fread(raw.data(), 8, n, f) != n) { printf("vector block truncated\n"); return words(); }
    words out(n > pad ? n : pad, 0);
    for (uint32_t i = 0; i < n; ++i) out[i] = raw[i];
    return out;
}

static int compare(const char* name, const words& got, const words& want, unsigned lo, unsigned hi) {
    int bad = 0;
    for (unsigned i = lo; i < hi; ++i)
        if (got[i] != want[i]) {
            if (bad < 8) printf("%s word %u got %016llx want %016llx\n", name, i,
                                (unsigned long long)got[i], (unsigned long long)want[i]);
            ++bad;
        }
    printf("%s: %d mismatches over %u words\n", name, bad, hi - lo);
    return bad;
}

int main() {
    FILE* f = fopen("vision_vectors.bin", "rb");
    if (!f) { printf("missing vision_vectors.bin\n"); return 1; }
    words p1 = block(f, BR_PARAM_WORDS), frame = block(f, BR_FRAME_WORDS), e1 = block(f, 2048);
    words p2 = block(f, BR_PARAM_WORDS), tpl = block(f, 9600), e2 = block(f, 2048);
    words p3 = block(f, BR_PARAM_WORDS), e3 = block(f, 2048);
    words p4 = block(f, BR_PARAM_WORDS), yuyv = block(f, BR_YUYV_WORDS), e4 = block(f, 4802);
    fclose(f);
    unsigned size = p1[0].range(31, 0), id = 0;
    int fail = 0;
    words rect(BR_FRAME_WORDS, 0), out(4802, 0);
    int rc = tcb_brush_recog(BR_MODE_RECTIFY, p1.data(), frame.data(), rect.data(), tpl.data(), id);
    if (rc != 0 || id != BR_IDENTITY) { printf("rectify rc=%d id=%08x\n", rc, id); ++fail; }
    fail += compare("rect", rect, e1, 0, size * BR_RECT_WPR) != 0;
    fail += compare("proj", rect, e1, BR_PROJ_COL, BR_PROJ_COL + 160) != 0;
    unsigned nb = p2[0].range(63, 32);
    rc = tcb_brush_recog(BR_MODE_RECOGNISE, p2.data(), rect.data(), out.data(), tpl.data(), id);
    if (rc != 0) { printf("recognise A rc=%d\n", rc); ++fail; }
    fail += compare("recognise A", out, e2, 0, nb * BR_RESULT_WORDS) != 0;
    nb = p3[0].range(63, 32);
    for (auto& w : out) w = 0;
    rc = tcb_brush_recog(BR_MODE_RECOGNISE, p3.data(), rect.data(), out.data(), tpl.data(), id);
    if (rc != 0) { printf("recognise B rc=%d\n", rc); ++fail; }
    fail += compare("recognise B (candidates)", out, e3, 0, nb * BR_RESULT_WORDS) != 0;
    words bin(4802, 0);
    rc = tcb_brush_recog(BR_MODE_PREPROCESS, p4.data(), yuyv.data(), bin.data(), tpl.data(), id);
    if (rc != 0) { printf("preprocess rc=%d\n", rc); ++fail; }
    fail += compare("preprocess", bin, e4, 0, 4802) != 0;
    if (tcb_brush_recog(0, p1.data(), frame.data(), out.data(), tpl.data(), id) != 0) ++fail;
    if (tcb_brush_recog(9, p1.data(), frame.data(), out.data(), tpl.data(), id) != 1) ++fail;
    words badp = p2;
    badp[0] = ap_uint<64>(400) | (ap_uint<64>(1) << 32);
    if (tcb_brush_recog(BR_MODE_RECOGNISE, badp.data(), rect.data(), out.data(), tpl.data(), id) != 1) ++fail;
    printf(fail ? "TB_FAIL %d\n" : "TB_PASS\n", fail);
    return fail ? 1 : 0;
}
