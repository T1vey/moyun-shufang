"""Memory layouts of tcb_brush_recog_0 (no hardware access here).

The camera is a USB/UVC device read by the PS; each 640x480 YUYV frame is copied to
DDR and the HLS core runs three modes on it:
  3 preprocess : YUYV -> ROI histogram/Otsu -> threshold -> 4 morphology stages -> binary
  1 rectify    : binary camera frame -> fixed-point homography -> square page + projections
  2 recognise  : per box crop, 64x64 normalisation, directional features, 3500-template
                 L1 top-5 and scoring statistics
Register offsets come from the generated driver header (tcb_brush_recog.registers.json).
"""
import numpy as np
from . import model as m

RECOG_ABI = 'tcb705-brushrecog-v1'
RECOG_IP = 'tcb_brush_recog_0'
RECOG_BASE = 0x40040000
RECOG_SIZE = 0x10000
RECOG_ID = 0x42524331
RECOG_TOP = 'tcb_brush_recog'

MODE_RECTIFY, MODE_RECOGNISE, MODE_PREPROCESS = 1, 2, 3
YUYV_WORDS = 76800
STATS_WORD = 4800
FRAME_WORDS = 4800
RECT_WPR = 5
PROJ_COL, PROJ_ROW = 1600, 1680
PARAM_BOXES, PARAM_EXPECT, PARAM_CAND = 2, 18, 34
PARAM_WORDS = PARAM_CAND + 4096 // 4
RESULT_WORDS = 128
MAX_TEMPLATES = 4096


def frame_u64(words_u32):
    return np.asarray(words_u32, dtype='<u4').view('<u8')


def rectify_params(hq, size):
    """hq: 9 fixed-point coefficients from model.homography_fixed."""
    p = np.zeros(PARAM_WORDS, dtype=np.uint64)
    p[0] = size
    for i, v in enumerate(hq):
        p[1 + i] = np.uint64(int(v) & 0xffffffffffffffff)
    return p


def preprocess_params(roi=(0, m.W - 1, 0, m.H - 1), otsu=True, manual=100, bias=0, ops=m.DEFAULT_OPS):
    p = np.zeros(PARAM_WORDS, dtype=np.uint64)
    opbits = sum((op & 3) << (2 * i) for i, op in enumerate(ops))
    p[0] = np.uint64(int(otsu) | (manual & 0xff) << 8 | (bias & 0xff) << 16 | opbits << 24)
    x0, x1, y0, y1 = roi
    p[1] = np.uint64(x0) | np.uint64(x1) << np.uint64(16) | np.uint64(y0) << np.uint64(32) | np.uint64(y1) << np.uint64(48)
    return p


def preprocess_stats_words(stats):
    otsu = stats['otsu']
    return np.array([(0 if otsu is None else otsu) | stats['threshold'] << 8 | (otsu is not None) << 16,
                     stats['hist_n'] | stats['hist_s'] << 32], dtype=np.uint64)


def parse_preprocess_stats(words):
    a, b = int(words[0]), int(words[1])
    return dict(otsu=a & 0xff if a >> 16 & 1 else None, threshold=a >> 8 & 0xff,
                hist_n=b & 0xffffffff, hist_s=b >> 32)


def recognise_params(size, boxes, n_tpl, expected=None, candidates=None):
    if not 1 <= size <= m.MAX_RECT or len(boxes) > m.MAX_BOXES:
        raise ValueError('invalid rectified size or box count')
    p = np.zeros(PARAM_WORDS, dtype=np.uint64)
    cand = list(candidates or [])
    p[0] = np.uint64(size) | (np.uint64(len(boxes)) << np.uint64(32))
    p[1] = np.uint64(n_tpl) | (np.uint64(len(cand)) << np.uint64(32))
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        p[PARAM_BOXES + i] = np.uint64(x0) | np.uint64(y0) << np.uint64(16) | np.uint64(x1) << np.uint64(32) | np.uint64(y1) << np.uint64(48)
        e = -1 if expected is None else expected[i]
        p[PARAM_EXPECT + i] = np.uint64(e & 0xffffffff)
    for i, c in enumerate(cand):
        p[PARAM_CAND + i // 4] |= np.uint64(c) << np.uint64(16 * (i % 4))
    return p


def pack_rect(rect):
    size = rect.shape[0]
    out = np.zeros((m.MAX_RECT, RECT_WPR), dtype=np.uint64)
    padded = np.zeros((size, RECT_WPR * 64), dtype=bool)
    padded[:, :rect.shape[1]] = rect
    out[:size] = np.packbits(padded, axis=1, bitorder='little').view('<u8')
    return out.reshape(-1)


def unpack_rect(words, size):
    w = np.asarray(words[:size * RECT_WPR], dtype='<u8').reshape(size, RECT_WPR)
    return np.unpackbits(w.view(np.uint8), axis=1, bitorder='little')[:, :size].astype(bool)


def pack_proj(col, row):
    out = np.zeros(160, dtype=np.uint64)
    c = np.zeros(m.MAX_RECT, dtype=np.uint16); c[:len(col)] = col
    r = np.zeros(m.MAX_RECT, dtype=np.uint16); r[:len(row)] = row
    out[:80] = c.view('<u8')
    out[80:] = r.view('<u8')
    return out


def unpack_proj(words, size):
    w = np.asarray(words, dtype='<u8')
    return (w[PROJ_COL:PROJ_COL + 80].view('<u2')[:size].astype(int),
            w[PROJ_ROW:PROJ_ROW + 80].view('<u2')[:size].astype(int))


def pack_templates(features, bitmaps):
    f = np.asarray(features, dtype=np.uint8)
    b = np.asarray(bitmaps, dtype=np.uint8)
    if f.ndim != 2 or f.shape[1] != m.FEATURES or b.shape != (len(f), 512):
        raise ValueError('template arrays have the wrong shape')
    return np.concatenate([f.reshape(-1), b.reshape(-1)]).view('<u8')


def result_words(r):
    """Model result -> the 128-word hardware record."""
    out = np.zeros(RESULT_WORDS, dtype=np.uint64)
    if r['empty']:
        x0, y0, x1, y1 = r['box']
        out[1] = np.uint64(x0) | np.uint64(y0) << np.uint64(16) | np.uint64(x1) << np.uint64(32) | np.uint64(y1) << np.uint64(48)
        return out
    U = np.uint64
    ow, oh = r['size']
    out[0] = U(1) | U(ow) << U(8) | U(oh) << U(16) | U(r['target']) << U(32)
    bx0, by0, bx1, by1 = r['bbox']
    out[1] = U(bx0) | U(by0) << U(16) | U(bx1) << U(32) | U(by1) << U(48)
    for i, (tid, d) in enumerate(r['top5']):
        out[2 + i] = U(tid) | U(d) << U(32)
    out[7] = U(r['n_w']) | U(r['n_t']) << U(16) | U(r['hit_w']) << U(32) | U(r['hit_t']) << U(48)
    out[8] = U(r['sx_w']) | U(r['sy_w']) << U(32)
    out[9] = U(r['sx_t']) | U(r['sy_t']) << U(32)
    out[10:18] = np.asarray(r['zone_ink'], dtype=np.uint8).view('<u8')
    out[18:26] = np.asarray(r['zone_contour'], dtype=np.uint8).view('<u8')
    out[26:58] = np.asarray(r['features'], dtype=np.uint8).view('<u8')
    out[58:122] = m.rows64(r['image'])
    return out


def parse_result(words):
    w = np.asarray(words, dtype='<u8')
    w0 = int(w[0])
    b = int(w[1])
    box = (b & 0xffff, b >> 16 & 0xffff, b >> 32 & 0xffff, b >> 48 & 0xffff)
    if not w0 & 1:
        return dict(empty=True, box=box)
    c, s1, s2 = int(w[7]), int(w[8]), int(w[9])
    img = np.unpackbits(w[58:122].view(np.uint8), bitorder='little').reshape(m.N, m.N).astype(bool)
    return dict(empty=False, bbox=box, size=(w0 >> 8 & 0xff, w0 >> 16 & 0xff), target=w0 >> 32 & 0xffff,
                top5=[(int(v) & 0xffff, int(v) >> 32) for v in w[2:7]],
                n_w=c & 0xffff, n_t=c >> 16 & 0xffff, hit_w=c >> 32 & 0xffff, hit_t=c >> 48 & 0xffff,
                sx_w=s1 & 0xffffffff, sy_w=s1 >> 32, sx_t=s2 & 0xffffffff, sy_t=s2 >> 32,
                zone_ink=w[10:18].view(np.uint8).copy(), zone_contour=w[18:26].view(np.uint8).copy(),
                features=w[26:58].view(np.uint8).copy(), image=img)
