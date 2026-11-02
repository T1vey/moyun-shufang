"""Place one expressive module in the same character square as the finger input."""
import numpy as np
from calligraphy.presets import STROKES, VERSION, modules, number, profile
from calligraphy.curves import sample
from .recognizer import points

def task(module, raw, size_mm, config):
    if module not in STROKES:raise ValueError('未知基本笔画')
    size = number(size_mm, 40, 100, '整字大小')
    a = points(raw);lo, hi = a.min(axis=0), a.max(axis=0)
    W,H = float(config['paper']['width_mm']),float(config['paper']['height_mm'])
    if size+4 > min(W,H):raise ValueError('字号超出标定纸面，四周需至少留 2 mm')
    p = profile(config);source = np.asarray(modules(module)[0], dtype=float)
    low, high = source[:,:2].min(axis=0),source[:,:2].max(axis=0)
    span = high-low;desired = (hi-lo)*size
    dominant = int(np.argmax(span));scale = max(desired.max(), size*.035)/span.max()
    scales = np.full(2, scale)
    # Keep the authored entry/finish of a straight horizontal/vertical. A zero
    # finger bbox height must never flatten its nib choreography to a line.
    for axis in (0,1):
        if span[axis] > span.max()*.15 and desired[axis] > .001:
            scales[axis] = desired[axis]/span[axis]
    if max(desired) < size*.018:scales[:] = size*.045/span.max()
    dense = np.asarray(sample(source.tolist(),float(max(scales))), dtype=float)
    center = (lo+hi)*size/2
    xy = (dense[:,:2]-(low+high)/2)*scales+center
    # A small entry flourish may exceed the raw bbox, but never the character cell.
    if np.any(xy < -.001) or np.any(xy > size+.001):
        raise ValueError('笔锋轨迹超出字框，请离边缘稍远处落笔')
    xy += [(W-size)/2,(H-size)/2]
    meta=dict(schema='brush-handwriting-v1',module=module,version=VERSION,brush=p,
              size_mm=size,raw_points=a.tolist(),depth_mm=[(dense[:,2]*p['max_press_mm']).tolist()],
              feed_ratio=[dense[:,3].tolist()])
    return dict(units='mm',width_mm=W,height_mm=H,coordinate_system='full_canvas_xy_down',
                paths=[np.round(xy,6).tolist()],calligraphy=meta)
