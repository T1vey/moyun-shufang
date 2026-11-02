"""Handwriting recognition service used by the backend (app.py /api/vision/*).

USB frame (ARM) -> PL mode 3 preprocess -> PL mode 1 rectify -> ARM cleanup, box split and
skeleton redraw -> PL mode 2 recognise once per calligraphy style (KaiTi, running, cursive,
clerical, Wei) -> ARM merge of the per-style top-5 -> PL scoring pass against the
standard glyph of the winning style -> ARM score.  Without the vision platform
the same chain runs on the bit-exact CPU model (slow; for PC demos).
"""
import base64
import json
import os
import threading
import time
from pathlib import Path
import numpy as np
from . import cloud_check, contract, model as m, prepare, scoring, segment, templates
from .camera import ImageCamera, UsbCamera

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'data/vision/templates_v3.bin'
STYLES_INDEX = ROOT / 'data/vision/styles.json'
CATEGORIES = ('楷书', '行书', '草书', '隶书', '魏碑')
COMMON300 = ROOT / 'data/calligraphy/常用300字.txt'
RECT = 320
# Closing only: an opening (erode first) wipes out 1-2 px pen strokes; specks are
# removed afterwards by prepare.clean on the rectified page.
MORPH_OPS = (m.OP_PASS, m.OP_PASS, m.OP_DILATE, m.OP_ERODE)
DEFAULT_CORNERS = [[120, 40], [520, 40], [520, 440], [120, 440]]
DEFAULT_SETTINGS = dict(otsu=True, manual=100, bias=0, morph=True, flatten=True, widthnorm=True, mode='single',
                        candidates='all', camera=0, categories=list(CATEGORIES), cloud=True, engine='template')
ENGINES = ('template', 'model')   # FPGA 模板匹配 / 本地模型 (手写识字 MobileNetV2, ARM CPU)


def _png(img, scale=1):
    import cv2
    a = np.asarray(img)
    if a.dtype == bool:
        a = np.where(a, 0, 255).astype(np.uint8)
    if scale != 1:
        a = cv2.resize(a, (a.shape[1] * scale, a.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
    ok, data = cv2.imencode('.png', a)
    return 'data:image/png;base64,' + base64.b64encode(data.tobytes()).decode()


def _jpeg(img, quality=70):
    import cv2
    ok, data = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return 'data:image/jpeg;base64,' + base64.b64encode(data.tobytes()).decode()


class VisionService:
    def __init__(self, data_dir, hardware=None, camera=None, template_path=TEMPLATES, styles_index=STYLES_INDEX):
        self.folder = Path(data_dir) / 'vision'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.meta, self.feats, self.bitmaps, self.blob = templates.load(template_path)
        self.chars = self.meta['characters']
        entries = [dict(style='kai_arphic', label='Arphic 楷体', category='楷书', file=None)]
        if styles_index is not None and Path(styles_index).is_file():
            entries = json.loads(Path(styles_index).read_text(encoding='utf-8'))['styles']
        self.styles = []
        for e in entries:
            path = Path(template_path) if e['file'] is None else Path(styles_index).parent / e['file']
            meta, feats, bitmaps, _ = templates.load(path)
            if meta['characters'] != self.chars:
                raise ValueError('style %s has a different character list' % e['style'])
            # Matching blob: features plus one blank bitmap (the scoring pass uses the real one).
            match = np.concatenate([feats.reshape(-1), np.zeros(512, np.uint8)]).view('<u8')
            self.styles.append(dict(e, meta=meta, feats=feats, bitmaps=bitmaps, match=match))
        self.index = {ch: i for i, ch in enumerate(self.chars)}
        self._hwr = None
        self.settings = dict(DEFAULT_SETTINGS)
        self.corners = [list(p) for p in DEFAULT_CORNERS]
        self._load_config()
        demo = os.environ.get('BRUSH_VISION_IMAGE')
        self.camera = camera or (ImageCamera(demo) if demo else UsbCamera(self.settings.get('camera', 0)))
        self._hardware = hardware
        self.hardware_error = None
        self.last = None

    # ---------------------------------------------------------------- config
    def _config_path(self):
        return self.folder / 'config.json'

    def _load_config(self):
        try:
            cfg = json.loads(self._config_path().read_text(encoding='utf-8'))
            self.settings.update({k: cfg['settings'][k] for k in DEFAULT_SETTINGS if k in cfg.get('settings', {})})
            if self._valid_corners(cfg.get('corners')):
                self.corners = cfg['corners']
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save_config(self):
        tmp = self._config_path().with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(settings=self.settings, corners=self.corners), ensure_ascii=False, indent=1),
                       encoding='utf-8')
        tmp.replace(self._config_path())

    @staticmethod
    def _valid_corners(pts):
        try:
            return (len(pts) == 4 and all(len(p) == 2 for p in pts)
                    and all(0 <= p[0] < m.W and 0 <= p[1] < m.H for p in pts))
        except TypeError:
            return False

    def hardware(self):
        if self._hardware is None:
            try:
                from .hardware import open_platform
                self._hardware = open_platform()
            except Exception as exc:
                from .hardware import SoftwareVision
                self.hardware_error = str(exc)
                self._hardware = SoftwareVision()
            blank = np.zeros((1, 512), np.uint8)
            for st in self.styles:
                self._hardware.load_templates(st['match'], len(self.chars), name=st['style'],
                                              feats=st['feats'], bitmaps=blank)
        return self._hardware

    def homography(self):
        import cv2
        src = np.float32([[0, 0], [RECT - 1, 0], [RECT - 1, RECT - 1], [0, RECT - 1]])
        return m.homography_fixed(cv2.getPerspectiveTransform(src, np.float32(self.corners)))

    def roi(self):
        pts = np.asarray(self.corners)
        return (int(max(0, pts[:, 0].min())), int(min(m.W - 1, pts[:, 0].max())),
                int(max(0, pts[:, 1].min())), int(min(m.H - 1, pts[:, 1].max())))

    # ---------------------------------------------------------------- API
    def status(self):
        hw = self._hardware
        return dict(backend=None if hw is None else hw.backend, hardware_error=self.hardware_error,
                    camera=self.camera.status(), settings=self.settings, corners=self.corners, rect_size=RECT,
                    templates=dict(count=len(self.chars), version=self.meta['schema'], sha256=self.meta['sha256'][:12],
                                   styles=[dict(style=st['style'], label=st['label'], category=st['category'])
                                           for st in self.styles]),
                    last=None if self.last is None else dict(time=self.last['time'], chars=[c.get('char') for c in self.last['chars']]))

    def preview(self):
        import cv2
        yuyv = self.camera.latest(max_age=1.5)
        gray = m.yuyv_gray(yuyv)
        small = cv2.resize(gray, (m.W // 2, m.H // 2), interpolation=cv2.INTER_AREA)
        return dict(image=_jpeg(small), width=m.W, height=m.H, corners=self.corners, camera=self.camera.status())

    def configure(self, data):
        with self.lock:
            s = dict(self.settings)
            for key in ('otsu', 'morph', 'flatten', 'widthnorm'):
                if key in data:
                    s[key] = bool(data[key])
            for key, lo, hi in (('manual', 0, 255), ('bias', -60, 60)):
                if key in data:
                    v = int(data[key])
                    if not lo <= v <= hi:
                        raise ValueError('%s 超出范围' % key)
                    s[key] = v
            if 'mode' in data:
                if data['mode'] not in ('single', 'auto'):
                    raise ValueError('mode 只能是 single/auto')
                s['mode'] = data['mode']
            if 'categories' in data:
                cats = [c for c in data['categories'] if c in CATEGORIES]
                if not cats:
                    raise ValueError('至少选择一种书体')
                s['categories'] = cats
            if 'engine' in data:
                if data['engine'] not in ENGINES:
                    raise ValueError('engine 只能是 template/model')
                s['engine'] = data['engine']
            if 'candidates' in data:
                if data['candidates'] not in ('all', 'common300', 'expected'):
                    raise ValueError('candidates 只能是 all/common300/expected')
                s['candidates'] = data['candidates']
            if 'corners' in data:
                if not self._valid_corners(data['corners']):
                    raise ValueError('标定点必须是 4 个画面内的点')
                self.corners = [[float(p[0]), float(p[1])] for p in data['corners']]
            self.settings = s
            self._save_config()
            return self.status()

    def _candidates(self, expected_text):
        mode = self.settings['candidates']
        if mode == 'common300':
            try:
                text = COMMON300.read_text(encoding='utf-8')
            except OSError:
                return None
            return sorted({self.index[ch] for ch in text if ch in self.index})
        if mode == 'expected' and expected_text:
            ids = sorted({self.index[ch] for ch in expected_text if ch in self.index})
            return ids or None
        return None

    def recognise(self, data=None):
        data = data or {}
        expected_text = str(data.get('expected', ''))[:16]
        with self.lock:
            hw = self.hardware()
            started = time.perf_counter()
            yuyv = self.camera.latest(max_age=1.0)
            t_capture = time.perf_counter() - started
            import cv2
            gray = m.yuyv_gray(yuyv)
            t0 = time.perf_counter()
            if self.settings['flatten']:
                flat = prepare.flatten(gray)
                yuyv = yuyv.copy()
                yuyv[0::2] = flat.reshape(-1)
            t_flat = time.perf_counter() - t0
            cv2.imwrite(str(self.folder / 'last_gray.png'), gray)
            if self.settings['flatten']:
                cv2.imwrite(str(self.folder / 'last_flat.png'), flat)
            ops = MORPH_OPS if self.settings['morph'] else (m.OP_PASS,) * 4
            binary, words, stats, t_pre = hw.preprocess(yuyv, self.roi(), self.settings['otsu'],
                                                       self.settings['manual'], self.settings['bias'], ops)
            rect, rect_words, col, row, t_rect = hw.rectify(words, self.homography(), RECT)
            t0 = time.perf_counter()
            rect = prepare.clean(rect)
            mode = data.get('mode', self.settings['mode'])
            boxes = [(0, 0, RECT, RECT)] if mode == 'single' else segment.boxes(rect, rect.sum(axis=1))
            if not boxes:
                boxes = [(0, 0, RECT, RECT)]
            # Each character: thin to a skeleton and redraw at a fixed width (same as the
            # templates), then lay out 4 per 320x320 page in 160x160 cells for the PL.
            cvs, glyphs = [], []
            for x0, y0, x1, y1 in boxes:
                region = rect[y0:y1, x0:x1]
                cvs.append(prepare.width_cv(region))
                glyphs.append(prepare.skeleton_glyph(region))
            cell = RECT // 2
            exp_chars = [ch for ch in expected_text if not ch.isspace()]
            expected = [self.index.get(exp_chars[i], -1) if i < len(exp_chars) else -1 for i in range(len(boxes))]
            candidates = self._candidates(expected_text)
            t_arm = t_flat + time.perf_counter() - t0
            active = [st for st in self.styles if st['category'] in self.settings['categories']] or self.styles
            results, t_rec, pages = [], 0.0, []
            for start in range(0, len(boxes), 4):
                page_rect = np.zeros((RECT, RECT), bool)
                cells = []
                for j, glyph in enumerate(glyphs[start:start + 4]):
                    cx, cy = (j % 2) * cell, (j // 2) * cell
                    if glyph is not None:
                        o = (cell - glyph.shape[0]) // 2
                        page_rect[cy + o:cy + o + glyph.shape[0], cx + o:cx + o + glyph.shape[1]] = glyph
                    cells.append((cx, cy, cx + cell, cy + cell))
                page_words = contract.pack_rect(page_rect)
                merged = [dict(cands=[], first=None) for _ in cells]
                for si, st in enumerate(active):
                    part, seconds = hw.recognise(page_words, RECT, cells, [0] * len(cells), candidates,
                                                 style=st['style'])
                    t_rec += seconds
                    for j, r in enumerate(part):
                        if merged[j]['first'] is None:
                            merged[j]['first'] = r
                        if not r['empty']:
                            merged[j]['cands'] += [(d, si, tid) for tid, d in r['top5'] if tid < len(self.chars)]
                for j, mg in enumerate(merged):
                    results.append(dict(mg, page=page_words, cell=cells[j]))
                pages.append(page_rect)
            t_pl = t_pre + t_rect + t_rec
            engine = self.settings.get('engine', 'template'); t_model = 0.0
            chars = []
            for i, (box, res) in enumerate(zip(boxes, results)):
                first = res['first']
                if first is None or first['empty'] or not res['cands']:
                    chars.append(dict(index=i, box=list(box), empty=True))
                    continue
                seen, top = set(), []
                for d, si, tid in sorted(res['cands']):
                    if tid not in seen:
                        seen.add(tid)
                        top.append((d, si, tid))
                    if len(top) == 5:
                        break
                q = first['features'].astype(np.int32)
                probs = {}
                if engine == 'model':
                    t0 = time.perf_counter()
                    ranked = self._model_top(rect, box, q, active, candidates)
                    t_model += time.perf_counter() - t0
                    if ranked:
                        top = [(d, si, cid) for d, si, cid, _ in ranked]
                        probs = {cid: p for _, _, cid, p in ranked}
                if expected[i] >= 0:     # score against the expected character, in its closest style
                    target = expected[i]
                    si = int(np.argmin([np.abs(st['feats'][target].astype(np.int32) - q).sum() for st in active]))
                else:
                    _, si, target = top[0]
                    record = dict(time=time.strftime('%Y-%m-%d %H:%M:%S'), index=i, local=self.chars[target],
                                  local_style=active[si]['label'], d1=int(top[0][0]),
                                  d2=int(top[1][0]) if len(top) > 1 else None, decided='model' if probs else 'local')
                    if probs:
                        record['p'] = probs[target]
                    elif self.settings.get('cloud', True) and self._uncertain(top, active) and cloud_check.available():
                        png = self._crop_png(rect, box)
                        t_cloud = time.perf_counter()
                        ans = cloud_check.ask(png) if png is not None else None
                        record.update(cloud_ms=round((time.perf_counter() - t_cloud) * 1000),
                                      cloud=ans and dict(char=ans['char'], style=ans['style'], confidence=ans['confidence']))
                        if ans and ans['char'] in self.index:
                            cid = self.index[ans['char']]
                            pool = [k for k, x in enumerate(active) if x['category'] == ans['style']] or range(len(active))
                            dist = {k: int(np.abs(active[k]['feats'][cid].astype(np.int32) - q).sum()) for k in pool}
                            si = min(dist, key=dist.get)
                            target = cid
                            top = [(dist[si], si, cid)] + [t for t in top if t[2] != cid][:4]
                            record['decided'] = 'cloud'
                    self._log_decision(record)
                st = active[si]
                score_blob = np.concatenate([st['feats'][target], st['bitmaps'][target]]).view('<u8')
                hw.load_templates(score_blob, 1, name='score', feats=st['feats'][target:target + 1],
                                  bitmaps=st['bitmaps'][target:target + 1])
                part, seconds = hw.recognise(res['page'], RECT, [res['cell']], [0], None, style='score')
                t_rec += seconds
                t_pl += seconds
                r = dict(part[0], target=target)
                s = scoring.score(r, st['feats'], st['bitmaps'], st['meta']['calibration'], None, width_cv=cvs[i])
                target_img = np.unpackbits(st['bitmaps'][target], bitorder='little').reshape(m.N, m.N).astype(bool)
                chars.append(dict(index=i, box=list(box), empty=False, char=self.chars[top[0][2]],
                                  style=active[top[0][1]]['label'], category=active[top[0][1]]['category'],
                                  score_style=st['label'],
                                  expected=exp_chars[i] if i < len(exp_chars) else None, target=self.chars[target],
                                  top5=[dict(char=self.chars[tid], distance=int(d), style=active[k]['label'],
                                             **({'p': probs[tid]} if tid in probs else {}))
                                        for d, k, tid in top], engine='model' if probs else 'template',
                                  image=_png(first['image'], 2), template=_png(target_img, 2), **s))
            page = cv2.cvtColor(np.where(rect, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            for c in chars:
                x0, y0, x1, y1 = c['box']
                cv2.rectangle(page, (x0, y0), (x1 - 1, y1 - 1), (60, 160, 60) if not c['empty'] else (180, 180, 180), 1)
            cam = cv2.resize(np.where(binary, 0, 255).astype(np.uint8), (m.W // 2, m.H // 2), interpolation=cv2.INTER_AREA)
            total = time.perf_counter() - started
            scored = [c['total'] for c in chars if not c['empty']]
            self.last = dict(time=time.strftime('%H:%M:%S'), backend=hw.backend, mode=mode, chars=chars, engine=engine,
                             average=round(sum(scored) / len(scored)) if scored else None,
                             threshold=stats['threshold'], otsu=stats['otsu'], page=_png(page), binary=_png(cam),
                             timing_ms=dict(capture=round(t_capture * 1000, 1), preprocess=round(t_pre * 1000, 2),
                                            rectify=round(t_rect * 1000, 2), recognise=round(t_rec * 1000, 2),
                                            pl_total=round(t_pl * 1000, 2), arm=round(t_arm * 1000, 1),
                                            model=round(t_model * 1000, 1),
                                            total=round(total * 1000, 1)), skeleton=_png(pages[0]))
            return self.last

    @staticmethod
    def _uncertain(top, active):
        """Low confidence: best distance far above the style's own spread, or no clear winner."""
        d1 = top[0][0]
        d2 = top[1][0] if len(top) > 1 else float('inf')
        limit = 1.15 * active[top[0][1]]['meta']['calibration'].get('d_own_p90', 1150)
        return d1 > limit or (d2 - d1) < 0.06 * d1

    def _model_top(self, rect, box, q, active, candidates):
        """本地模型 (2026-10-28): the 手写识字 MobileNetV2 names the character; the templates still
        choose its closest style and score it, as for a cloud answer. Returns up to five
        (distance, style index, template id, probability), only characters the templates have
        (and the 常用 300 / expected list when chosen); empty when none of the top 40 is there."""
        x0, y0, x1, y1 = box
        img = prepare.model_glyph(rect[y0:y1, x0:x1])
        if img is None:
            return []
        if self._hwr is None:
            from user_gui.hwr import Recognizer
            self._hwr = Recognizer()          # loaded on first use (about 0.4 s, 50 MB)
        allowed = set(candidates) if candidates else None
        out = []
        for c in self._hwr.recognize_image(img, k=40)['candidates']:
            cid = self.index.get(c['char'])
            if cid is None or (allowed is not None and cid not in allowed):
                continue
            dist = [int(np.abs(st['feats'][cid].astype(np.int32) - q).sum()) for st in active]
            si = int(np.argmin(dist))
            out.append((dist[si], si, cid, c['p']))
            if len(out) == 5:
                break
        return out

    @staticmethod
    def _crop_png(rect, box):
        import cv2
        x0, y0, x1, y1 = box
        region = rect[y0:y1, x0:x1]
        bb = m.tight_bbox(region, (0, 0, region.shape[1], region.shape[0]))
        if bb is None:
            return None
        bx0, by0, bx1, by1 = bb
        img = np.where(region[by0:by1, bx0:bx1], 0, 255).astype(np.uint8)
        img = cv2.copyMakeBorder(img, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        k = 256 / max(img.shape)
        img = cv2.resize(img, (max(1, int(img.shape[1] * k)), max(1, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA)
        return cv2.imencode('.png', img)[1].tobytes()

    def _log_decision(self, record):
        try:
            with open(self.folder / 'decisions.jsonl', 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def last_result(self):
        return self.last or {}
