"""Checks for the actual SDK joint-linear path; no IO or motion."""
import numpy as np

# Part of the preparation identity: older full-node preparations must be rebuilt.
MERGE_VERSION = 'brush-joint-merge-v1'


class _Geometry:
    def __init__(self, config, nodes, model):
        from tcb705.artifact import check_brush_nodes
        check_brush_nodes(nodes, config)
        self.config = config; self.model = model
        from .couplets import surface
        self.paper = surface(config, nodes.get('calligraphy')); p = self.paper
        self.origin = np.asarray(p['origin_m'])
        self.axes = np.stack([p['x_axis'], p['y_axis']], axis=1)
        self.normal = np.cross(p['x_axis'], p['y_axis'])
        if not np.allclose(self.normal, [0, 0, 1], atol=1e-6):
            raise ValueError('毛笔首版需要水平纸面标定')
        self.maximum = nodes['calligraphy']['brush']['max_press_mm'] * .001
        self.q = (model.from_sdk_batch(nodes['sdk_degrees']) if hasattr(model, 'from_sdk_batch')
                  else np.asarray([model.from_sdk(row) for row in nodes['sdk_degrees']]))
        self.phases = np.asarray(nodes['interval_phase'])
        self.mm = np.asarray(nodes['positions_m']) * 1000.
        self.arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(self.mm, axis=0), axis=1))]
        self.grids = {}
        self.rotation = np.asarray(config['tool_rotation'])
        self.cached = {}

    def sample_spec(self, a, b):
        # Verify both uniform samples and the original knots' arc positions.
        # The latter also prevents shortcutting a small hook or pressure change.
        count = max(16, int(np.ceil(np.max(np.abs(self.q[b]-self.q[a])) /
                                   self.config['planning']['verify_step_rad'])))
        if count not in self.grids:
            self.grids[count] = np.linspace(0., 1., count+1)
        fractions = self.grids[count]
        span = self.arc[b]-self.arc[a]
        knots = (self.arc[a:b+1]-self.arc[a])/span if span > 1e-12 else np.linspace(0., 1., b-a+1)
        fractions = np.unique(np.concatenate((fractions, knots)))
        return fractions, knots

    def prefetch(self, pairs):
        """Bounded FK batches; exactly the same probes as samples(), no coarser grid."""
        self.cached.clear()
        specs = [(a, b, *self.sample_spec(a, b)) for a, b in pairs]
        if not specs:
            return
        rows = np.concatenate([self.q[a]+(self.q[b]-self.q[a])*f[:, None]
                               for a, b, f, _ in specs])
        poses = self.model.fk_batch(rows)
        phases = np.concatenate([np.full(len(f), self.phases[a]) for a, _, f, _ in specs])
        violations = self.violations(poses, phases)
        offset = 0
        for a, b, f, knots in specs:
            end = offset+len(f)
            self.cached[(a, b)] = (poses[offset:end], f, knots,
                                  int(np.bitwise_or.reduce(violations[offset:end])))
            offset = end

    def samples(self, a, b):
        if (a, b) in self.cached:
            return self.cached[(a, b)][:3]
        fractions, knots = self.sample_spec(a, b)
        poses = self.model.fk_batch(self.q[a]+(self.q[b]-self.q[a])*fractions[:, None])
        return poses, fractions, knots

    def violations(self, poses, phase):
        """One bit per old check, preserving rejection priority in raise_violation."""
        xyz = poses[:, :3, 3]
        code = (~np.isfinite(poses).all(axis=(1, 2))).astype(np.uint8)
        angle = np.arccos(np.clip((np.einsum('nij,ij->n', poses[:, :3, :3],
                                           self.rotation)-1)/2, -1, 1))
        code |= (angle > self.config['planning']['orientation_tolerance_rad']).astype(np.uint8)*2
        signed = (xyz-self.origin) @ self.normal
        tol = self.config['planning']['path_tolerance_m']
        code |= (signed < -self.maximum-tol).astype(np.uint8)*4
        contact = signed < -tol
        code |= (contact & ~np.isin(phase, (1, 2, 4))).astype(np.uint8)*8
        xy = (xyz-self.origin) @ self.axes * 1000.
        outside = ((xy[:, 0] < 0) | (xy[:, 1] < 0) |
                   (xy[:, 0] > self.paper['width_mm']) | (xy[:, 1] > self.paper['height_mm']))
        code |= (contact & outside).astype(np.uint8)*16
        return code

    @staticmethod
    def raise_violation(code):
        errors = ((1, 'BRUSH_GEOMETRY: 插值结果无效'),
                  (2, 'BRUSH_ORIENTATION: 下发插值过程笔轴偏离竖直，请减小采样间距'),
                  (4, 'BRUSH_DEPTH: 插值下压超过已保存上限'),
                  (8, 'BRUSH_TRAVEL: 空走段侵入纸面'),
                  (16, 'BRUSH_PAPER: 下压位置超出纸面'))
        for bit, message in errors:
            if code & bit:
                raise ValueError(message)

    def check_segment(self, a, b, poses):
        if (a, b) in self.cached:
            self.raise_violation(self.cached[(a, b)][3])
        else:
            self.check(poses, int(self.phases[a]))

    def check(self, poses, phase):
        self.raise_violation(int(np.bitwise_or.reduce(self.violations(poses, phase))))


def check_geometry(config, nodes, model, keep=None):
    """Check the points actually sent to the SDK, including merged joint segments."""
    g = _Geometry(config, nodes, model)
    keep = list(range(len(g.q))) if keep is None else list(keep)
    for a, b in zip(keep[:-1], keep[1:]):
        poses, _, _ = g.samples(a, b)
        g.check(poses, int(g.phases[a]))


def refine_merged(config, nodes, model, keep, settings):
    """Split unsafe candidate merges back to original knots, never weaken guards.

    Native merging supplies geometric candidates. This second pass checks the
    executed joint interpolation's orientation, pressure, paper and path. A
    rejected merge is subdivided; an invalid original interval remains an error.
    """
    from tcb705.web_executor import NEAR_PAPER, _polyline_distance
    g = _Geometry(config, nodes, model)
    stops = set(nodes.get('stops', []))
    out = [0]

    def append(a, b):
        # Be defensive even if a candidate source changes in the future.
        boundary = next((i for i in range(a+1, b)
                         if i in stops or g.phases[i] != g.phases[a]), None)
        if boundary is not None:
            append(a, boundary); append(boundary, b); return
        poses, fractions, knots = g.samples(a, b)
        near = int(g.phases[a]) in NEAR_PAPER
        tol = min(settings['joint_merge_tolerance_mm'], .02) if near else settings['joint_air_merge_tolerance_mm']
        final_tol = settings['joint_draw_tolerance_mm'] if near else settings['joint_air_tolerance_mm']
        tol = min(tol, final_tol)
        problem = None
        try:
            g.check_segment(a, b, poses)
            actual = poses[:, :3, 3] * 1000.
            # Actual -> planned path, and original planned knot -> its matching
            # executed position, so a tiny pressure peak/hook cannot disappear.
            dev = max(float(_polyline_distance(actual, g.mm[a:b+1]).max()),
                      float(np.linalg.norm(actual[np.searchsorted(fractions, knots)]-
                                           g.mm[a:b+1], axis=1).max()))
            if not np.isfinite(dev) or dev > tol:
                raise ValueError('BRUSH_PATH: 关节插值偏离毛笔轨迹 %.6f mm' % dev)
        except ValueError as exc:
            problem = exc
        if problem is None:
            out.append(b)
        elif b == a+1:
            raise problem
        else:
            middle = (a+b)//2
            append(a, middle); append(middle, b)

    pairs = [(int(a), int(b)) for a, b in zip(keep[:-1], keep[1:])]
    # At most 32 candidate segments retained at once. A candidate spanning many
    # knots is evaluated singly. Recursive splits are checked before acceptance.
    batch = []; samples = 0
    for a, b in pairs:
        count = max(16, int(np.ceil(np.max(np.abs(g.q[b]-g.q[a])) /
                                   config['planning']['verify_step_rad']))) + b-a+2
        if batch and (len(batch) >= 32 or samples+count > 4096):
            g.prefetch(batch)
            for lo, hi in batch: append(lo, hi)
            batch = []; samples = 0
        batch.append((a, b)); samples += count
    if batch:
        g.prefetch(batch)
        for lo, hi in batch: append(lo, hi)
    return out
