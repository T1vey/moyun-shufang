"""Motion blending (SDK smooth level) for every drawing feature, in one place.

2026-10-29 trial (record: docs/smooth_trial_20261029.md): every feature blends gentle on-paper
bends at smooth 4 with 4 SDK moves queued. Corners, pen down/up, planned stops, stroke ends and
every move in the air stay exact stops (smooth 0); 复位 / home moves are never blended.

To go back to the behaviour before the trial, set TRIAL = False and restart the UI (reboot).
"""
TRIAL = True

QUEUE_DEPTH = 4        # blending needs more than one queued move (sdk_motion.pump forces 0 at depth 1)

if TRIAL:
    SMOOTH = 4
    # 名帖表演 / 诗词 / 春联 / 硬笔 (fixed speed): bends up to 45 deg.
    PERFORMANCE_BLEND = dict(smooth=SMOOTH, corner_deg=45.0, draw_only=True)
    # 毛笔页面 / 字帖 / phone text pages at the screen speed: same rule as the performances.
    PAGE_BLEND = dict(smooth=SMOOTH, corner_deg=45.0, draw_only=True)
    # 图案 / line art with the pen at the screen speed: gentle drawing vertices only.
    LINEART_SMOOTH = SMOOTH
    # 屏上手写 (live handwriting): bends up to 20 deg.
    HANDWRITING_BLEND = dict(smooth=SMOOTH, corner_deg=20.0, draw_only=True)
else:
    # Before 2026-10-29: performances and handwriting at 3; screen-speed runs exact stops only.
    PERFORMANCE_BLEND = dict(smooth=3, corner_deg=45.0, draw_only=True)
    PAGE_BLEND = None
    LINEART_SMOOTH = None
    HANDWRITING_BLEND = dict(smooth=3, corner_deg=20.0, draw_only=True)
