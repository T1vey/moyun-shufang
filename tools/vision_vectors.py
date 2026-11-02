"""HLS test vectors for tcb_brush_recog (csim/cosim), computed with brush_vision.model.

Blocks: [u32 count][u64 words...]; order: rect params, frame, expected rect+proj,
recognise params A, templates, expected A, recognise params B, expected B, meta.
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import cv2
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from brush_vision import contract as c, model as m   # noqa: E402
from tools.check_brush_cam import synthetic_frame       # noqa: E402


def page_frame():
    gray = m.rgb565_to_gray(m.bgr_to_rgb565(synthetic_frame()))
    binary = m.frontend_binary(gray, 109)
    # Second and third "characters" so segmentation and the small-box path are used.
    extra = np.zeros_like(binary)
    cv2.circle(extra.view(np.uint8), (560, 120), 18, 1, 6)
    cv2.line(extra.view(np.uint8), (540, 300), (590, 330), 1, 7)
    return binary | extra


def homography(size):
    src = np.float32([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]])
    dst = np.float32([[60, 50], [600, 70], [620, 450], [40, 430]])
    return cv2.getPerspectiveTransform(src, dst).astype(np.float32)


def put(blocks, words):
    blocks.append(np.asarray(words, dtype=np.uint64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('output', type=Path)
    ap.add_argument('--size', type=int, default=320)
    ap.add_argument('--cosim', action='store_true', help='smaller rectified page for RTL co-simulation')
    a = ap.parse_args()
    size = 96 if a.cosim else a.size
    rng = np.random.default_rng(1024)
    frame = page_frame()
    hm = m.homography_fixed(homography(size))
    rect = m.rectify(frame, hm, size)
    col, row = m.projections(rect)
    blocks = []
    put(blocks, c.rectify_params(hm, size))
    put(blocks, c.frame_u64(m.pack_frame(frame)))
    exp1 = np.zeros(2048, dtype=np.uint64)
    exp1[:m.MAX_RECT * c.RECT_WPR] = c.pack_rect(rect)
    exp1[c.PROJ_COL:c.PROJ_COL + 160] = c.pack_proj(col, row)
    put(blocks, exp1)

    s = size / 320
    boxes = [(int(0 * s), int(0 * s), int(250 * s), int(320 * s)),     # main strokes
             (int(250 * s), int(0 * s), int(320 * s), int(160 * s)),   # circle
             (int(250 * s), int(160 * s), int(320 * s), int(320 * s)), # short line
             (int(300 * s), int(300 * s), int(310 * s), int(310 * s))] # probably empty
    n_tpl = 100
    feats = rng.integers(0, 60, (n_tpl, m.FEATURES)).astype(np.uint8)
    bitmaps = rng.integers(0, 256, (n_tpl, 512)).astype(np.uint8)
    # Plant near-copies so the top-5 ordering and ties are meaningful.
    for i, b in enumerate(boxes[:3]):
        bb = m.tight_bbox(rect, b)
        if bb is None:
            continue
        img, _ = m.normalize64(rect, bb)
        q, _, _ = m.def_features(img)
        feats[10 + i] = q
        feats[40 + i] = np.clip(q.astype(int) + 1, 0, 255)
        feats[41 + i] = feats[40 + i]                       # exact tie: 40+i must win over 41+i
        bitmaps[10 + i] = np.packbits(img.reshape(-1), bitorder='little')
    tpl = c.pack_templates(feats, bitmaps)
    expected_a = [-1, 7, -1, -1]
    put(blocks, c.recognise_params(size, boxes, n_tpl, expected_a))
    tpl_padded = np.zeros(9600, dtype=np.uint64)
    tpl_padded[:len(tpl)] = tpl
    put(blocks, tpl_padded)
    res_a = [m.recognise_box(rect, size, b, feats, bitmaps, e) for b, e in zip(boxes, expected_a)]
    put(blocks, np.concatenate([c.result_words(r) for r in res_a]))
    cand = [99, 41, 12, 40, 3, 500, 11]
    put(blocks, c.recognise_params(size, boxes[:3], n_tpl, None, cand))
    res_b = [m.recognise_box(rect, size, b, feats, bitmaps, -1, cand) for b in boxes[:3]]
    put(blocks, np.concatenate([c.result_words(r) for r in res_b]))
    # Mode 3: YUYV -> binary frame; chroma bytes are random and must be ignored.
    gray = m.rgb565_to_gray(m.bgr_to_rgb565(synthetic_frame()))
    yuyv = m.gray_to_yuyv(gray)
    yuyv[1::2] = rng.integers(0, 256, yuyv.size // 2).astype(np.uint8)
    roi = (40, 600, 40, 440)
    binary, stats = m.preprocess(gray, roi, otsu=True, manual=90, bias=-6)
    put(blocks, c.preprocess_params(roi, otsu=True, manual=90, bias=-6))
    put(blocks, yuyv.view('<u8'))
    exp3 = np.zeros(4802, dtype=np.uint64)
    exp3[:4800] = c.frame_u64(m.pack_frame(binary))
    exp3[4800:] = c.preprocess_stats_words(stats)
    put(blocks, exp3)
    with a.output.open('wb') as f:
        for b in blocks:
            f.write(np.uint32(len(b)).tobytes())
            f.write(b.astype('<u8').tobytes())
    meta = dict(preprocess=stats, size=size, boxes=boxes, rect_ink=int(rect.sum()),
                top5_a=[r.get('top5') for r in res_a], top5_b=[r.get('top5') for r in res_b])
    a.output.with_suffix('.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


if __name__ == '__main__':
    main()
