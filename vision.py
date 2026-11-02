"""Shared image-to-centerline entry point for desktop and board applications."""
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = ROOT if (ROOT/'vendor'/'armvision').is_dir() else ROOT.parent


def vendor(name):
    spec = importlib.util.spec_from_file_location("armvision_" + name, VENDOR_ROOT / "vendor" / "armvision" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def convert(image_path, output, style="lineart", width_mm=20., height_mm=20., max_segments=4000, detail='fine',
            coordinate_system='full_canvas_xy_up', diagnostics=True, stroke_profile='faithful'):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    if style not in ("lineart", "photo"):
        raise ValueError("选择线稿或照片模式")
    if not all(math.isfinite(x) and 2 <= x <= 300 for x in (width_mm, height_mm)):
        raise ValueError("绘制尺寸范围为 2–300 mm")
    if type(max_segments) is not int or not 10 <= max_segments <= 12000:
        raise ValueError("线段预算范围为 10–12000")
    presets = {'fine':(1536, .45, 0, 0, 3), 'balanced':(1024, .8, 1, 2, 5), 'simple':(768, 1.2, 1, 3, 8)}
    if detail not in presets:
        raise ValueError('提取精度选择 fine/balanced/simple')
    resolution = presets[detail][0]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as im:
        if im.width * im.height > 16000000:
            raise ValueError("图片请压缩至 1600 万像素以内")
        rgba = ImageOps.exif_transpose(im).convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        rgb = white.convert("RGB")
        rgb.thumbnail((resolution, resolution))
        if diagnostics:
            rgb.save(output / "input.png")
    if style == "photo":
        processor = vendor("image_processor").ImageProcessor()
        bgr = np.array(rgb)[:, :, ::-1].copy()
        stages = processor.portrait_lineart(processor.grayscale(bgr), output_size=rgb.size)
        lineart = Image.fromarray(cv2.cvtColor(stages["13_lineart"], cv2.COLOR_BGR2GRAY))
    else:
        lineart = rgb.convert('L')
    if diagnostics:
        lineart.save(output / 'lineart.png')
    from stroke_paths import make_result
    gray = np.asarray(lineart)
    return make_result(gray,Path(image_path).read_bytes(),output,style,width_mm,height_mm,max_segments,detail,coordinate_system,
                       diagnostics=diagnostics, stroke_profile=stroke_profile)


def join_endpoints(paths, tolerance=1e-8):
    """Join touching open chains in the straightest direction; never bridge a gap."""
    paths = [[list(p) for p in chain] for chain in paths]
    # Endpoint index makes junction joining linear in image complexity.
    endpoints = {}
    def key(point):
        return tuple(round(v/tolerance) for v in point)
    for i, p in enumerate(paths):
        if math.dist(p[0], p[-1]) <= tolerance:
            continue
        for end in (0, -1):
            endpoints.setdefault(key(p[end]), []).append((i, end))
    remaining = set(range(len(paths))); result = []
    while remaining:
        seed = min(remaining); remaining.remove(seed); chain = paths[seed]
        for side in range(2):
            while math.dist(chain[0], chain[-1]) > tolerance:
                options = []
                dx, dy = chain[-1][0]-chain[-2][0], chain[-1][1]-chain[-2][1]
                for i, end in endpoints.get(key(chain[-1]), []):
                    if i not in remaining or math.dist(chain[-1], paths[i][end]) > tolerance:
                        continue
                    p = paths[i] if end == 0 else paths[i][::-1]
                    ex, ey = p[1][0]-p[0][0], p[1][1]-p[0][1]
                    score = (dx*ex+dy*ey)/max(math.hypot(dx,dy)*math.hypot(ex,ey), 1e-20)
                    options.append((score, i, end))
                if not options:
                    break
                _, i, end = max(options); remaining.remove(i)
                p = paths[i] if end == 0 else paths[i][::-1]
                chain.extend(p[1:])
            if side == 0:
                chain.reverse()
        result.append(chain)
    return result


def save_paths(result, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    width_mm, height_mm, ordered = result['width_mm'], result['height_mm'], result['paths']
    (output / "paths.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    polylines = "".join('<polyline fill="none" stroke="#226b54" stroke-width="0.12" points="%s"/>' %
                        " ".join("%.5f,%.5f" % (x, height_mm-y) for x, y in p) for p in ordered)
    (output / "paths.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 %.5f %.5f"><rect x="-1" y="-1" width="100%%" height="100%%" fill="white"/>%s</svg>' %
                                    (width_mm+2, height_mm+2, polylines), encoding="utf-8")


def preset(name, output, width_mm=20., height_mm=20.):
    if not all(math.isfinite(x) and 2 <= x <= 300 for x in (width_mm, height_mm)):
        raise ValueError('绘制尺寸范围为 2–300 mm')
    if name == 'line':
        paths = [[[0, height_mm/2], [width_mm, height_mm/2]]]
    elif name == 'circle':
        r = min(width_mm, height_mm)/2
        paths = [[[width_mm/2+r*math.cos(2*math.pi*i/120), height_mm/2+r*math.sin(2*math.pi*i/120)] for i in range(121)]]
        paths[0][-1] = paths[0][0][:]
    elif name == 'square':
        paths = [[[0,0],[width_mm,0],[width_mm,height_mm],[0,height_mm],[0,0]]]
    elif name == 'two-strokes':
        paths = [[[0,height_mm*.3],[width_mm,height_mm*.3]], [[0,height_mm*.7],[width_mm,height_mm*.7]]]
    else:
        raise ValueError('选择 line/circle/square/two-strokes')
    result = dict(units='mm', width_mm=width_mm, height_mm=height_mm, paths=paths, style='preset',
                  engine='geometric_preset', strokes=len(paths), segments=sum(len(p)-1 for p in paths))
    save_paths(result, output)
    return result
