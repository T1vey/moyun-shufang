"""Centerline graph extraction and outside-in pen trails (no motor I/O).

Pixel graph edges are consumed once. Junctions join opposite tangent branches;
they never force an arm to backtrack over an edge to reach another branch.
Coordinates use the full input canvas, x right / y up, in millimetres.
"""
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

ALGORITHM = 'centerline-graph-v1'
PIPELINE_VERSION = 'drawing-quality-v2'


def _thinning_tables():
    codes = np.arange(256, dtype=np.uint16)
    p = [(codes >> i) & 1 for i in range(8)]
    common = ((sum(p) >= 2) & (sum(p) <= 6) &
              (sum((p[i] == 0) & (p[(i+1) % 8] != 0) for i in range(8)) == 1))
    return (common & (p[0]*p[2]*p[4] == 0) & (p[2]*p[4]*p[6] == 0),
            common & (p[0]*p[2]*p[6] == 0) & (p[0]*p[4]*p[6] == 0))


_THIN_TABLES = _thinning_tables()
_THIN_KERNEL = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], dtype=np.float32)


def _thin_cpu(binary):
    """Exact Zhang-Suen rules, cropped and evaluated by an 8-neighbor LUT."""
    source = np.asarray(binary, dtype=bool)
    if source.ndim != 2:
        raise ValueError('中心线输入必须是二维图像')
    result = np.zeros(source.shape, dtype=bool)
    ys, xs = np.nonzero(source)
    if not len(ys):
        return result
    y0, y1, x0, x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1
    image = np.pad(source[y0:y1, x0:x1].astype(np.uint8), 1)
    for _ in range(max(image.shape)):
        changed = False
        for table in _THIN_TABLES:
            code = cv2.filter2D(image, cv2.CV_16U, _THIN_KERNEL,
                                borderType=cv2.BORDER_CONSTANT)[1:-1, 1:-1]
            remove = (image[1:-1,1:-1] != 0) & table[code]
            if remove.any():
                image[1:-1,1:-1][remove] = 0
                changed = True
        if not changed:
            result[y0:y1, x0:x1] = image[1:-1,1:-1]
            return result
    raise ValueError('中心线细化未收敛')


def thin(binary):
    """Use the boot-loaded lineart core when present; retain the exact CPU oracle."""
    from lineart_backend import thin_or_cpu
    return thin_or_cpu(binary,_thin_cpu)


def _neighbors(pixels, point):
    x, y = point
    result = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            q = (x+dx, y+dy)
            if (dx == 0 and dy == 0) or q not in pixels:
                continue
            # Suppress diagonal shortcuts when the orthogonal connection exists.
            if dx and dy and ((x+dx,y) in pixels or (x,y+dy) in pixels):
                continue
            result.append(q)
    return sorted(result)


def _graph_trails_python(skeleton):
    pixels = {tuple(map(int, p[::-1])) for p in np.argwhere(skeleton)}
    adj = {p: _neighbors(pixels,p) for p in sorted(pixels)}
    junctions = {p for p in pixels if len(adj[p]) >= 3}
    nodes, owner = [], {}
    remaining = set(junctions)
    while remaining:
        seed = min(remaining); remaining.remove(seed)
        cluster, todo = [seed], [seed]
        while todo:
            for q in adj[todo.pop()]:
                if q in remaining:
                    remaining.remove(q); cluster.append(q); todo.append(q)
        node = len(nodes)
        nodes.append(np.mean(cluster,axis=0).tolist())
        owner.update({p:node for p in cluster})
    junction_count=len(nodes)
    for p in sorted(pixels):
        if len(adj[p]) == 1:
            owner[p] = len(nodes); nodes.append(list(p))

    def key(a,b):
        return tuple(sorted((a,b)))
    visited = {key(p,q) for p in junctions for q in adj[p]
               if q in junctions and owner[p] == owner[q]}
    contracted = len(visited)
    edges = []
    def trace(p,q):
        chain = [nodes[owner[p]][:] if p in owner else list(p)]
        start = owner.get(p)
        previous, current = p, q
        visited.add(key(p,q))
        while True:
            chain.append(nodes[owner[current]][:] if current in owner else list(current))
            if current in owner or current == p:
                break
            options = [v for v in adj[current] if v != previous and key(current,v) not in visited]
            if not options:
                break
            nxt = options[0]
            visited.add(key(current,nxt))
            previous, current = current, nxt
        cleaned = [v for i,v in enumerate(chain) if i == 0 or v != chain[i-1]]
        if len(cleaned) >= 2:
            edges.append(dict(points=cleaned, nodes=(start,owner.get(current))))
    for p in sorted(owner):
        for q in adj[p]:
            if key(p,q) not in visited:
                trace(p,q)
    # Components without endpoints/junctions are closed degree-two cycles.
    for p in sorted(pixels):
        for q in adj[p]:
            if key(p,q) not in visited:
                trace(p,q)
    raw_edges = sum(len(v) for v in adj.values())//2
    if len(visited) != raw_edges:
        raise ValueError('中心线图存在未访问的边')

    ports = {}
    for i,e in enumerate(edges):
        for end,n in enumerate(e['nodes']):
            if n is not None:
                ports.setdefault(n,[]).append((i,end))
    def tangent(port):
        i,end = port
        p = np.asarray(edges[i]['points'][::1 if end == 0 else -1],dtype=float)
        distances = np.linalg.norm(p-p[0],axis=1)
        j = next((j for j,d in enumerate(distances) if d >= 4),len(p)-1)
        v = p[j]-p[0]
        return v/max(float(np.linalg.norm(v)),1e-12)
    pairing = {}
    for n, candidates in sorted(ports.items()):
        free = list(candidates)
        while len(free) >= 2:
            choices = [(float(np.dot(tangent(a),tangent(b))),a,b)
                       for ai,a in enumerate(free) for b in free[ai+1:]]
            score,a,b = min(choices)
            # Joining branches may turn at most 80 degrees. Other branches
            # remain independent trails; no bridging of disconnected pixels.
            if score > -math.cos(math.radians(80)):
                break
            pairing[a] = b; pairing[b] = a
            free.remove(a); free.remove(b)
    used, trails = set(), []
    starts = [(i,end) for i in range(len(edges)) for end in (0,1) if (i,end) not in pairing]
    starts += [(i,0) for i in range(len(edges))]
    for start in starts:
        i,end = start
        if i in used:
            continue
        trail = []
        while i not in used:
            used.add(i)
            points = edges[i]['points'][::1 if end == 0 else -1]
            trail.extend(points if not trail else points[1:])
            nxt = pairing.get((i,1-end))
            if nxt is None:
                break
            i,end = nxt
        trails.append(trail)
    if len(used) != len(edges):
        raise ValueError('中心线笔画存在未访问的链')
    return trails, dict(pixel_edges=raw_edges, visited_pixel_edges=len(visited),
                        contracted_junction_edges=contracted, raw_chains=len(edges),
                        consumed_chains=len(used), edge_revisits=0,
                        junction_clusters=junction_count)


def graph_trails(skeleton):
    from native.lineart import get_kernel
    core=get_kernel()
    if core is not None:
        try:return core.graph(skeleton)
        except (ValueError,RuntimeError):pass
    return _graph_trails_python(skeleton)


def _simplify(path, epsilon):
    points = np.asarray(path,dtype=np.float32)
    closed = len(points) > 2 and np.linalg.norm(points[0]-points[-1]) < 1e-8
    result = cv2.approxPolyDP(points.reshape(-1,1,2),epsilon,closed).reshape(-1,2).astype(float).tolist()
    if closed and len(result) >= 3 and result[-1] != result[0]:
        result.append(result[0][:])
    return result


def outside_in(paths):
    """Geometric containment, then largest outer chain, then nearby endpoints.

    An open enclosing arc is closed only for containment testing. No chord is
    added to its drawing path. This handles the open duck head outline.
    """
    arrays = [np.asarray(p,dtype=np.float32) for p in paths]
    areas = [abs(float(cv2.contourArea(p))) for p in arrays]
    parents = {}
    for i,p in enumerate(arrays):
        containers=[]
        for j,q in enumerate(arrays):
            if i == j or areas[j] <= max(areas[i]+1e-5,1.0):
                continue
            # Test samples from the whole chain, not only its centroid.
            probe=p[np.linspace(0,len(p)-1,min(25,len(p))).astype(int)]
            inside=sum(cv2.pointPolygonTest(q,(float(v[0]),float(v[1])),False) >= 0 for v in probe)
            if inside >= math.ceil(.9*len(probe)):
                containers.append(j)
        if containers:
            parents[i]=min(containers,key=lambda j:(areas[j],j))
    def depth(i):
        return 1+depth(parents[i]) if i in parents else 0
    depths=[depth(i) for i in range(len(paths))]
    spans=[float(np.linalg.norm(np.ptp(p,axis=0))) for p in arrays]
    remaining=set(range(len(paths))); order=[]; layers=[]; tip=[0.,0.]
    while remaining:
        layer=min(depths[i] for i in remaining)
        group=[i for i in remaining if depths[i] == layer]
        if not order:
            i=max(group,key=lambda i:(spans[i],areas[i],-i))
            end=min((0,-1),key=lambda e:math.dist(tip,paths[i][e]))
        else:
            _,i,end=min((math.dist(tip,paths[i][end]),i,end) for i in group for end in (0,-1))
        chain=[p[:] for p in paths[i][::1 if end == 0 else -1]]
        order.append(chain);layers.append(layer);tip=chain[-1];remaining.remove(i)
    return order,layers


def extract_centerlines(gray, width_mm, height_mm, epsilon_mm=.12):
    height,width=gray.shape
    # Keep light but locally distinct AI lines, as well as solid black ink.
    blurred=cv2.blur(gray,(15,15)).astype(np.int16)
    mask=(gray < 180) | ((gray < 238) & (blurred-gray.astype(np.int16) >= 5))
    skeleton=thin(mask)
    trails,graph=graph_trails(skeleton)
    paths=[]; discarded=0
    for trail in trails:
        mm=[[x*width_mm/width,(height-y)*height_mm/height] for x,y in trail]
        length=sum(math.dist(a,b) for a,b in zip(mm,mm[1:]))
        # Drop only sub-pixel noise, never the remainder of an over-budget job.
        if length < min(width_mm/width,height_mm/height)*1.5:
            discarded+=1;continue
        simplified=_simplify(mm,epsilon_mm)
        if len(simplified) >= 2:
            paths.append(simplified)
    if not paths:
        raise ValueError('未提取到连续笔画，请使用清晰线稿')
    ordered,layers=outside_in(paths)
    graph.update(discarded_noise_trails=discarded)
    return ordered,layers,graph,skeleton


def tidy_strokes(paths, min_length_mm=2., join_mm=1., target_strokes=60):
    """Join short aligned gaps, then discard only explicitly bounded fragments.

    Never truncate the longest N strokes: exceeding the target is reported,
    not a reason to silently erase recognizable features. Closed contours are
    not joined. Reversing a chain preserves its geometry.
    """
    if not (0 <= min_length_mm <= 3 and 0 <= join_mm <= 1.2):
        raise ValueError('糖画整理阈值超出范围')
    chains = [[list(p) for p in chain] for chain in paths]
    before = len(chains); joins = 0; added = 0.
    def length(chain): return sum(math.dist(a, b) for a, b in zip(chain, chain[1:]))
    def aligned(a, b):
        norm = math.hypot(*a)*math.hypot(*b)
        return norm > 1e-12 and sum(x*y for x,y in zip(a,b)) >= .7071067811865476*norm
    def vector(a, b): return [b[0]-a[0], b[1]-a[1]]
    # Endpoint candidates are bounded by the existing input budget. A small
    # spatial index avoids an all-pairs scan on noisy images.
    while join_mm > 0 and len(chains) <= 512 and joins < 64:
        grid = {}
        for i, chain in enumerate(chains):
            if math.dist(chain[0], chain[-1]) <= 1e-8: continue
            for end in (0, -1):
                x,y = chain[end]
                grid.setdefault((math.floor(x/join_mm), math.floor(y/join_mm)), []).append((i,end))
        best = None
        for key, entries in grid.items():
            for i, end_i in entries:
                a = chains[i] if end_i == -1 else chains[i][::-1]
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        for j, end_j in grid.get((key[0]+dx,key[1]+dy), ()):
                            if i >= j: continue
                            b = chains[j] if end_j == 0 else chains[j][::-1]
                            gap = math.dist(a[-1], b[0])
                            if gap > join_mm: continue
                            va, vb = vector(a[-2],a[-1]), vector(b[0],b[1])
                            if not aligned(va,vb): continue
                            bridge = vector(a[-1],b[0])
                            if gap > 1e-8 and (not aligned(va,bridge) or not aligned(bridge,vb)): continue
                            candidate = (gap, i, j, end_i, end_j)
                            if best is None or candidate < best: best = candidate
        if best is None: break
        gap,i,j,end_i,end_j = best
        a = chains[i] if end_i == -1 else chains[i][::-1]
        b = chains[j] if end_j == 0 else chains[j][::-1]
        chains[i] = a+(b[1:] if gap <= 1e-8 else b)
        del chains[j]
        joins += 1; added += gap
    kept = [chain for chain in chains if length(chain) >= min_length_mm]
    # A tiny legitimate drawing remains usable instead of becoming empty.
    if not kept: kept = chains
    removed = sum(length(chain) for chain in chains if length(chain) < min_length_mm) if len(kept) < len(chains) else 0.
    return kept, dict(version='sugar-tidy-v1', min_length_mm=min_length_mm, join_mm=join_mm,
        before_strokes=before, after_strokes=len(kept), joined=joins, removed_strokes=len(chains)-len(kept),
        removed_length_mm=removed, added_length_mm=added, target_strokes=target_strokes,
        target_reached=len(kept)<=target_strokes, policy='bounded_fragments_no_top_n_truncation')


def validate_paths(data):
    if not isinstance(data,dict) or data.get('units') != 'mm':
        raise ValueError('笔画单位必须是 mm')
    width,height=data.get('width_mm'),data.get('height_mm')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 2 <= v <= 300 for v in (width,height)):
        raise ValueError('绘制尺寸范围为 2–300 mm')
    paths=data.get('paths')
    if not isinstance(paths,list) or not paths or len(paths) > 12000:
        raise ValueError('笔画列表为空或超出预算')
    segments=0
    for chain in paths:
        if not isinstance(chain,list) or len(chain) < 2:
            raise ValueError('每条笔画至少需要两个点')
        segments+=len(chain)-1
        for p in chain:
            if (not isinstance(p,list) or len(p) != 2
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in p)
                    or not -1e-4 <= p[0] <= width+1e-4 or not -1e-4 <= p[1] <= height+1e-4):
                raise ValueError('笔画坐标必须是画布内有限的二维毫米值')
    if segments > 12000:
        raise ValueError('笔画超出 12000 段预算')
    return len(paths),segments


def path_digest(data):
    identity={k:data.get(k) for k in ('units','width_mm','height_mm','paths','algorithm_version','coordinate_system')}
    return hashlib.sha256(json.dumps(identity,separators=(',',':'),sort_keys=True,allow_nan=False).encode()).hexdigest()


def resize_paths(data, width_mm, height_mm):
    """Scale immutable registered strokes; retain order and source image identity."""
    import copy
    validate_paths(data)
    resized=copy.deepcopy(data)
    sx,sy=width_mm/data['width_mm'],height_mm/data['height_mm']
    resized.update(width_mm=width_mm,height_mm=height_mm,
        paths=[[[x*sx,y*sy] for x,y in chain] for chain in data['paths']])
    validate_paths(resized)
    resized['draw_length_mm']=sum(math.hypot(b[0]-a[0],b[1]-a[1])
        for chain in resized['paths'] for a,b in zip(chain,chain[1:]))
    resized['path_sha256']=path_digest(resized)
    resized['drawing_resize']=dict(source_width_mm=data['width_mm'],source_height_mm=data['height_mm'],
        source_path_sha256=path_digest(data),scale_x=sx,scale_y=sy)
    return resized


def save_preview(data,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    width,height=data['width_mm'],data['height_mm']
    colors=('#2563eb','#dc2626','#16a34a','#9333ea','#d97706','#0891b2')
    def display_y(y):
        return y if data.get('coordinate_system') == 'full_canvas_xy_down' else height-y
    parts=['<rect x="-2" y="-2" width="104%" height="104%" fill="white"/>']
    previous=None
    for i,p in enumerate(data['paths']):
        color=colors[i%len(colors)]
        points=' '.join('%.5f,%.5f'%(x,display_y(y)) for x,y in p)
        if previous is not None:
            parts.append('<path d="M %.5f %.5f L %.5f %.5f" stroke="#cbd5e1" stroke-width=".12" stroke-dasharray=".7 .7"/>'%(previous[0],display_y(previous[1]),p[0][0],display_y(p[0][1])))
        parts.append('<polyline fill="none" stroke="%s" stroke-width=".22" points="%s"/>'%(color,points))
        parts.append('<circle cx="%.5f" cy="%.5f" r=".45" fill="%s"/><text x="%.5f" y="%.5f" font-size="2" fill="%s">%d</text>'%(p[0][0],display_y(p[0][1]),color,p[0][0]+.6,display_y(p[0][1])-.6,color,i+1))
        previous=p[-1]
    svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 %.5f %.5f">%s</svg>'%(width+4,height+4,''.join(parts))
    (output/'paths.svg').write_text(svg,encoding='utf-8')


def make_result(gray, source_bytes, output, style, width_mm, height_mm, max_segments, detail,
                coordinate_system='full_canvas_xy_up', diagnostics=True, stroke_profile='faithful'):
    if coordinate_system not in ('full_canvas_xy_up','full_canvas_xy_down'):
        raise ValueError('未知图像坐标方向')
    epsilon={'fine':.10,'balanced':.15,'simple':.22}[detail]
    paths,layers,graph,skeleton=extract_centerlines(gray,width_mm,height_mm,epsilon)
    if stroke_profile not in ('faithful', 'sugar'):
        raise ValueError('未知笔画整理模式')
    tidy = None
    if stroke_profile == 'sugar':
        paths, tidy = tidy_strokes(paths)
        paths, layers = outside_in(paths)
    from path_quality import smooth_strokes
    paths, smoothing = smooth_strokes(paths)
    if coordinate_system == 'full_canvas_xy_down':
        paths=[[[x,height_mm-y] for x,y in p] for p in paths]
    result=dict(units='mm',width_mm=width_mm,height_mm=height_mm,style=style,
                engine='SO101_centerline_graph',algorithm_version=ALGORITHM,
                coordinate_system=coordinate_system,paths=paths,strokes=len(paths),
                segments=sum(len(p)-1 for p in paths),detail=detail,
                source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                ordering='outside_in',stroke_layers=layers,
                draw_length_mm=sum(math.dist(a,b) for p in paths for a,b in zip(p,p[1:])),
                extraction=dict(resolution=[gray.shape[1],gray.shape[0]],simplify_error_mm=epsilon,
                                graph=graph,budget_policy='reject_over_budget_no_path_deletion'))
    if tidy is not None:
        result['extraction']['tidy'] = tidy
        result['extraction']['budget_policy'] = 'bounded_fragments_then_reject_over_budget'
        result['algorithm_version'] += '+sugar-tidy-v1'
    result['extraction']['smoothing'] = smoothing
    from lineart_backend import last_metrics
    result['extraction']['thinning'] = last_metrics()
    result['algorithm_version'] += '+' + smoothing['version']
    if result['segments'] > max_segments:
        raise ValueError('提取到 %d 段，超过 %d 段；请提高预算或选择较低精度，未删除任何笔画'%(result['segments'],max_segments))
    validate_paths(result)
    result['path_sha256']=path_digest(result)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'paths.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',', ':'),allow_nan=False),encoding='utf-8')
    if diagnostics:
        cv2.imwrite(str(output/'centerline.png'),skeleton.astype(np.uint8)*255)
        save_preview(result,output)
    return result
