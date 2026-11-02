"""Explicit application edition; package defaults never infer an FPGA ABI."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IP_NAMES = {'wls': 'z20_wls_step_0', 'upstream': 'xf_solver_lm_so101_0'}


def default_engine():
    path = ROOT/'config/edition.json'
    value = json.loads(path.read_text(encoding='utf-8'))['ik_engine'] if path.exists() else 'wls'
    if value not in IP_NAMES:
        raise ValueError('Unsupported package IK edition')
    return value


def make_backend(engine, overlay=None, ip_name=None, pl_mode="wls", pl_load_policy='download',
                 platform_manifest=None, platform_ready=None):
    if pl_load_policy not in ('download','attach'):
        raise ValueError('Unsupported PL load policy')
    if pl_load_policy=='attach' and (engine!='wls' or pl_mode not in ('target','planner') or not overlay):
        raise ValueError('attach requires the complete target IK platform')
    if engine not in IP_NAMES:
        raise ValueError('Unsupported IK engine')
    if pl_mode not in ("wls", "full", "target", "planner"):
        raise ValueError("Unsupported PL mode")
    if engine == 'upstream':
        if pl_mode != "wls":
            raise ValueError("full task-step 只对应当前 wls 数学合同")
        from upstream_backend import UpstreamBackend
        return UpstreamBackend(overlay, ip_name or IP_NAMES[engine])
    if pl_mode == 'planner':
        if not overlay:
            raise ValueError('--pl-mode planner requires a matching v2 --overlay')
        from planner_accel_backend import PynqPlannerAccel
        return PynqPlannerAccel(overlay,ip_name or 'planner_accel_v2_0',load_policy=pl_load_policy,
            platform_manifest=platform_manifest,platform_ready=platform_ready)
    if pl_mode == 'target':
        if not overlay:
            raise ValueError('--pl-mode target requires a matching --overlay')
        from ik_target_backend import PynqIKTarget
        return PynqIKTarget(overlay,ip_name or 'z20_ik_target_0',load_policy=pl_load_policy,
            platform_manifest=platform_manifest,platform_ready=platform_ready)
    if overlay and pl_mode == "full":
        if engine != "wls":
            raise ValueError("full task-step 只对应当前 z20_wls_step 数学合同")
        from ik_backend import PynqIKStep
        return PynqIKStep(overlay, ip_name or "z20_ik_step_0")
    if pl_mode == "full":
        raise ValueError("--pl-mode full requires a matching --overlay")
    if overlay:
        from pl_backend import PynqStep
        return PynqStep(overlay, ip_name or IP_NAMES[engine])
    return None
