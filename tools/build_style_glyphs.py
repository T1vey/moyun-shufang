"""Build an extra-style brush library (行书/草书/隶书/篆书) from a calligraphy font.

Geometry is the font's own centreline: the glyph is rendered, thinned and turned
into a cleaned stroke graph, so every path lies inside the font's ink. Stroke
order comes from the existing 楷书 library: its Make Me a Hanzi medians are
non-rigidly registered onto the skeleton and each skeleton piece is ordered by
the 楷书 stroke and arc position it lies along. Cursive styles keep the brush
down wherever the font itself joins one stroke to the next (连笔). Pressure
follows the local half-width of the font stroke.

Run from the repository root (build machine only; needs Pillow, fontTools,
OpenCV). No SDK, network or robot operations.

  python tools/build_style_glyphs.py --style li --font C:/Windows/Fonts/SIMLI.TTF
"""
import argparse
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import sqlite3
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

R = 256                                   # raster pixels per 50-unit cell
UNIT = 50.0 / R
STYLES = {
    'xing': dict(label='行书', cursive=True, method='trace'),
    'cao': dict(label='草书', cursive=True, method='trace'),
    'li': dict(label='隶书', cursive=False, method='trace'),
    'zhuan': dict(label='篆书', cursive=False, method='trace'),
}
N8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32)


# ---------------------------------------------------------------- raster

def render(font, ch):
    """Glyph in an R x R cell, centred, shrunk only if the ink would leave the cell."""
    from PIL import Image, ImageDraw
    im = Image.new('L', (R * 2, R * 2), 0)
    ImageDraw.Draw(im).text((R // 2, R // 2 + R * 900 // 1024), ch, font=font, fill=255, anchor='ls')
    a = np.array(im) > 127
    ys, xs = np.nonzero(a)
    if not len(ys):
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    k = min(1.0, 0.94 * R / max(x1 - x0, y1 - y0))
    M = np.float32([[k, 0, R / 2 - k * (x0 + x1) / 2], [0, k, R / 2 - k * (y0 + y1) / 2]])
    return cv2.warpAffine(a.astype(np.uint8) * 255, M, (R, R), flags=cv2.INTER_AREA) > 127


def length(p):
    return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0


def resample(poly, step):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(poly, axis=0).T))]
    n = max(2, int(d[-1] / step) + 1)
    t = np.linspace(0, d[-1], n)
    return np.c_[np.interp(t, d, poly[:, 0]), np.interp(t, d, poly[:, 1])]


# ---------------------------------------------------------------- skeleton graph

def raw_graph(skel):
    nb = cv2.filter2D(skel.astype(np.uint8), cv2.CV_8U, KERNEL, borderType=cv2.BORDER_CONSTANT) * skel
    junction = skel & (nb >= 3)
    nj, jlab = cv2.connectedComponents(junction.astype(np.uint8), connectivity=8)
    nodes = {i: np.argwhere(jlab == i)[:, ::-1].mean(0) for i in range(1, nj)}
    n, lab = cv2.connectedComponents((skel & ~junction).astype(np.uint8), connectivity=8)
    edges, nid = [], nj

    def touching(p):
        found = []
        for dx, dy in N8:
            x, y = p[0] + dx, p[1] + dy
            if 0 <= x < R and 0 <= y < R and jlab[y, x] > 0:
                found.append(int(jlab[y, x]))
        return found

    for k in range(1, n):
        pix = set(map(tuple, np.argwhere(lab == k)[:, ::-1]))
        def nbrs(p):
            return [(p[0] + dx, p[1] + dy) for dx, dy in N8 if (p[0] + dx, p[1] + dy) in pix]
        ends = [p for p in pix if len(nbrs(p)) <= 1]
        start = min(ends) if ends else min(pix)
        order, seen = [start], {start}
        while True:
            nx = [q for q in nbrs(order[-1]) if q not in seen]
            if not nx:
                break
            nx.sort(key=lambda q: abs(q[0] - order[-1][0]) + abs(q[1] - order[-1][1]))
            order.append(nx[0]); seen.add(nx[0])
        pts = [np.array(p, float) for p in order]
        if not ends:                                       # isolated closed loop
            nodes[nid] = pts[0]
            edges.append([nid, nid, np.array(pts + [pts[0]])]); nid += 1
            continue
        ta, tb = touching(order[0]), touching(order[-1])
        a = ta[0] if ta else 0
        b = ([j for j in tb if j != a] or tb or [0])[0] if len(order) == 1 else (tb[0] if tb else 0)
        if not a:
            a = nid; nodes[nid] = pts[0]; nid += 1
        else:
            pts.insert(0, nodes[a])
        if not b:
            b = nid; nodes[nid] = pts[-1]; nid += 1
        else:
            pts.append(nodes[b])
        edges.append([a, b, np.array(pts)])
    return nodes, edges


def degree(edges):
    d = {}
    for a, b, _ in edges:
        d[a] = d.get(a, 0) + 1; d[b] = d.get(b, 0) + 1
    return d


def clean(nodes, edges, dt, spur=2.0, bridge=0.9):
    """Remove thinning spurs, contract tiny junction bridges, merge degree-2 nodes."""
    def width(p):
        x, y = int(np.clip(round(p[0]), 0, R - 1)), int(np.clip(round(p[1]), 0, R - 1))
        return max(float(dt[y, x]), 1.0)
    changed = True
    while changed:
        changed = False
        d = degree(edges)
        for e in sorted(edges, key=lambda e: length(e[2])):
            a, b, p = e
            if a == b:
                continue
            leaf = a if d[a] == 1 and d[b] >= 3 else b if d[b] == 1 and d[a] >= 3 else None
            if leaf is None:
                continue
            # A thinning spur barely protrudes past the outline of the stroke it hangs from;
            # a real short stroke (dot, hook) does.
            hub = width(nodes[b if leaf == a else a])
            protrusion = length(p) + width(nodes[leaf]) - hub
            if protrusion < max(3.0, spur * 0.3 * hub):
                edges.remove(e); changed = True; break
        if changed:
            continue
        for e in edges:
            a, b, p = e
            if a != b and d[a] >= 3 and d[b] >= 3 and length(p) < bridge * min(width(nodes[a]), width(nodes[b])):
                edges.remove(e)
                m = (nodes[a] + nodes[b]) / 2; nodes[a] = m
                for f in edges:
                    if f[0] == b: f[0] = a
                    if f[1] == b: f[1] = a
                    if f[0] == a: f[2] = np.vstack([m, f[2][1:]])
                    if f[1] == a: f[2] = np.vstack([f[2][:-1], m])
                changed = True; break
        if changed:
            continue
        for node, k in d.items():
            if k != 2:
                continue
            inc = [e for e in edges if e[0] == node or e[1] == node]
            if len(inc) != 2:
                continue
            e1, e2 = inc
            p1 = e1[2] if e1[1] == node else e1[2][::-1]
            u = e1[0] if e1[1] == node else e1[1]
            p2 = e2[2] if e2[0] == node else e2[2][::-1]
            v = e2[1] if e2[0] == node else e2[0]
            edges.remove(e1); edges.remove(e2)
            edges.append([u, v, np.vstack([p1, p2[1:]])])
            changed = True; break
    return [e for e in edges if length(e[2]) >= 2]


# ---------------------------------------------------------------- stroke order

def nearest_map(mask):
    _, lab = cv2.distanceTransformWithLabels((~mask).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    zy, zx = np.nonzero(mask)
    lut = np.zeros((lab.max() + 1, 2), np.float32)
    lut[lab[zy, zx]] = np.c_[zx, zy]
    return lut[lab]


SIGMAS = (40, 30, 22, 16, 12, 12)   # stiff enough that single strokes keep their places
BACK = 0.5


def register(strokes, skel, sigmas=None):
    """Smoothed symmetric ICP: 楷书 medians move onto the target skeleton, structure kept."""
    pts = [resample(s, 2.0) for s in strokes]
    idx = np.cumsum([0] + [len(p) for p in pts])
    A = np.vstack(pts)
    sy, sx = np.nonzero(skel)
    S = np.c_[sx, sy].astype(float)
    a0, a1, s0, s1 = A.min(0), A.max(0), S.min(0), S.max(0)
    A = (A - (a0 + a1) / 2) * np.clip((s1 - s0) / np.maximum(a1 - a0, 8), 0.6, 1.6) + (s0 + s1) / 2
    near = nearest_map(skel)
    for sigma in sigmas or SIGMAS:
        P = np.clip(np.round(A).astype(int), 0, R - 1)
        fwd = near[P[:, 1], P[:, 0]] - A
        j = ((S[:, None, :] - A[None, :, :]) ** 2).sum(-1).argmin(1)
        back = np.zeros_like(A); cnt = np.zeros(len(A))
        np.add.at(back, j, S - A[j]); np.add.at(cnt, j, 1)
        disp = fwd + np.where(cnt[:, None] > 0, back / np.maximum(cnt, 1)[:, None], 0) * BACK
        w = np.exp(-((A[:, None, :] - A[None, :, :]) ** 2).sum(-1) / (2 * sigma ** 2))
        A = A + 0.7 * (w @ disp) / w.sum(1)[:, None]
    return [A[idx[i]:idx[i + 1]] for i in range(len(pts))]


def split_label(edges, warped, min_run=8):
    """Split skeleton edges where the nearest registered stroke changes; keep arc position."""
    dense = [resample(w, 1.0) for w in warped]
    out = []
    for _, _, P in edges:
        D = np.stack([np.hypot(P[:, None, 0] - d[None, :, 0], P[:, None, 1] - d[None, :, 1]).min(1) for d in dense])
        lab = D.argmin(0)
        cum = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
        sm = np.array([np.bincount(lab[np.abs(cum - c) <= min_run / 2], minlength=len(dense)).argmax() for c in cum])
        cuts = [0] + [i for i in range(1, len(P)) if sm[i] != sm[i - 1]] + [len(P)]
        runs = [[sm[a], a, b] for a, b in zip(cuts, cuts[1:])]
        merged = True
        while merged and len(runs) > 1:
            merged = False
            for k, (s, a, b) in enumerate(runs):
                if cum[b - 1] - cum[a] < min_run:
                    j = k - 1 if k > 0 else k + 1
                    runs[j][1] = min(runs[j][1], a); runs[j][2] = max(runs[j][2], b)
                    del runs[k]; merged = True; break
        for s, a, b in runs:
            pts = P if len(runs) == 1 else P[max(a - 1, 0):b + (1 if b < len(P) else 0)]
            d = dense[s]
            j = np.hypot(pts[:, None, 0] - d[None, :, 0], pts[:, None, 1] - d[None, :, 1]).argmin(1)
            t0, t1 = j[0] / max(len(d) - 1, 1), j[-1] / max(len(d) - 1, 1)
            if t1 < t0:
                pts, t0, t1 = pts[::-1], t1, t0
            out.append(dict(pts=pts, stroke=int(s), t0=t0, t1=t1))
    return out


def assemble(pieces, cursive, gap=3.0):
    """Order pieces by (楷书 stroke, arc position), keeping the brush down where possible.

    After each piece the next one is, if any, an unused piece touching the pen of
    the same stroke (any style), of the next stroke (cursive styles) or a tiny
    junction fragment; otherwise the brush lifts and the earliest unused piece starts.
    """
    todo = sorted(pieces, key=lambda e: (e['stroke'], (e['t0'] + e['t1']) / 2))
    paths, cur, cur_stroke = [], None, None
    while todo:
        pick = None
        if cur is not None:
            for k, e in enumerate(todo):
                if e['stroke'] > cur_stroke + (1 if cursive else 0) and length(e['pts']) >= 6:
                    continue
                d0, d1 = np.hypot(*(e['pts'][0] - cur[-1])), np.hypot(*(e['pts'][-1] - cur[-1]))
                if min(d0, d1) < gap:
                    pick = (k, e['pts'] if d0 <= d1 else e['pts'][::-1])
                    break
        if pick is None:
            if cur is not None:
                paths.append(cur)
            e = todo.pop(0)
            cur, cur_stroke = e['pts'].copy(), e['stroke']
            continue
        k, pts = pick
        cur_stroke = max(cur_stroke, todo.pop(k)['stroke'])
        cur = np.vstack([cur, pts[1:]])
    if cur is not None:
        paths.append(cur)
    return paths


def _end_dir(p, at_start, reach=6.0):
    """Unit direction leaving the node into the edge, measured over ~reach px."""
    q = p if at_start else p[::-1]
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    k = min(int(np.searchsorted(d, reach)), len(q) - 1)
    v = q[k] - q[0]
    n = np.hypot(*v)
    return v / n if n > 1e-9 else v


def natural_strokes(edges, max_turn_deg=45.0):
    """Join skeleton edges through junctions by good continuation into whole strokes.

    At every junction the incident edge ends are paired greedily by how straight
    the continuation is (a 横 crossing a 竖 becomes two whole strokes, never four
    pieces); ends that find no partner within max_turn_deg terminate there.
    """
    ends = {}
    for i, (a, b, p) in enumerate(edges):
        ends.setdefault(a, []).append((i, 0)); ends.setdefault(b, []).append((i, 1))
    partner = {}
    for node, inc in ends.items():
        if len(inc) < 2:
            continue
        cands = []
        for x in range(len(inc)):
            for y in range(x + 1, len(inc)):
                (i, ei), (j, ej) = inc[x], inc[y]
                if i == j:
                    continue
                di, dj = _end_dir(edges[i][2], ei == 0), _end_dir(edges[j][2], ej == 0)
                dev = math.degrees(math.acos(float(np.clip(-np.dot(di, dj), -1, 1))))
                cands.append((dev, inc[x], inc[y]))
        for dev, u, v in sorted(cands):
            if dev <= max_turn_deg and u not in partner and v not in partner:
                partner[u] = v; partner[v] = u
    used, chains = set(), []
    def walk(i, enter):
        pts = []
        while i not in used:
            used.add(i)
            p = edges[i][2] if enter == 0 else edges[i][2][::-1]
            pts.append(p if not pts else p[1:])
            nxt = partner.get((i, 1 - enter))
            if nxt is None:
                break
            i, enter = nxt
        return np.vstack(pts)
    starts = [(i, e) for i in range(len(edges)) for e in (0, 1) if (i, e) not in partner]
    for i, e in starts:
        if i not in used:
            chains.append(walk(i, e))
    for i in range(len(edges)):                      # closed loops without a free end
        if i not in used:
            chains.append(walk(i, 0))
    return chains


def label_strokes(chains, warped, corner_deg=45.0, min_run=8):
    """Split a chain only where it turns sharply AND passes to another standard stroke
    (the corner of 口); smooth cursive joins and crossings stay whole. Each piece is
    labelled with its standard stroke and oriented in that stroke's direction."""
    dense = [resample(w, 1.0) for w in warped]
    pieces = []
    for C in chains:
        P = resample(C, 1.0) if length(C) >= 2 else C
        if len(P) < 2:
            continue
        D = np.stack([np.hypot(P[:, None, 0] - d[None, :, 0], P[:, None, 1] - d[None, :, 1]).min(1) for d in dense])
        lab = D.argmin(0)
        n = len(P)
        sm = np.array([np.bincount(lab[max(0, i - min_run // 2):i + min_run // 2 + 1], minlength=len(dense)).argmax()
                       for i in range(n)])
        turn = np.zeros(n)
        for i in range(5, n - 5):
            a, b = P[i] - P[i - 5], P[i + 5] - P[i]
            na, nb = np.hypot(*a), np.hypot(*b)
            if na > 1e-6 and nb > 1e-6:
                turn[i] = math.degrees(math.acos(float(np.clip(np.dot(a, b) / (na * nb), -1, 1))))
        cuts = [0]
        for i in range(1, n):
            if sm[i] != sm[i - 1]:
                lo, hi = max(0, i - 5), min(n, i + 6)
                k = lo + int(turn[lo:hi].argmax())
                if turn[k] >= corner_deg and k - cuts[-1] >= min_run and n - k >= min_run:
                    cuts.append(k)
        cuts.append(n)
        for a, b in zip(cuts, cuts[1:]):
            seg = P[a:b + 1] if b < n else P[a:b]
            s = int(np.bincount(lab[a:b], minlength=len(dense)).argmax())
            d = dense[s]
            j = np.hypot(seg[:, None, 0] - d[None, :, 0], seg[:, None, 1] - d[None, :, 1]).argmin(1)
            t0, t1 = j[0] / max(len(d) - 1, 1), j[-1] / max(len(d) - 1, 1)
            if t1 < t0:
                seg, t0, t1 = seg[::-1], t1, t0
            pieces.append(dict(pts=seg, stroke=s, t0=t0, t1=t1))
    return sorted(pieces, key=lambda e: (e['stroke'], (e['t0'] + e['t1']) / 2))


def trace_stroke(w, skel, ink, sigma=4.0, avoid=None):
    """One standard stroke = one continuous brush path along the style skeleton.

    w is the registered 楷书 median (standard order and direction). The path is the
    cheapest skeleton route from the pixel nearest w's start to the one nearest its
    end, where leaving w costs (distance / sigma)^2 per pixel, so it crosses other
    strokes' junctions instead of being split there. Small skeleton breaks may be
    bridged (<= 3 px, expensive). Ends extend along w while still inside the ink.
    """
    line = np.zeros((R, R), np.uint8)
    W = np.round(w).astype(np.int32)
    cv2.polylines(line, [W], False, 1, 1)
    dline = cv2.distanceTransform((1 - line).astype(np.uint8), cv2.DIST_L2, 5)
    band = (dline <= 20) & skel
    if band.sum() < 2 or length(w) < 4:
        return None
    # Both ends must lie on the skeleton piece the stroke mostly runs along; a
    # registered end may otherwise land on a neighbouring stroke's skeleton.
    n, lab = cv2.connectedComponents(band.astype(np.uint8), connectivity=8)
    near = nearest_map(band)
    S = np.clip(np.round(resample(w, 1.0)).astype(int), 0, R - 1)
    hit = near[S[:, 1], S[:, 0]].astype(int)
    close = np.hypot(*(hit - S).T) <= 6
    votes = np.bincount(lab[hit[close, 1], hit[close, 0]], minlength=n) if close.any() else np.zeros(n, int)
    comp = int(votes[1:].argmax()) + 1 if n > 1 and votes[1:].any() else 0
    if not comp:
        return None
    ys, xs = np.nonzero(lab == comp)
    pix = {(x, y) for x, y in zip(xs, ys)}
    def nearest(p):
        d = np.hypot(xs - p[0], ys - p[1])
        k = int(d.argmin())
        return (int(xs[k]), int(ys[k])), float(d[k])
    a, da = nearest(w[0]); b, db = nearest(w[-1])
    if a == b:
        # Short stroke on one blob: press across that piece along the stroke direction.
        v = (w[-1] - w[0]) / max(np.hypot(*(w[-1] - w[0])), 1e-6)
        t = (xs - a[0]) * v[0] + (ys - a[1]) * v[1]
        lo, hi = int(t.argmin()), int(t.argmax())
        if lo == hi:
            return None
        return np.array([[xs[lo], ys[lo]], [xs[hi], ys[hi]]], float)
    jumps = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4) if max(abs(dx), abs(dy)) >= 2]
    dist = {a: 0.0}; prev = {}; heap = [(0.0, a)]
    import heapq
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            break
        if d > dist[u]:
            continue
        for (dx, dy), gap in [(o, False) for o in N8] + [(o, True) for o in jumps]:
            v = (u[0] + dx, u[1] + dy)
            if v not in pix:
                continue
            step = math.hypot(dx, dy)
            c = step * (1 + (dline[v[1], v[0]] / sigma) ** 2) * (6 if gap else 1) * (25 if avoid is not None and avoid[v[1], v[0]] else 1)
            if d + c < dist.get(v, 1e18):
                dist[v] = d + c; prev[v] = u; heapq.heappush(heap, (d + c, v))
    if b not in dist:
        return None
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    path = np.array(path[::-1], float)
    def inside(p, q):
        for t in np.linspace(0, 1, 8):
            x, y = np.round(p + (q - p) * t).astype(int)
            if not (0 <= x < R and 0 <= y < R and ink[y, x]):
                return False
        return True
    if np.hypot(*(w[0] - path[0])) > 2 and inside(w[0], path[0]):
        path = np.vstack([w[0], path])
    if np.hypot(*(w[-1] - path[-1])) > 2 and inside(path[-1], w[-1]):
        path = np.vstack([path, w[-1]])
    return path


def complete_strokes(paths, warped, skel, dt, near_px=5.0, min_len=0.0):
    """Draw the parts of the font no standard stroke traced, without splitting strokes.

    An undrawn skeleton chain touching an existing path's end extends that path
    (tips, hooks: the stroke stays one brush path). A free-standing chain is a
    stroke of this style's own form: it is written right after the standard stroke
    nearest to it, left-to-right / top-to-bottom. Returns (paths, order keys).
    """
    covered = np.zeros((R, R), np.uint8)
    for p in paths:
        for x, y in resample(p, 1.0) if len(p) > 1 else p:
            xi, yi = int(np.clip(round(x), 0, R - 1)), int(np.clip(round(y), 0, R - 1))
            cv2.circle(covered, (xi, yi), int(math.ceil(max(dt[yi, xi], 2.0))), 1, -1)
    rest = skel & ~covered.astype(bool)
    keys = [(i, 0) for i in range(len(paths))]
    if rest.sum() < 4:
        return paths, keys
    nodes, edges = raw_graph(rest)
    paths = [p.copy() for p in paths]
    extra = []
    for C in natural_strokes(edges) if edges else []:
        width = float(np.median([dt[int(np.clip(round(y), 0, R - 1)), int(np.clip(round(x), 0, R - 1))] for x, y in C]))
        if length(C) < max(6.0, 1.5 * width, min_len if best_touch(C, paths, near_px + width) is None else 0.0):
            continue
        best = None
        for i, p in enumerate(paths):
            for pe, at_end in ((p[-1], True), (p[0], False)):
                for ce, c_start in ((C[0], True), (C[-1], False)):
                    d = float(np.hypot(*(pe - ce)))
                    if d <= near_px + width and (best is None or d < best[0]):
                        best = (d, i, at_end, c_start)
        if best is not None:
            _, i, at_end, c_start = best
            seg = C if c_start else C[::-1]                  # seg starts at the touching end
            paths[i] = np.vstack([paths[i], seg]) if at_end else np.vstack([seg[::-1], paths[i]])
            continue
        a, b = C[0], C[-1]
        horizontal = abs(b[0] - a[0]) > abs(b[1] - a[1])
        if (horizontal and a[0] > b[0]) or (not horizontal and a[1] > b[1]):
            C = C[::-1]
        mid = C[len(C) // 2]
        s = int(np.argmin([np.hypot(*(resample(w, 1.0) - mid).T).min() for w in warped]))
        extra.append((C, (s, 1)))
    for C, k in extra:
        paths.append(C); keys.append(k)
    return paths, keys


def best_touch(C, paths, limit):
    """Index of a path whose end touches either end of chain C (within limit), else None."""
    for i, p in enumerate(paths):
        for pe in (p[0], p[-1]):
            for ce in (C[0], C[-1]):
                if float(np.hypot(*(pe - ce))) <= limit:
                    return i
    return None


def ink_snap(w, skel):
    """Fallback for short strokes (both ends on one skeleton point) and broken skeletons:
    the median pulled onto the nearest skeleton points, consecutive duplicates removed."""
    near = nearest_map(skel)
    P = np.clip(np.round(resample(w, 1.0)).astype(int), 0, R - 1)
    Q = near[P[:, 1], P[:, 0]].astype(float)
    keep = np.r_[True, np.any(np.diff(Q, axis=0) != 0, axis=1)]
    return Q[keep]


def dots(smooth, pieces, warped):
    """Ink blobs that kept no skeleton piece (dots) become a short press-and-lift."""
    n, lab = cv2.connectedComponents(smooth.astype(np.uint8), connectivity=8)
    hit = set()
    for e in pieces:
        P = np.clip(np.round(e['pts']).astype(int), 0, R - 1)
        hit.update(int(v) for v in lab[P[:, 1], P[:, 0]])
    dense = [resample(w, 1.0) for w in warped]
    out = []
    for k in range(1, n):
        if k in hit:
            continue
        yx = np.argwhere(lab == k).astype(float)
        if len(yx) < 12:
            continue
        c = yx.mean(0)
        _, sv, vt = np.linalg.svd(yx - c, full_matrices=False)
        half = max(1.5, 0.6 * sv[0] / math.sqrt(len(yx)))      # ~0.6 x the blob's half-extent
        a, b = (c - vt[0] * half)[::-1], (c + vt[0] * half)[::-1]
        if a[1] > b[1]:
            a, b = b, a                                       # a dot is written downwards
        mid = (a + b) / 2
        d = [np.hypot(*(dd - mid).T) for dd in dense]
        s = int(np.argmin([x.min() for x in d]))
        t = d[s].argmin() / max(len(dense[s]) - 1, 1)
        out.append(dict(pts=np.array([a, mid, b]), stroke=s, t0=t, t1=t))
    return out


# ---------------------------------------------------------------- keyframes

def rdp(points, tol, keep):
    """Douglas-Peucker on XY and compression; indices in keep always survive."""
    out = {0, len(points) - 1} | set(keep)
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[b, :2] - points[a, :2]
        L = max(np.hypot(*seg), 1e-9)
        rel = points[a + 1:b, :2] - points[a, :2]
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / L
        u = np.linspace(0, 1, b - a + 1)[1:-1]
        dz = np.abs(points[a + 1:b, 2] - (points[a, 2] * (1 - u) + points[b, 2] * u)) * 2.0
        err = np.maximum(dist, dz)
        i = int(err.argmax())
        inside = [k for k in out if a < k < b]
        if err[i] > tol or inside:
            m = inside[len(inside) // 2] if inside and err[i] <= tol else a + 1 + i
            out.add(m); stack += [(a, m), (m, b)]
    return points[sorted(out)]


def keyframes(path, dt, width_ref):
    """Pixel centreline -> [x, y, compression, feed] in the 50-unit cell (Y down)."""
    p = resample(path, 1.0)
    if len(p) >= 5:
        k = np.exp(-0.5 * (np.arange(-3, 4) / 1.2) ** 2); k /= k.sum()
        pad = np.pad(p, ((3, 3), (0, 0)), mode='edge')
        q = np.c_[np.convolve(pad[:, 0], k, 'valid'), np.convolve(pad[:, 1], k, 'valid')]
        q[0], q[-1] = p[0], p[-1]
        p = q
    P = np.clip(np.round(p).astype(int), 0, R - 1)
    hw = dt[P[:, 1], P[:, 0]]
    hw = np.convolve(np.pad(hw, 2, mode='edge'), np.ones(5) / 5, 'valid')
    comp = np.clip(0.12 + 0.68 * hw / width_ref, 0.08, 0.85)
    pts = np.c_[p * UNIT, comp]
    pts[0, 2] = pts[-1, 2] = 0.0
    # Touch down / lift within the first and last ~1 unit, not along a long chord.
    n = len(pts)
    keep = [i for i in (1, 2, n - 3, n - 2) if 0 < i < n - 1]
    pts = rdp(pts, 0.06, keep)
    feed = np.clip(0.88 - 0.6 * pts[:, 2], 0.3, 0.9)
    out = np.c_[np.clip(pts[:, :2], 0, 50), pts[:, 2], feed]
    return [[round(float(v), 6) for v in row] for row in out]


# ---------------------------------------------------------------- per character

_FONT = None
_CFG = None


def _init(font_path, cfg):
    global _FONT, _CFG
    from PIL import ImageFont
    _FONT = ImageFont.truetype(font_path, R)
    _CFG = cfg


def build_char(job):
    ch, source_ch, medians = job
    try:
        ink = render(_FONT, source_ch)
        if ink is None or ink.sum() < 30:
            return ch, None, 'empty glyph'
        smooth = cv2.GaussianBlur(ink.astype(np.float32), (0, 0), 1.2) > 0.5
        from stroke_paths import _thin_cpu
        skel = _thin_cpu(smooth)
        dt = cv2.distanceTransform(smooth.astype(np.uint8), cv2.DIST_L2, 5)
        nodes, edges = raw_graph(skel)
        edges = clean(nodes, edges, dt)
        if not edges:
            return ch, None, 'no skeleton'
        ref = [np.array([[x / 1024 * R, (900 - y) / 1024 * R] for x, y in m], float) for m in medians]
        warped = register(ref, skel)
        fallback = 0
        if _CFG['method'] == 'trace':
            # Structure follows 楷书: exactly one brush path per standard stroke, in the
            # standard order and direction, traced along the font's own skeleton.
            def trace(w, avoid=None):
                p = trace_stroke(w, skel, smooth, avoid=avoid)
                fb = p is None
                if fb:
                    p = ink_snap(w, skel)
                if len(p) < 2 or length(p) < 1.5:           # a dot: short press along the median
                    v = (w[-1] - w[0]) / max(np.hypot(*(w[-1] - w[0])), 1e-6)
                    p = np.vstack([p[0], p[0] + v * 2.0])
                return p, fb
            def overlap(a, b):
                a, b = resample(a, 1.0), resample(b, 1.0)
                return float((np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1]).min(1) <= 2).mean())
            traced = [trace(w) for w in warped]
            paths = [p for p, _ in traced]
            fallback = sum(fb for _, fb in traced)
            # A short stroke that latched onto a longer one (a dot riding a 横) is traced
            # again with the longer stroke's line made expensive, so it finds its own ink.
            for i in range(len(paths)):
                for j in range(len(paths)):
                    if i != j and length(paths[i]) > 10 and length(paths[i]) <= length(paths[j]) and overlap(paths[i], paths[j]) > 0.6:
                        avoid = np.zeros((R, R), np.uint8)
                        cv2.polylines(avoid, [np.round(paths[j]).astype(np.int32)], False, 1, 5)
                        paths[i], _ = trace(warped[i], avoid.astype(bool))
            for k, (p, w) in enumerate(zip(paths, warped)):
                Q = np.clip(np.round(resample(p, 1.0)).astype(int), 0, R - 1)
                if smooth[Q[:, 1], Q[:, 0]].mean() < 0.95:
                    return ch, None, 'stroke leaves the ink'
                # A stroke latched onto a neighbour (wrong order/direction) is far longer
                # or shorter than its standard stroke: never keep such a character.
                lw = length(w)
                if lw > 15 and not 0.4 <= length(p) / lw <= 2.5:
                    return ch, None, 'stroke %d does not match its standard stroke' % (k + 1)
            for i in range(len(paths)):
                for j in range(i + 1, len(paths)):
                    a, b = (paths[i], paths[j]) if length(paths[i]) <= length(paths[j]) else (paths[j], paths[i])
                    if length(a) > 10 and overlap(a, b) > 0.6:
                        return ch, None, 'strokes %d and %d trace the same line' % (i + 1, j + 1)
            paths, keys = complete_strokes(paths, warped, skel, dt)
            paths = [p for _, p in sorted(zip(keys, paths), key=lambda kp: kp[0])]
        else:
            # True cursive: whole strokes of the font (never split at crossings), each
            # one brush path, ordered and oriented by the standard stroke they follow.
            pieces = label_strokes(natural_strokes(edges), warped)
            pieces = sorted(pieces + dots(smooth, pieces, warped), key=lambda e: (e['stroke'], (e['t0'] + e['t1']) / 2))
            paths = [e['pts'] for e in pieces if length(e['pts']) >= 2.5]
        strokes = [dict(module='style', points=keyframes(p, dt, _CFG['width_ref'])) for p in paths]
        # Ink coverage: fraction of glyph pixels reached by a brush of the local width.
        reach = np.zeros((R, R), np.uint8)
        for p in paths:
            for x, y in resample(p, 1.5):
                xi, yi = int(np.clip(round(x), 0, R - 1)), int(np.clip(round(y), 0, R - 1))
                cv2.circle(reach, (xi, yi), int(math.ceil(dt[yi, xi] + 1.5)), 1, -1)
        coverage = float((reach.astype(bool) & smooth).sum() / max(smooth.sum(), 1))
        stats = dict(pen_downs=len(strokes), kai_strokes=len(medians), coverage=round(coverage, 4), fallback=fallback)
        return ch, dict(character=ch, source_character=source_ch, strokes=strokes, stats=stats), None
    except Exception as exc:                                       # reported, never silently kept
        return ch, None, '%s: %s' % (type(exc).__name__, exc)


def width_reference(font_path, chars):
    """90th percentile of skeleton half-width over a character sample (pressure scale)."""
    from PIL import ImageFont
    from stroke_paths import _thin_cpu
    font = ImageFont.truetype(font_path, R)
    vals = []
    for ch in chars:
        ink = render(font, ch)
        if ink is None:
            continue
        smooth = cv2.GaussianBlur(ink.astype(np.float32), (0, 0), 1.2) > 0.5
        dt = cv2.distanceTransform(smooth.astype(np.uint8), cv2.DIST_L2, 5)
        vals.append(dt[_thin_cpu(smooth)])
    return float(np.percentile(np.concatenate(vals), 90))


def source_map(chars, cmap, st_table, variants):
    """Font code point to draw for each repertoire character (seal fonts need traditional forms)."""
    out = {}
    for ch in chars:
        if ord(ch) in cmap:
            out[ch] = ch
            continue
        for t in st_table.get(ch, []):
            found = [v for v in [t] + variants.get(t, []) if ord(v) in cmap]
            if found:
                out[ch] = found[0]
                break
    return out


def opencc_table(path):
    table = {}
    if path:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('#') or '\t' not in line:
                continue
            s, t = line.split('\t')
            table[s] = t.split()
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--style', required=True, choices=sorted(STYLES))
    ap.add_argument('--font', type=Path, required=True)
    ap.add_argument('--font-label', required=True, help='font name shown in the notice, e.g. 志莽行书')
    ap.add_argument('--font-license', required=True, help='licence summary for the notice')
    ap.add_argument('--st-table', type=Path, help='OpenCC STCharacters.txt (simplified -> traditional)')
    ap.add_argument('--variants', type=Path, help='OpenCC TWVariants.txt (alternative traditional forms)')
    ap.add_argument('--graphics', type=Path, help='Make Me a Hanzi graphics.txt: stroke order of traditional source forms')
    ap.add_argument('--min-coverage', type=float, default=0.85)
    ap.add_argument('--limit', type=int, default=0, help='only the first N characters (trial runs)')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/calligraphy/styles')
    ap.add_argument('--jobs', type=int, default=max(1, multiprocessing.cpu_count() - 2))
    args = ap.parse_args()
    from fontTools.ttLib import TTFont
    from tools.build_glyph_library import repertoire
    cfg = dict(STYLES[args.style])
    chars = repertoire()
    if args.limit:
        chars = chars[:args.limit]
    cmap = TTFont(str(args.font), fontNumber=0).getBestCmap()
    mapping = source_map(chars, cmap, opencc_table(args.st_table), opencc_table(args.variants))
    con = sqlite3.connect(str(ROOT / 'data/calligraphy/glyphs.sqlite'))
    kai = {ch: [s['source_median'] for s in json.loads(p)['strokes']]
           for ch, p in con.execute('SELECT character, payload FROM glyphs')}
    con.close()
    cfg['width_ref'] = width_reference(str(args.font), [mapping[c] for c in list(mapping)[:300:3]])
    # A traditional source form (篆书) is ordered by its own Make Me a Hanzi strokes when available.
    trad = {}
    wanted = {mapping[c] for c in chars if c in mapping and mapping[c] != c}
    if args.graphics and wanted:
        with args.graphics.open(encoding='utf-8') as f:
            for line in f:
                item = json.loads(line)
                if item['character'] in wanted:
                    trad[item['character']] = item['medians']
    jobs = [(ch, mapping[ch], trad.get(mapping[ch], kai[ch])) for ch in chars if ch in mapping]
    cfg['traditional_order'] = sum(1 for ch in chars if ch in mapping and mapping[ch] in trad)
    records, rejected = {}, {ch: 'not in font' for ch in chars if ch not in mapping}
    with multiprocessing.Pool(args.jobs, initializer=_init, initargs=(str(args.font), cfg)) as pool:
        for i, (ch, rec, err) in enumerate(pool.imap_unordered(build_char, jobs, chunksize=8)):
            if rec is None:
                rejected[ch] = err
            elif rec['stats']['coverage'] < args.min_coverage:
                rejected[ch] = 'coverage %.3f' % rec['stats']['coverage']
            else:
                records[ch] = rec
            if (i + 1) % 250 == 0:
                print('%d/%d' % (i + 1, len(jobs)), flush=True)
    kept = ''.join(ch for ch in chars if ch in records)
    notice = ('%s brush trajectories derived 2026-10-25 from the font %s (%s): centrelines of the rendered glyphs, '
              'stroke order registered from the Make Me a Hanzi / Arphic 楷书 library (Arphic Public License). '
              'For use on this machine only; the font itself is not redistributed. No warranty; physical brush '
              'results not yet verified.') % (cfg['label'], args.font_label, args.font_license)
    for rec in records.values():
        rec['source_notice'] = notice
    raw = ''.join(json.dumps(records[ch], ensure_ascii=False, separators=(',', ':')) + '\n' for ch in kept)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    cov = [r['stats']['coverage'] for r in records.values()]
    meta = dict(schema='brush-glyphs-v1', style=args.style, label=cfg['label'],
                version='%s3500-20261025-%s' % (args.style, digest[:12]), count=len(kept), characters=kept,
                content_sha256=digest, source_notice=notice, font=args.font_label, font_license=args.font_license,
                font_sha256=hashlib.sha256(args.font.read_bytes()).hexdigest(), cursive=cfg['cursive'],
                width_reference_px=round(cfg['width_ref'], 4), raster_px=R, coordinates='50-unit XY-down',
                stroke_order='one brush path per standard stroke, standard order and direction (Make Me a Hanzi; '
                             'traditional source forms use their own order when available: %d)' % cfg['traditional_order'],
                rejected=dict(sorted(rejected.items())), coverage_min=round(min(cov), 4) if cov else None,
                coverage_median=round(float(np.median(cov)), 4) if cov else None,
                verification='structural offline; physical ink results pending')
    args.out.mkdir(parents=True, exist_ok=True)
    db = args.out / ('%s.sqlite' % args.style)
    tmp = args.out / ('%s.build.sqlite' % args.style)
    if tmp.exists():
        tmp.unlink()
    with sqlite3.connect(str(tmp)) as out:
        out.execute('CREATE TABLE glyphs (character TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        out.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        out.executemany('INSERT INTO glyphs VALUES (?,?)',
                        [(ch, json.dumps(records[ch], ensure_ascii=False, separators=(',', ':'))) for ch in kept])
        out.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(meta, ensure_ascii=False)))
    out.close()
    tmp.replace(db)
    print(json.dumps(dict(style=args.style, count=len(kept), rejected=len(rejected), bytes=db.stat().st_size,
                          coverage_median=meta['coverage_median'], version=meta['version']), ensure_ascii=False))


if __name__ == '__main__':
    main()
