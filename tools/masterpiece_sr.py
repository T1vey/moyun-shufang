"""Super-resolve the masterpiece column strips (build machine only).

Most scans give a character only 85-190 px. Thresholding at that size leaves
stair-step edges that the traced centreline then follows. Each column strip
used by tools/build_masterpieces.py is upscaled x4 here (OpenCV dnn_superres:
EDSR / ESPCN / FSRCNN weights, or plain bicubic) and saved as a PNG; the build
then takes the ink edge from the upscaled strip. Needs opencv-contrib-python
(cv2.dnn_superres), which the board runtime does not use.

  python tools/masterpiece_sr.py --models DIR [--method espcn] [--only lanting]
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import masterpiece_crop as C

OUT = ROOT.parent / 'masterpieces_sr'
FACTOR = 4


def strip_path(work_id, part, method):
    return OUT / ('%s_%d_%s_x%d.png' % (work_id, part, method, FACTOR))


def upscale(rgb, method, models):
    if method == 'bicubic':
        return cv2.resize(rgb, None, fx=FACTOR, fy=FACTOR, interpolation=cv2.INTER_CUBIC)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(str(Path(models) / ('%s_x%d.pb' % (method.upper(), FACTOR))))
    sr.setModel(method, FACTOR)
    # EDSR is slow on a CPU for tall strips: upscale in overlapping tiles.
    tile, over, out = 256, 16, None
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    out = np.zeros((h * FACTOR, w * FACTOR, 3), np.uint8)
    for y in range(0, h, tile):
        y0, y1 = max(0, y - over), min(h, y + tile + over)
        up = sr.upsample(bgr[y0:y1])
        a = (y - y0) * FACTOR
        out[y * FACTOR:min(h, y + tile) * FACTOR] = up[a:a + (min(h, y + tile) - y) * FACTOR]
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def main():
    import build_masterpieces as B
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True)
    ap.add_argument('--method', default='espcn', choices=['bicubic', 'fsrcnn', 'espcn', 'edsr'])
    ap.add_argument('--only', action='append')
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for work in B.WORKS:
        if args.only and work['id'] not in args.only:
            continue
        for k, (image, box, *_rest) in enumerate(work['parts']):
            rgb = C.load(str(image or work['source']), box)
            up = upscale(rgb, args.method, args.models)
            cv2.imencode('.png', cv2.cvtColor(up, cv2.COLOR_RGB2BGR))[1].tofile(str(strip_path(work['id'], k, args.method)))
            print(work['id'], k, rgb.shape[:2], '->', up.shape[:2], flush=True)


if __name__ == '__main__':
    main()
