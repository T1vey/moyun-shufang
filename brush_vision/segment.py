"""Split the rectified page into character boxes from the PL projections."""
import numpy as np


def runs(profile, threshold, min_gap, min_len):
    """Index ranges where profile > threshold, merging gaps shorter than min_gap."""
    on = np.asarray(profile) > threshold
    spans, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            spans.append([start, i]); start = None
    if start is not None:
        spans.append([start, len(on)])
    merged = []
    for s in spans:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [tuple(s) for s in merged if s[1] - s[0] >= min_len]


def boxes(rect, row_proj, max_boxes=16, min_ink=40):
    """Reading order: rows top to bottom, characters left to right."""
    size = rect.shape[0]
    gap, pad = max(4, size // 24), 2
    out = []
    for y0, y1 in runs(row_proj, 0, gap, 6):
        cols = rect[y0:y1].sum(axis=0)
        for x0, x1 in runs(cols, 0, gap, 4):
            if rect[y0:y1, x0:x1].sum() < min_ink:
                continue
            out.append((max(0, x0 - pad), max(0, y0 - pad), min(size, x1 + pad), min(size, y1 + pad)))
    return out[:max_boxes]
