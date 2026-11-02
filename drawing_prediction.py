"""Ordered drawing preview data: exact PC segments or calibrated command FK."""
import csv
import math
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from stroke_paths import validate_paths, path_digest


def ordered_preview(paths):
    strokes, count = validate_paths(paths)
    rows = []
    for stroke, chain in enumerate(paths['paths'], 1):
        for local, (start, end) in enumerate(zip(chain, chain[1:]), 1):
            rows.append(dict(order=len(rows) + 1, stroke=stroke, stroke_segment=local,
                             start_mm=list(start), end_mm=list(end),
                             length_mm=math.dist(start, end), predicted_points_mm=None))
    return dict(schema='so101-drawing-preview-v1', mode='paths',
                title='提取路径预测', width_mm=paths['width_mm'], height_mm=paths['height_mm'],
                coordinate_system=paths.get('coordinate_system', 'full_canvas_xy_up'),
                path_sha256=path_digest(paths), source_sha256=paths.get('source_sha256'),
                strokes=strokes, segments=count, draw_length_mm=sum(row['length_mm'] for row in rows),
                rows=rows, explanation='显示将上传的落笔路径；尚未计入机械臂运动学和实物误差。')


def feedback_preview(data, trace):
    """Project recorded encoder positions; preserve source segment IDs/order."""
    result=ordered_preview(data['paths'])
    paper=data['machine']['paper']
    origin=np.asarray(data['drawing']['plane_origin_m'])
    u,v=[np.asarray(data['drawing'].get('plane_'+k,paper[k])) for k in ('u','v')]
    width,height=result['width_mm'],result['height_mm']
    from drawing_geometry import inverse_projection
    inverse=inverse_projection(data['drawing'])
    lookup={(row['stroke']-1,row['stroke_segment']-1):row for row in result['rows']}
    assigned=0;maximum=axis_max=0.
    previous=None
    for index,point in enumerate(trace.get('points',[])):
        source=point.get('source_segment_id')
        if point.get('phase')!='DRAW' or not isinstance(source,(list,tuple)) or len(source)!=2:
            previous=None;continue
        row=lookup.get(tuple(source))
        if row is None:continue
        position=np.asarray(point['model_tip_m'])-origin
        xy=inverse@np.asarray([position@u,position@v])*1000
        projected=[float(xy[0]+width/2),float(xy[1]+height/2)]
        if row['predicted_points_mm'] is None:
            row['predicted_points_mm']=[]
            if previous is not None and previous[0]==point['stroke']:
                row['predicted_points_mm'].append(previous[1])
        row['predicted_points_mm'].append(projected)
        row.setdefault('command_first',index+1);row['command_last']=index+1
        row.setdefault('time_start_s',point['elapsed_s']);row['time_end_s']=point['elapsed_s']
        previous=(point['stroke'],projected)
        maximum=max(maximum,point.get('tip_error_m',0.)*1000)
        axis_max=max(axis_max,point.get('pen_axis_error_deg',0.))
        assigned+=1
    result.update(mode='feedback',title='编码器实际执行轨迹重建',predicted_commands=assigned,
        drawing_offset_mm=data['drawing'].get('drawing_offset_mm',[0,0]),
        max_command_target_error_mm=maximum,max_pen_axis_error_deg=axis_max,
        unrepresented_segments=sum(row['predicted_points_mm'] is None for row in result['rows']),
        explanation='黑线由实际编码器反馈重建，灰线为目标路径。此图可查看跟随变形；没有接触传感器，黑线不代表纸上实际墨迹。')
    return result


def command_preview(data):
    """Calculate on PC from one plan's frozen paths, model and integer commands."""
    from planning import Model, load
    from motion import counts_from_angles, angles_from_counts
    if data.get('status') != 'OK':
        raise ValueError('只能预测成功规划的绘画效果')
    paths, spec = data['paths'], data['drawing']
    result = ordered_preview(paths)
    commands = data.get('commands')
    if not isinstance(commands, list) or not commands:
        raise ValueError('规划没有舵机指令')
    if len(commands) > 500000:
        raise ValueError('规划指令数量超出预览预算')
    machine = data.get('machine')
    real = data.get('mode') == 'real'
    if real and not machine:
        raise ValueError('规划缺少冻结的机器标定，不能使用其他标定代替')
    model = Model(machine['model'] if real else load('nominal_so101.json'))
    origin = np.asarray(spec['plane_origin_m'], dtype=float)
    basis = np.asarray([spec.get('plane_u', [1, 0, 0]), spec.get('plane_v', [0, 1, 0])], dtype=float)
    if (origin.shape != (3,) or basis.shape != (2, 3) or not np.isfinite(origin).all()
            or not np.isfinite(basis).all() or not np.allclose(basis @ basis.T, np.eye(2), atol=1e-6)):
        raise ValueError('规划纸面坐标无效')
    rows_by_stroke = {}
    for row in result['rows']:
        rows_by_stroke.setdefault(row['stroke'] - 1, []).append(row)
    # Verify that original segment numbering actually belongs to this drawing.
    if len(spec['strokes']) != result['strokes']:
        raise ValueError('规划与笔画数量不一致')
    offset = np.asarray([result['width_mm'], result['height_mm']]) / 2
    from drawing_geometry import inverse_projection
    inverse=inverse_projection(spec)
    def project(points): return (np.asarray(points) - origin) @ basis.T @ inverse.T * 1000 + offset
    for index, stroke in enumerate(spec['strokes']):
        rows = rows_by_stroke[index]
        segments = stroke['segments']
        if len(segments) != len(rows): raise ValueError('规划与线段数量不一致')
        for row, segment in zip(rows, segments):
            if segment['type'] != 'line' or not np.allclose(
                    project([segment['start_m'], segment['end_m']]),
                    [row['start_mm'], row['end_mm']], atol=1e-5):
                raise ValueError('规划与原始路径不一致')
    joints = np.asarray([command['q_rad'] for command in commands], dtype=float)
    if real:
        from motion import quantized_angles_many
        joints = quantized_angles_many(machine, joints)
    positions = model.pose_many(np.asarray(joints))[:, :3, 3]
    projected = project(positions)
    targets = project([command['tip_target_m'] for command in commands])
    starts = {stroke: np.asarray([row['start_mm'] for row in rows]) for stroke, rows in rows_by_stroke.items()}
    vectors = {stroke: np.asarray([row['end_mm'] for row in rows]) - starts[stroke]
               for stroke, rows in rows_by_stroke.items()}
    current = {}; finished = {}; last_stroke = -1; errors = []; assigned = 0
    previous_stroke = None
    for index, command in enumerate(commands):
        if not command.get('pen_down'):
            previous_stroke = None
            continue
        if command.get('phase') != 'DRAW': raise ValueError('落笔指令阶段不一致')
        stroke = command['stroke']
        if type(stroke) is not int or stroke not in rows_by_stroke or stroke < last_stroke:
            raise ValueError('绘画指令笔画顺序无效')
        last_stroke = stroke
        target = targets[index]
        if target.shape != (2,) or not np.isfinite(target).all(): raise ValueError('规划目标无效')
        start = current.get(stroke, 0)
        # The planner emits the end of every segment. Advancing after that
        # endpoint preserves order even when the next line doubles back.
        if finished.get(stroke) and start+1 < len(rows_by_stroke[stroke]): start += 1
        provenance=command.get('source_segment_id')
        if provenance is not None:
            if (not isinstance(provenance,(list,tuple)) or len(provenance)!=2
                    or provenance[0]!=stroke or type(provenance[1]) is not int
                    or not start<=provenance[1]<len(rows_by_stroke[stroke])):
                raise ValueError('规划原始线段编号无效')
            start=provenance[1]
            stop=start+1
        else:
            stop = min(len(rows_by_stroke[stroke]), start+8)
        a = starts[stroke][start:stop]; delta = vectors[stroke][start:stop]
        norm = np.einsum('ij,ij->i', delta, delta)
        progress = np.clip(np.einsum('ij,ij->i', target-a, delta) / np.maximum(norm, 1e-20), 0, 1)
        distance = np.linalg.norm(target - (a + progress[:, None] * delta), axis=1)
        local = start + int(np.argmin(distance))
        if float(distance[local-start]) > .02: raise ValueError('舵机目标不属于声明的线段')
        current[stroke] = local
        row = rows_by_stroke[stroke][local]
        finished[stroke] = bool(np.linalg.norm(target-np.asarray(row['end_mm'])) < 1e-6)
        if row['predicted_points_mm'] is None:
            row['predicted_points_mm'] = []
            if index and (previous_stroke == stroke or commands[index-1].get('phase') == 'LOWER'):
                row['predicted_points_mm'].append(projected[index-1].tolist())
        row['predicted_points_mm'].append(projected[index].tolist())
        row.setdefault('command_first', index+1)
        row['command_last'] = index+1
        row.setdefault('time_start_s', float(commands[index-1]['t_s']) if index else 0.)
        row['time_end_s'] = float(command['t_s'])
        if command.get('hard_stop'):
            row.setdefault('rest_boundaries_s',[]).append(float(command['t_s']))
        errors.append(float(np.linalg.norm(positions[index] - np.asarray(command['tip_target_m'])) * 1000))
        assigned += 1; previous_stroke = stroke
    if not assigned: raise ValueError('规划没有落笔指令')
    result.update(mode='commands', title='舵机指令模型预测', plan_job_id=data.get('job_id'),
                  drawing_offset_mm=spec.get('drawing_offset_mm',[0,0]),
                  duration_s=data.get('metrics', {}).get('duration_s'),
                  motion_algorithm_version=data.get('metrics',{}).get('motion_algorithm_version'),
                  motion_mode=data.get('metrics',{}).get('motion_mode'),
                  hard_stop_knots=data.get('metrics',{}).get('hard_stop_knots'),
                  peak_jerk_rad_s3=data.get('metrics',{}).get('peak_jerk_rad_s3'),
                  predicted_commands=assigned, max_command_target_error_mm=max(errors),
                  unrepresented_segments=sum(row['predicted_points_mm'] is None for row in result['rows']),
                  explanation=('橙色为整数舵机指令的笔尖模型投影，灰色为期望路径；实际还受标定、间隙和笔压力影响。'
                               if real else '模拟规划的名义模型投影，不代表实物绘画精度。'))
    return result


def export_order_csv(preview, destination):
    """Export every numbered DRAW segment, keeping transfers out of ink order."""
    with Path(destination).open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['全局线段顺序', '笔画顺序', '笔画内线段', '起点X_mm', '起点Y_mm',
                         '终点X_mm', '终点Y_mm', '长度_mm', '首指令序号', '末指令序号'])
        for row in preview['rows']:
            writer.writerow([row['order'], row['stroke'], row['stroke_segment'], *row['start_mm'],
                             *row['end_mm'], row['length_mm'], row.get('command_first', ''),
                             row.get('command_last', '')])


def export_preview_svg(preview, destination, numbers=False):
    width, height = preview['width_mm'], preview['height_mm']
    def point(p):
        return (p[0], p[1] if preview['coordinate_system'] == 'full_canvas_xy_down' else height-p[1])
    def points(chain): return ' '.join('%.6f,%.6f' % point(p) for p in chain)
    body = ['<rect width="100%" height="100%" fill="white"/>']
    if preview['mode'] in ('commands','feedback'):
        for row in preview['rows']:
            body.append('<polyline points="%s" fill="none" stroke="#cbd5e1" stroke-width=".15"/>' %
                        points([row['start_mm'], row['end_mm']]))
    for row in preview['rows']:
        chain = row['predicted_points_mm'] if preview['mode'] in ('commands','feedback') else [row['start_mm'], row['end_mm']]
        if chain:
            if len(chain)==1 and preview['mode']=='feedback':
                x,y=point(chain[0]);body.append('<circle cx="%.6f" cy="%.6f" r=".11" fill="#111827"/>' % (x,y))
            else:
                body.append('<polyline points="%s" fill="none" stroke="#111827" stroke-width=".22" stroke-linecap="round"/>' % points(chain))
        if numbers:
            x, y = point([(a+b)/2 for a, b in zip(row['start_mm'], row['end_mm'])])
            body.append('<text x="%.6f" y="%.6f" font-size="1.4" fill="#2563eb">%d</text>' % (x, y, row['order']))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 %.6f %.6f">'
           '<title>%s</title><desc>%s</desc>%s</svg>') % (
               width+4, height+4, escape(preview['title']), escape(preview['explanation']), ''.join(body))
    Path(destination).write_text(svg, encoding='utf-8')
