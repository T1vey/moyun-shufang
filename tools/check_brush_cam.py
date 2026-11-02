"""Generate the brush_cam simulation frame and check the XSim dump against the model.

    python tools/check_brush_cam.py gen   <sim_dir>
    python tools/check_brush_cam.py check <sim_dir>
"""
import sys
from pathlib import Path
import numpy as np
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brush_vision import model as m   # noqa: E402

ROI = (40, 600, 40, 440)


def synthetic_frame(seed=20261024):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:m.H, 0:m.W]
    paper = 205 + 25 * (xx / m.W) - 15 * (yy / m.H)
    img = np.repeat(paper[..., None], 3, axis=2)
    img[:, :30] = 55                                    # dark table outside the ROI
    strokes = [((170, 150), (470, 140), 22), ((190, 250), (450, 255), 20), ((140, 360), (500, 350), 26),
               ((320, 120), (318, 370), 24), ((420, 280), (520, 400), 16)]
    for p0, p1, t in strokes:
        cv2.line(img, p0, p1, (25, 28, 30), t, cv2.LINE_AA)
    img += rng.normal(0, 4, img.shape)
    for _ in range(300):                                # ink specks and dry-brush holes
        y, x = rng.integers(40, 440), rng.integers(40, 600)
        img[y, x] = 30 if rng.random() < .5 else 240
    return np.clip(img, 0, 255).astype(np.uint8)


def gen(sim):
    img = synthetic_frame()
    pix = m.bgr_to_rgb565(img)
    (sim / 'frame.hex').write_text('\n'.join(f'{int(v):04x}' for v in pix.reshape(-1)) + '\n')
    np.save(sim / 'frame_rgb565.npy', pix)
    print('frame written', sim / 'frame.hex')


def check(sim):
    pix = np.load(sim / 'frame_rgb565.npy')
    gray = m.rgb565_to_gray(pix)
    regs, binw, prvw = {}, [], []
    for line in (sim / 'dump.txt').read_text().split('\n'):
        p = line.split()
        if not p:
            continue
        if 'x' in p[-1] or 'z' in p[-1]:
            raise SystemExit('X/Z in dump: ' + line)
        if p[0] == 'R':
            regs[int(p[1])] = int(p[2], 16)
        elif p[0] == 'B':
            binw.append(int(p[1], 16))
        elif p[0] == 'P':
            prvw.append(int(p[1], 16))
    hist, n, s = m.histogram(gray, ROI)
    want_otsu = m.otsu_threshold(hist, n, s)
    thr = regs[0x48]
    status = regs[0x40]
    print('status %08x frames %d thr %08x ink %d diff %d hist_n %d geom %08x misc %08x' % (
        status, regs[0x44], thr, regs[0x4c], regs[0x50], regs[0x54], regs[0x58], regs[0x5c]))
    errors = []
    if regs[0] != 0x42434d31:
        errors.append('ID')
    if (status & 0x3) != 0x3:
        errors.append('init/frozen status')
    if regs[0x54] != n:
        errors.append(f'hist N {regs[0x54]} != {n}')
    if thr & 0xff != want_otsu or not thr >> 16 & 1:
        errors.append(f'otsu {thr & 0xff} != model {want_otsu}')
    used = thr >> 8 & 0xff
    if used != want_otsu:
        errors.append(f'threshold in use {used} != {want_otsu}')
    if regs[0x58] & 0x3ff != 480 or regs[0x58] >> 16 & 0xfff != 1280:
        errors.append('frame geometry')
    want = m.frontend_binary(gray, used)
    got = m.unpack_frame(np.array(binw, dtype=np.uint32))
    bad = np.argwhere(got != want)
    if len(bad):
        errors.append(f'binary mismatches {len(bad)} first {bad[:5].tolist()}')
    if regs[0x4c] != int(want.sum()):
        errors.append(f'ink count {regs[0x4c]} != {int(want.sum())}')
    prv = m.unpack_preview(np.array(prvw, dtype=np.uint32))
    if not np.array_equal(prv, gray[::4, ::4]):
        errors.append(f'preview mismatches {int((prv != gray[::4, ::4]).sum())}')
    print('model otsu', want_otsu, 'ink pixels', int(want.sum()))
    if errors:
        raise SystemExit('FAIL: ' + '; '.join(errors))
    print('BRUSH_CAM_SIM_PASS')


if __name__ == '__main__':
    {'gen': gen, 'check': check}[sys.argv[1]](Path(sys.argv[2]))
